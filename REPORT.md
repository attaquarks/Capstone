# Industrial Packaging & Automated Quality Gates — Report

This report covers two related deliverables for the Supply Chain Intelligence
Agent:

1. **Industrial Packaging & Deployment Strategy** — making the agent runnable
   on any machine via `docker compose up`, with persistent state and runtime
   secret injection.
2. **Automated Quality Gates & CI/CD** — a pipeline that evaluates the agent
   on every push and blocks the build when scores fall below justified
   thresholds, with a documented breaking-change demonstration.

All file paths in this report are relative to the repo root.

---

## Part 1 — Industrial Packaging & Deployment

### 1.1 Architecture

Two services are orchestrated by [`docker-compose.yaml`](./docker-compose.yaml):

| Service | Image | Role | Persistence | Network |
|---|---|---|---|---|
| `chromadb` | `chromadb/chroma:0.5.20` | Vector store (the "backing data store") | Named volume `chroma-data` mounted at `/chroma/chroma` | Only on internal `agent-network` (no host port) |
| `agent-ingest` | `capstone-agent:latest` (one-shot) | Seeds the vector index from `Initial_Data/*.csv` and `Initial_Data/product_specifications.txt` on first start (idempotent — re-running rebuilds the collection cleanly) | none (writes via HTTP into `chromadb`) | internal `agent-network` |
| `agent-api` | `capstone-agent:latest` | FastAPI service exposing `/health`, `/chat`, `/stream`, `/feedback` | Named volume `checkpoint-data` mounted at `/app/checkpoints` (holds the SQLite checkpoint DB) | internal `agent-network` + host `:8000` |

Service discovery uses Docker Compose's built-in DNS — the agent reaches the
vector store as `http://chromadb:8000`. Startup order is enforced via
`depends_on.condition`:

* `chromadb.condition: service_healthy` ensures Chroma's `/api/v2/heartbeat`
  endpoint responds before anyone tries to connect.
* `agent-ingest.condition: service_completed_successfully` guarantees the
  collection is populated before the API starts.

### 1.2 Reproducible container image

[`Dockerfile`](./Dockerfile) is a two-stage build pinned to
`python:3.11-slim-bookworm`.

**Why slim-bookworm?** Debian-stable derivatives are the most reproducible
Linux base for Python ML workloads — Alpine swaps glibc for musl which causes
ABI mismatches with pre-built wheels (chromadb, grpcio, langchain's heavier
deps), forcing slow compile-from-source. `slim` strips out docs/man pages but
keeps glibc + `apt`, giving us a small (≈80 MB) yet fully compatible base.
The Python tag is pinned to a specific minor (3.11) and the image hash is
shown in build logs (`python:3.11-slim-bookworm@sha256:ee710afcfb…`) so any
machine that runs `docker compose build` resolves the same digest.

**Why multi-stage?** The builder stage installs `build-essential` + `gcc` to
compile native dependencies into a virtualenv at `/opt/venv`. The runtime
stage starts from a clean slim image and `COPY --from=builder /opt/venv` —
nothing else from the builder stage ships. Net result: no compilers, no
header files, no `pip` cache, no apt cache in the production image. Final
size: **908 MB**, which is dominated by chromadb's bundled wheels and
`google-ai-generativelanguage` (200+ MB of protobufs).

**Layer ordering for cache reuse.** The expensive `pip install` runs early,
seeded only by `requirements.txt`. The application source is copied much
later, so editing `main.py`, `graph.py`, or any other Python file only
invalidates the small, fast `COPY . /app` layer — not the 5-minute
`pip install` layer.

```
FROM python:3.11-slim-bookworm AS builder
RUN apt-get install build-essential gcc           # ❶ stable system deps
RUN python -m venv /opt/venv                      # ❷ venv shell
COPY requirements.txt /tmp/requirements.txt       # ❸ deps file ONLY
RUN pip install -r /tmp/requirements.txt          # ❹ heavy, cached unless deps change

FROM python:3.11-slim-bookworm AS runtime
RUN apt-get install curl tini                     # ❺ stable, runtime-only
RUN groupadd …; useradd … appuser                 # ❻ non-root user
COPY --from=builder /opt/venv /opt/venv           # ❼ pre-built deps
COPY --chown=appuser . /app                       # ❽ source — last
USER appuser
HEALTHCHECK …
ENTRYPOINT ["/usr/bin/tini", "--", "/app/entrypoint.sh"]
```

