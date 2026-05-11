# Supply Chain Intelligence Agent — Capstone Project

An **Industrial Agentic AI System** built with **LangGraph** that serves as
an intelligent assistant for supply chain managers. The system performs
real-time inventory analysis, supplier intelligence, reorder-risk scoring,
automated procurement-email drafting, and post-deployment drift monitoring.

> **New here?** Read [`docs/VIVA_GUIDE.md`](docs/VIVA_GUIDE.md) for a
> plain-English, end-to-end walkthrough of every Lab and every file in
> this repository. The formal write-up of Labs 9 (Industrial Packaging)
> and 10 (Quality Gate) lives in [`docs/REPORT.md`](docs/REPORT.md).

## Repository layout

```
Capstone/
├── src/                              # Application package
│   ├── paths.py                      # Centralised filesystem paths
│   ├── core/                         # LangGraph workflows + tools (Labs 3, 4, 5, 6, 9, 10)
│   │   ├── graph.py                  # Single-agent ReAct loop
│   │   ├── multi_agent_graph.py      # Researcher → Analyst orchestration
│   │   ├── secured_graph.py          # Guardrail-fronted graph
│   │   ├── tools.py                  # The 5 supply-chain tools
│   │   ├── llm_factory.py            # Pluggable Gemini / Groq backend
│   │   ├── agents_config.py          # Agent personas
│   │   ├── guardrails_config.py      # Pydantic + LLM judge guardrails
│   │   └── approval_logic.py         # HITL approval gate
│   ├── api/                          # FastAPI layer (Lab 8)
│   │   ├── main.py                   # /health, /chat, /stream
│   │   └── schema.py                 # Pydantic request/response models
│   ├── ingestion/                    # ChromaDB seeding (Lab 2)
│   │   └── ingest_data.py
│   ├── ui/                           # Streamlit chat UI (Labs 11–12)
│   │   └── app.py                    # Good 👍 / Bad 👎 feedback UI
│   └── feedback/                     # Post-deployment monitoring (Labs 11–12)
│       ├── analyze_feedback.py       # Lab 11 — LLM-clustered drift report
│       └── analyze.py                # Lab 12 — counts + top failed queries
│
├── data/                             # Seed CSVs + product specs (Lab 1)
│
├── tests/
│   ├── persistence_test.py           # Lab 5 persistence demo
│   └── test_dataset.json             # 22-case curated eval set
│
├── evaluation/                       # Lab 7 + Lab 10 quality gate
│   ├── run_eval.py                   # CI-grade eval pipeline
│   ├── eval_thresholds.json          # Versioned thresholds + justifications
│   └── eval_threshold_config.json    # Legacy threshold filename
│
├── scripts/                          # CI helpers (Lab 10)
│   ├── break_agent.py / restore_agent.py
│   ├── summarise_eval.py
│   └── validate_thresholds.py
│
├── docker/                           # Lab 9 deployment artefacts
│   ├── Dockerfile                    # Multi-stage slim-bookworm build
│   ├── docker-compose.yaml           # 3 services (chromadb / ingest / api)
│   └── entrypoint.sh                 # Wait-for-chromadb shim
│
├── docs/                             # All Markdown / TXT reports
│   ├── PRD.md, REPORT.md, VIVA_GUIDE.md
│   ├── agent_personas.md, retrieval_test.md, grounding_justification.txt
│   ├── security_report.md, bottleneck_analysis.txt, observability_link.txt
│   ├── drift_report.md, improved_prompt.txt, api_test_results.txt
│   ├── collaboration_trace.log
│   ├── analysis_report.md            # Lab 12 — basic feedback analytics
│   └── improvement_demo.md           # Lab 12 — issue, fix, before/after
│
├── runtime/                          # Writable state (git-ignored, Docker-volumed)
│   ├── feedback_log.db               # SQLite primary feedback store
│   ├── feedback_log.json             # Lab 12 JSON mirror
│   ├── checkpoint_db.sqlite          # LangGraph checkpoint
│   └── chroma_db/                    # Local ChromaDB shards
│
├── .github/workflows/main.yml        # CI/CD pipeline (Lab 10)
├── pyproject.toml                    # Package metadata
├── requirements.txt
├── .env.example
└── README.md
```