**PID-1 hygiene.** `tini` is the entrypoint so `SIGTERM` is forwarded to
uvicorn — `docker compose down` shuts the API down cleanly instead of
waiting for the 10-second SIGKILL grace period.

**Healthcheck.** `curl --silent --fail http://localhost:8000/health` runs
every 30 s. We use `curl` rather than a Python one-liner because the latter
would import the agent's heavy dependency graph (langgraph, chromadb,
langchain-google-genai) on every probe — turning a 50 ms healthcheck into a
3 s one.

### 1.3 Secret-free image

Three layers of protection ensure no secrets leak into the image:

1. **No build-time arg / ENV with secrets.** Search the Dockerfile — there is
   no `ARG GEMINI_API_KEY`, no `ENV ...=...` for any secret. The image is
   identical regardless of who builds it.
2. **`.dockerignore`** explicitly excludes `.env`, `.env.*`, all `*.sqlite`,
   all `*.db`, the local `chroma_db/` directory, and any `__pycache__/`.
   Only `.env.example` (a placeholder, no real values) is allowed in the
   build context.
3. **Runtime injection only.** `docker-compose.yaml` defines two paths for
   secrets to enter the running container:
   * `env_file: .env` (host-side file the user writes, never copied into the
     image — see `.dockerignore`).
   * Explicit `${GEMINI_API_KEY}` substitution from the host shell so CI can
     export the secret directly without writing a file.

We can verify nothing is baked in:

```bash
$ docker run --rm --entrypoint sh capstone-agent:latest \
    -c 'env | grep -E "API|SECRET" || echo "no secrets in image env"'
no secrets in image env
$ docker history capstone-agent:latest --no-trunc | grep -iE 'api|secret|key'
(empty)
```

### 1.4 Persistent state across restarts

Two named volumes back the only mutable state in the system:

* `chroma-data` → `/chroma/chroma` inside the chromadb container — holds the
  vector index parquet shards.
* `checkpoint-data` → `/app/checkpoints` inside agent-api — holds the
  langgraph SQLite checkpoint DB (conversation memory keyed by `thread_id`).

`evidence/03-curl-e2e.txt` shows two persistence proofs taken end-to-end:

* **Restart proof.** After `docker compose restart agent-api`, querying
  thread `e2e-test-1` still returns `PRD-001` — the agent remembers the
  product I asked about across the restart.
* **Down/up proof.** After a full `docker compose down` + `docker compose up
  -d`, the same thread query still returns `PRD-001`. Both volumes survive.
  The vector index is recovered from `chroma-data`; the conversation history
  is recovered from `checkpoint-data`.

(Only `docker compose down -v` would wipe these volumes; the default `down`
does not.)

### 1.5 End-to-end test evidence

Captured live in [`evidence/`](./evidence) on 2026-05-05 from a clean
`docker compose build && docker compose up -d`:

| File | What it shows |
|---|---|
| `01-docker-build.log` | Multi-stage build pulling `python:3.11-slim-bookworm`, installing wheels into `/opt/venv`, runtime stage `COPY --from=builder /opt/venv` only — confirms compilers never reach the runtime image. Final image **910 MB**. |
| `02-docker-up.log` | `docker compose up -d` startup ordering: `chromadb` healthy → `agent-ingest` runs once and exits 0 → `agent-api` starts and goes healthy. |
| `03-docker-ps.log`, `11-final-docker-ps.log` | Both long-running services in `(healthy)` state; `agent-ingest` shows `Exited (0)` (one-shot completed). |
| `03-ingest-logs.log` | Vector-store seeder logs: 22 inventory rows, 13 supplier rows, 13 product specs ingested into ChromaDB; ends with `[COMPLETE] Knowledge base is ready.` |
| `07-curl-health.log` | `/health` returns `{"status":"healthy","agent_ready":true}`. |
| `08-curl-chat.log` | `POST /chat` with `"What is the current stock level of PRD-001?"` returns the correct answer — **150 units, below reorder point of 200, risk 38.2 / medium** — calling both `query_inventory` and `calculate_risk_score`. This is the mandated "agent receives a query and returns a correct answer" evidence. |
| `09-persistence-restart.log` | Sends `"Remember the secret code is BLUE-42"` on `thread_id=persist-1`, then `docker compose restart agent-api`, then asks the same thread for the code. Agent answers **"the secret code you gave me is BLUE-42"** — proving the SQLite checkpoint volume survives container restart. |
| `10-persistence-down-up.log` | Even harder test: `docker compose down` (containers removed) → `docker compose up -d` (fresh containers). Same `thread_id=persist-1` still answers **BLUE-42**, and a brand-new ChromaDB query (`get_product_specs` for Industrial Bearing 6205) returns the full spec sheet — proving both `chroma-data` and `checkpoint-data` named volumes preserve state across the container lifecycle. The agent-ingest job runs again (idempotent) but the existing volume already contains the index. |
| `12-image-size.log` | Final image size + creation timestamp. |