## Lab → file map

| Lab | Topic                                | Key locations |
|-----|--------------------------------------|---------------|
| 1   | Problem framing & architecture       | `docs/PRD.md`, `data/` |
| 2   | Knowledge engineering & RAG          | `src/ingestion/ingest_data.py`, `docs/retrieval_test.md`, `docs/grounding_justification.txt` |
| 3   | Reasoning loop (LangGraph)           | `src/core/tools.py`, `src/core/graph.py` |
| 4   | Multi-agent orchestration            | `src/core/multi_agent_graph.py`, `src/core/agents_config.py`, `docs/agent_personas.md` |
| 5   | State management & HITL              | `tests/persistence_test.py`, `src/core/approval_logic.py` |
| 6   | Security guardrails                  | `src/core/guardrails_config.py`, `src/core/secured_graph.py`, `docs/security_report.md` |
| 7   | Evaluation & observability           | `tests/test_dataset.json`, `evaluation/run_eval.py`, `docs/bottleneck_analysis.txt`, `docs/observability_link.txt` |
| 8   | FastAPI layer                        | `src/api/schema.py`, `src/api/main.py`, `docs/api_test_results.txt` |
| 9   | Industrial packaging & deployment    | `docker/Dockerfile`, `docker/docker-compose.yaml`, `docker/entrypoint.sh`, `docs/REPORT.md` §1 |
| 10  | Automated quality gate (CI/CD)       | `.github/workflows/main.yml`, `evaluation/eval_thresholds.json`, `scripts/`, `docs/REPORT.md` §2 |
| 11  | Drift monitoring & feedback (LLM)    | `src/ui/app.py`, `src/feedback/analyze_feedback.py`, `docs/drift_report.md`, `docs/improved_prompt.txt` |
| 12  | Post-deployment feedback loop        | `src/feedback/analyze.py`, `runtime/feedback_log.{db,json}`, `docs/analysis_report.md`, `docs/improvement_demo.md` |

## Tech stack

* **LLM**: Google Gemini (default) or Groq Llama (fallback). Provider
  selection is handled by [`src/core/llm_factory.py`](src/core/llm_factory.py).
* **Orchestration**: LangGraph (stateful agent + tool loop, SQLite
  checkpointer for memory).
* **Vector DB**: ChromaDB (HTTP service in Docker, local persistent client
  for dev).
* **API**: FastAPI (`/health`, `/chat`, `/stream`).
* **Frontend**: Streamlit (Labs 11–12 demo).
* **Containerization**: Docker (multi-stage) + Docker Compose
  (three-service orchestration).
* **CI/CD**: GitHub Actions (lint job + automated quality gate).

## Quick start (local dev, no Docker)

```bash
git clone https://github.com/attaquarks/Capstone.git
cd Capstone
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Either provider works. Gemini is the default.
echo "GEMINI_API_KEY=your-gemini-key" > .env
# or, to use Groq:
# printf 'GROQ_API_KEY=your-groq-key\nLLM_PROVIDER=groq\n' > .env

# Make src/ importable for the module-style invocations below.
export PYTHONPATH=.

python -m src.ingestion.ingest_data           # Lab 2: build the vector index
python -m src.core.graph                      # Lab 3: interactive ReAct loop
uvicorn src.api.main:app --port 8000          # Lab 8: REST API
streamlit run src/ui/app.py                   # Labs 11–12: Streamlit chat UI
```

## Quick start (Docker — Lab 9)

```bash
echo "GEMINI_API_KEY=your-gemini-key" > .env       # secret stays on host
# or:  printf 'GROQ_API_KEY=...\nLLM_PROVIDER=groq\n' > .env
docker compose -f docker/docker-compose.yaml up -d --build

curl -s http://localhost:8000/health                                          # → "healthy"
curl -s -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"What is PRD-001 stock?","thread_id":"demo"}'
```

## Quality gate (Lab 10)

Run the same evaluation that the CI pipeline runs on every push:

```bash
export PYTHONPATH=.

# Healthy run
EVAL_SMOKE=1 python -m evaluation.run_eval
echo "exit=$?"           # 0 ⇒ build PASS

# Demonstrate the gate firing on a degraded agent
python scripts/break_agent.py
EVAL_SMOKE=1 python -m evaluation.run_eval
echo "exit=$?"           # 1 ⇒ build FAIL

# Restore
python scripts/restore_agent.py
EVAL_SMOKE=1 python -m evaluation.run_eval
echo "exit=$?"           # 0 ⇒ build PASS
```

Output files: `evaluation/eval_results.json` (machine-readable, schema in
[`docs/REPORT.md`](docs/REPORT.md) §2.1) and `evaluation/evaluation_report.md`
(human summary). Thresholds are versioned in
[`evaluation/eval_thresholds.json`](evaluation/eval_thresholds.json) with
per-metric justifications.

## Post-deployment feedback (Labs 11–12)

```bash
export PYTHONPATH=.

# 1. Collect feedback through the Streamlit UI (Good 👍 / Bad 👎 buttons)
streamlit run src/ui/app.py

# 2. Run the Lab 12 deliverable: counts + top 3 failed queries
python -m src.feedback.analyze

# 3. (Optional) Run the Lab 11 LLM-clustered drift analysis
python -m src.feedback.analyze_feedback
```

Outputs land in [`runtime/feedback_log.db`](runtime/feedback_log.db) (primary
SQLite store) and [`runtime/feedback_log.json`](runtime/feedback_log.json)
(JSON mirror auto-exported on every feedback event). Reports go to
[`docs/analysis_report.md`](docs/analysis_report.md) (Lab 12) and
[`docs/drift_report.md`](docs/drift_report.md) (Lab 11). The Lab 12
before/after improvement story is in
[`docs/improvement_demo.md`](docs/improvement_demo.md).

## Use case

The agent helps supply-chain managers with:

* **Inventory monitoring** — real-time stock + reorder alerts.
* **Risk assessment** — automated scoring from stock, lead time, and
  supplier reliability.
* **Supplier intelligence** — semantic search across supplier catalogues.
* **Procurement automation** — drafting professional RFQ emails (with
  human-in-the-loop approval, see Lab 5).
* **Specs lookup** — technical specifications from the knowledge base.

## Environment variables

| Variable                  | Description                                                                                | Required                        |
|---------------------------|--------------------------------------------------------------------------------------------|---------------------------------|
| `GEMINI_API_KEY`          | Google Gemini API key (or set `GOOGLE_API_KEY`).                                            | One of `GEMINI`/`GROQ` required |
| `GROQ_API_KEY`            | Groq API key (used when set, or when `LLM_PROVIDER=groq`).                                  | One of `GEMINI`/`GROQ` required |
| `LLM_PROVIDER`            | Force `groq` or `google`. Auto-detected from whichever key is set if left unset.            | No                              |
| `AGENT_MODEL`             | Override the agent's chat model. Defaults differ per provider.                              | No                              |
| `JUDGE_MODEL`             | Override the eval judge model.                                                              | No                              |
| `CHROMA_HOST`/`CHROMA_PORT` | Set when running against a remote ChromaDB (Compose sets these to `chromadb:8000`).        | No (Docker auto-sets them)      |
| `CHECKPOINT_DB_PATH`      | Where the LangGraph SQLite checkpoint DB lives (Docker mounts a volume here).               | No                              |
| `FEEDBACK_DB_PATH`        | Where the Streamlit feedback SQLite DB lives.                                               | No                              |
| `FEEDBACK_JSON_PATH`      | Where the Lab 12 JSON mirror is written.                                                    | No                              |
| `PROJECT_ROOT`            | Override the auto-detected repo root (used by `src/paths.py`).                              | No                              |
| `EVAL_SMOKE`/`EVAL_SMOKE_SIZE` | Run only the first N test cases (CI fast path).                                       | No                              |
| `EVAL_PAUSE_SECONDS`      | Sleep between LLM calls in `evaluation/run_eval.py` to stay under free-tier rate limits.    | No                              |
| `LANGCHAIN_TRACING_V2` / `LANGCHAIN_API_KEY` | Optional LangSmith tracing.                                              | No                              |