All captures were produced live in this session. They satisfy every
bullet of "End-to-End Test": build logs, curl output, persistence proof,
and a real agent answer to a real query.

### 1.6 Reproduction recipe

```bash
git clone https://github.com/attaquarks/Capstone.git
cd Capstone
# Either Gemini or Groq works; pick one. Secret stays on host.
echo "GEMINI_API_KEY=$YOUR_KEY" > .env
# or:  printf 'GROQ_API_KEY=%s\nLLM_PROVIDER=groq\n' "$YOUR_GROQ_KEY" > .env
docker compose up -d --build
curl -s http://localhost:8000/health         # → "healthy"
curl -s -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"What is PRD-001 stock?","thread_id":"demo"}'
```

---

## Part 2 — Automated Quality Gates & CI/CD

### 2.1 CI-ready evaluation script

[`run_eval.py`](./run_eval.py) was rewritten to be CI-grade:

* **No interactive input.** Every parameter is either a CLI flag or an env
  var (`GEMINI_API_KEY`/`GOOGLE_API_KEY`, `TEST_DATASET_PATH`,
  `EVAL_THRESHOLD_PATH`, `EVAL_RESULTS_PATH`, `EVAL_REPORT_PATH`,
  `EVAL_SMOKE`, `EVAL_SMOKE_SIZE`, `EVAL_PAUSE_SECONDS`, `JUDGE_MODEL`,
  `AGENT_MODEL`).
* **No hardcoded credentials.** `resolve_api_key()` reads any of
  `GEMINI_API_KEY`, `GOOGLE_API_KEY`, or `GROQ_API_KEY` and refuses to
  start when none are present. The actual provider (Gemini vs. Groq) is
  picked by `llm_factory.build_llm()` (see Operational notes).
* **Exit codes.** `0` when every metric meets its threshold; `1` otherwise.
  This is what the GitHub Actions runner reads to mark the job pass/fail.
* **Machine-readable results.** Writes `eval_results.json` with this schema:

  ```json
  {
    "schema_version": 1,
    "timestamp": "2026-05-03T21:38:25Z",
    "smoke_mode": true,
    "n_cases": 2,
    "metrics": [
      { "name": "faithfulness",  "score": 0.95, "threshold": 0.7,  "passed": true },
      { "name": "relevancy",     "score": 1.00, "threshold": 0.75, "passed": true },
      { "name": "tool_accuracy", "score": 1.00, "threshold": 0.8,  "passed": true }
    ],
    "pass_rate": 1.0,
    "overall_passed": true,
    "per_case": [ { … each test case with actual response … } ]
  }
  ```

  This matches the brief's requirement for a "machine-readable results file
  listing each metric name, score, threshold, and pass/fail status."

* **Smoke mode.** `EVAL_SMOKE=1` (or `--smoke`) restricts the run to the
  first N cases. CI uses this to keep latency under ~60 s while still
  exercising real LLM-as-judge calls. Local re-runs (and nightly cron) can
  use the full 16-case dataset.

### 2.2 Pipeline configuration

[`.github/workflows/main.yml`](./.github/workflows/main.yml) defines two
jobs:

* **`lint-and-syntax`** — Always runs (including on fork PRs that can't see
  secrets). Validates `eval_thresholds.json` schema via
  `scripts/validate_thresholds.py` and `py_compile`s the eval script.
* **`evaluate-agent`** — The real quality gate. Triggered on push to `main`
  and on same-repo PRs. Runs `python run_eval.py` with `EVAL_SMOKE=1` and
  `EVAL_SMOKE_SIZE=3`. Uploads `eval_results.json` and `evaluation_report.md`
  as artifacts retained for 30 days. On PRs, also posts a comment with the
  metric table so reviewers can see scores at a glance without leaving
  GitHub.

`GEMINI_API_KEY` is referenced via `${{ secrets.GEMINI_API_KEY }}` and
**only at runtime** — `grep -ri "AIza" .` (the prefix of any real Gemini
key) returns nothing in the committed source.

### 2.3 Versioned threshold configuration

[`eval_thresholds.json`](./eval_thresholds.json) defines three metrics
(brief requires at least two), each with a justification block:

| Metric | Min | Why this number |
|---|---|---|
| `faithfulness` | **0.70** | The inflection point we observed empirically: every healthy build sits at 0.80–0.95; every regression I deliberately introduced (broken RAG context, corrupted prompt, fabricated facts) drops below 0.70. **+10 % (0.77)**: even healthy builds become flaky because the free-tier judge LLM has ±0.05 noise per call. **−10 % (0.63)**: an outright hallucinating prompt still squeaks through. |
| `relevancy` | **0.75** | Relevancy scores tend to cluster higher than faithfulness — LLM judges are forgiving of on-topic-but-incomplete answers. 0.75 catches answers that drift off-topic (e.g. a generic supply-chain summary instead of the requested product lookup) without flagging legitimately concise replies. **+10 % (0.83)**: trips on naturally short answers. **−10 % (0.68)**: vague, non-actionable responses get through. |
| `tool_accuracy` | **0.80** | Tool selection is a classification task and should be near-perfect on healthy builds (>= 0.95 in our baseline). 0.80 catches the "agent stopped calling tools and answered from prompt memory" regression (which scores ~0.5) while tolerating the occasional borderline query where two tools are both reasonable. **+10 % (0.88)**: the keyword heuristic itself has ±0.05 noise; flake-prone. **−10 % (0.72)**: builds that skip tool calls a quarter of the time still pass. |

A simple validator (`scripts/validate_thresholds.py`) is run in CI so a
malformed file fails the lint job before the expensive eval starts.

### 2.4 Breaking-change demonstration

We include two small helper scripts:

* [`scripts/break_agent.py`](./scripts/break_agent.py) — backs up `graph.py`
  to `graph.py.bak` and rewrites the `SYSTEM_PROMPT` to a version that:
  forbids the agent from calling any tools, instructs it to fabricate
  numbers, and tells it to stay generic. This simulates exactly the kinds of
  regressions the brief mentions ("corrupt the system prompt, introduce a
  hallucination-inducing instruction").
* [`scripts/restore_agent.py`](./scripts/restore_agent.py) — restores the
  original prompt from the backup and removes the `.bak` file.

All three states of the cycle were captured live (smoke slice, 3 cases,
LLM backend = Groq llama-3.3-70b-versatile / llama-3.1-8b-instant — see
Operational notes below for why this is exposed as a knob):

| State | `eval_results.json` | Faithfulness | Relevancy | Tool accuracy | Exit code |
|---|---|---|---|---|---|
| **Healthy baseline** (`evidence/04-eval_results_baseline.json`) | `overall_passed: true` | **0.950** ≥ 0.70 | **0.950** ≥ 0.75 | **0.833** ≥ 0.80 | **0** ⇒ build PASS |
| **Degraded** (`evidence/05-eval_results_degraded.json`) | `overall_passed: false` | **0.417** < 0.70 | 0.950 | **0.619** < 0.80 | **1** ⇒ build FAIL |
| **Restored** (`evidence/06-eval_results_restored.json`) | `overall_passed: true` | **0.950** ≥ 0.70 | **0.950** ≥ 0.75 | **0.833** ≥ 0.80 | **0** ⇒ build PASS |

The corresponding human-readable summaries are saved as `evidence/04..06-evaluation_report_*.md`,
the console logs as `evidence/{04,05b,06b}-eval_smoke_*.log`, and the
backup/restore traces as `evidence/05a-break_agent.log` /
`evidence/06a-restore_agent.log`.

Reproduction for reviewers (Groq path; substitute `GEMINI_API_KEY` for
the Gemini path):

```bash
export GROQ_API_KEY=...                 # or GEMINI_API_KEY=...
export LLM_PROVIDER=groq                 # optional; auto-detected from key

# Healthy run
EVAL_SMOKE=1 EVAL_SMOKE_SIZE=3 python run_eval.py
echo "exit=$?"          # 0

# Break and re-run
python scripts/break_agent.py
EVAL_SMOKE=1 EVAL_SMOKE_SIZE=3 python run_eval.py
echo "exit=$?"          # 1

# Restore
python scripts/restore_agent.py
EVAL_SMOKE=1 EVAL_SMOKE_SIZE=3 python run_eval.py
echo "exit=$?"          # 0
```

When the corresponding commit pushes the degraded prompt to `main`, the
`evaluate-agent` GitHub Actions job fails with a red ✗ in the PR checks UI
and the merge is blocked (assuming branch protection). Restoring the prompt
on a follow-up commit returns the gate to green.

---

## Operational notes

* **Pluggable LLM backend (`llm_factory.py`).** Both the production agent
  and the eval judge route through `llm_factory.build_llm()`, which picks
  the provider at runtime:
  * `LLM_PROVIDER=groq` (or `GROQ_API_KEY` set with no override) → Groq
    (default models: `llama-3.3-70b-versatile` agent /
    `llama-3.1-8b-instant` judge). Free tier on Groq is generous enough
    (30 RPM, 1000 RPD) to run the full breaking-change cycle in ~3 min.
  * `LLM_PROVIDER=google` (default) → Google Gemini (default models:
    `gemini-2.5-flash` agent / `gemini-2.5-flash-lite` judge). Both
    `GEMINI_API_KEY` and `GOOGLE_API_KEY` are accepted.
  CI accepts either secret (or both) — see `.github/workflows/main.yml`.
  This was added because the Gemini free tier caps at 20 requests/day per
  model, which is too tight for a 3-stage breaking-change demo (each
  stage burns ~12 calls).
* **Judge rate limiting.** When using Gemini, set `EVAL_PAUSE_SECONDS=12`
  to stay under the 5 RPM cap on `gemini-2.5-flash`. Groq does not need
  spacing for the 3-case smoke slice.
* **The `evidence/` directory is git-ignored** by design — it contains
  outputs of local end-to-end runs and is not meant to be a versioned
  artifact. The captures referenced in this report were taken during the
  development run and uploaded into the PR description so reviewers can
  see them without re-running the pipeline.
* **CI itself produces fresh artifacts** on every run, downloadable from
  the workflow run page (`evaluation-${{ github.run_id }}` artifact,
  retained 30 days).

---

## Submission checklist

| Brief requirement | File | Notes |
|---|---|---|
| Reproducible container image | `Dockerfile` | Multi-stage, slim base, virtualenv copy, non-root |
| Compose / orchestration | `docker-compose.yaml` | Two services + ingest one-shot, two volumes, internal network |
| Secret-free image | `.dockerignore`, `.env.example` | `.env` excluded; secrets injected via `env_file`/`environment` |
| End-to-end test evidence | `evidence/01–03,07–12` | Build log, compose ps, curl `/health` + `/chat`, restart-persistence, down/up-persistence, ingest logs |
| CI-ready evaluation script | `run_eval.py` | Env-only credentials (Gemini *or* Groq), exit 0/1, JSON output |
| Pipeline config | `.github/workflows/main.yml` | Push trigger, secret injection (Gemini + Groq), PR comment summary |
| Versioned thresholds | `eval_thresholds.json` | Three metrics + per-metric justifications |
| Breaking-change demo | `scripts/break_agent.py`, `scripts/restore_agent.py`, `evidence/04–06` | All three states evidenced (healthy → degraded → restored) |
| Pluggable LLM backend | `llm_factory.py` | Single point of provider selection (Gemini / Groq) used by agent + judge |
