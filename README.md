# Supply Chain Intelligence Agent — Capstone Project

An **Industrial Agentic AI System** built with **LangGraph** that serves as
an intelligent assistant for supply chain managers. The system performs
real-time inventory analysis, supplier intelligence, reorder-risk scoring,
and automated procurement-email drafting.

> **New here?** Read [`VIVA_GUIDE.md`](./VIVA_GUIDE.md) for a plain-English,
> end-to-end walkthrough of every Lab and every file in this repository.
> The formal write-up of Labs 9 (Industrial Packaging) and 10 (Quality
> Gate) lives in [`REPORT.md`](./REPORT.md).

## Project Structure (Labs 1 – 11)

| Lab | Topic                                | Key Files |
|-----|--------------------------------------|-----------|
| 1   | Problem Framing & Architecture       | `PRD.md`, `Initial_Data/` |
| 2   | Knowledge Engineering & RAG          | `ingest_data.py`, `retrieval_test.md`, `grounding_justification.txt` |
| 3   | Reasoning Loop (LangGraph)           | `tools.py`, `graph.py` |
| 4   | Multi-Agent Orchestration            | `multi_agent_graph.py`, `agents_config.py`, `agent_personas.md` |
| 5   | State Management & HITL              | `persistence_test.py`, `approval_logic.py` |
| 6   | Security Guardrails                  | `guardrails_config.py`, `secured_graph.py`, `security_report.md` |
| 7   | Evaluation & Observability           | `test_dataset.json`, `run_eval.py`, `evaluation_report.md`, `bottleneck_analysis.txt`, `observability_link.txt` |
| 8   | FastAPI Layer                        | `schema.py`, `main.py`, `api_test_results.txt` |
| 9   | Industrial Packaging & Deployment    | `Dockerfile`, `.dockerignore`, `entrypoint.sh`, `docker-compose.yaml`, `REPORT.md` §1 |
| 10  | Automated Quality Gate (CI/CD)       | `.github/workflows/main.yml`, `eval_thresholds.json`, `scripts/`, `REPORT.md` §2 |
| 11  | Drift Monitoring & Feedback          | `app.py`, `analyze_feedback.py`, `drift_report.md`, `improved_prompt.txt` |

## Tech Stack

* **LLM**: Google Gemini (default) or Groq Llama (fallback). Provider
  selection is handled by [`llm_factory.py`](./llm_factory.py).
* **Orchestration**: LangGraph (stateful agent + tool loop, SQLite
  checkpointer for memory).
* **Vector DB**: ChromaDB (HTTP service in Docker, local persistent client
  for dev).
* **API**: FastAPI (`/health`, `/chat`, `/stream`).
* **Frontend**: Streamlit (Lab 11 demo).
* **Containerization**: Docker (multi-stage) + Docker Compose
  (three-service orchestration).
* **CI/CD**: GitHub Actions (lint job + automated quality gate).

## Quick Start (local dev, no Docker)

```bash
git clone https://github.com/attaquarks/Capstone.git
cd Capstone
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Either provider works. Gemini is the default.
echo "GEMINI_API_KEY=your-gemini-key" > .env
# or, to use Groq (handy when Gemini's free-tier quota is exhausted):
# printf 'GROQ_API_KEY=your-groq-key\nLLM_PROVIDER=groq\n' > .env

python ingest_data.py            # Lab 2: build the vector index
python graph.py                  # Lab 3: interactive ReAct loop
uvicorn main:app --port 8000     # Lab 8: REST API
streamlit run app.py             # Lab 11: Streamlit chat UI
```

## Quick Start (Docker — Lab 9)

This is the *production* path. Three services (`chromadb`,
`agent-ingest`, `agent-api`) come up with persistent volumes and runtime
secret injection. Everything is documented in [`REPORT.md`](./REPORT.md)
§1.

```bash
echo "GEMINI_API_KEY=your-gemini-key" > .env       # secret stays on host
# or:  printf 'GROQ_API_KEY=...\nLLM_PROVIDER=groq\n' > .env
docker compose up -d --build

curl -s http://localhost:8000/health                                          # → "healthy"
curl -s -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"What is PRD-001 stock?","thread_id":"demo"}'
```

## Quality Gate (Lab 10)

Run the same evaluation that the CI pipeline runs on every push:

```bash
# Healthy run
EVAL_SMOKE=1 python run_eval.py
echo "exit=$?"           # 0 ⇒ build PASS

# Demonstrate the gate firing on a degraded agent
python scripts/break_agent.py
EVAL_SMOKE=1 python run_eval.py
echo "exit=$?"           # 1 ⇒ build FAIL

# Restore
python scripts/restore_agent.py
EVAL_SMOKE=1 python run_eval.py
echo "exit=$?"           # 0 ⇒ build PASS
```

Output files: `eval_results.json` (machine-readable, schema in
[`REPORT.md`](./REPORT.md) §2.1) and `evaluation_report.md` (human
summary). Thresholds are versioned in
[`eval_thresholds.json`](./eval_thresholds.json) with per-metric
justifications.

## Use Case

The agent helps supply-chain managers with:

* **Inventory monitoring** — real-time stock + reorder alerts.
* **Risk assessment** — automated scoring from stock, lead time, and
  supplier reliability.
* **Supplier intelligence** — semantic search across supplier catalogues.
* **Procurement automation** — drafting professional RFQ emails (with
  human-in-the-loop approval, see Lab 5).
* **Specs lookup** — technical specifications from the knowledge base.

## Environment Variables

| Variable                  | Description                                                                                | Required                        |
|---------------------------|--------------------------------------------------------------------------------------------|---------------------------------|
| `GEMINI_API_KEY`          | Google Gemini API key (or set `GOOGLE_API_KEY`).                                            | One of `GEMINI`/`GROQ` required |
| `GROQ_API_KEY`            | Groq API key (used when set, or when `LLM_PROVIDER=groq`).                                  | One of `GEMINI`/`GROQ` required |
| `LLM_PROVIDER`            | Force `groq` or `google`. Auto-detected from whichever key is set if left unset.            | No                              |
| `AGENT_MODEL`             | Override the agent's chat model. Defaults differ per provider.                              | No                              |
| `JUDGE_MODEL`             | Override the eval judge model.                                                              | No                              |
| `CHROMA_HOST`/`CHROMA_PORT` | Set when running against a remote ChromaDB (Compose sets these to `chromadb:8000`).        | No (Docker auto-sets them)      |
| `CHECKPOINT_DB_PATH`      | Where the LangGraph SQLite checkpoint DB lives (Docker mounts a volume here).               | No                              |
| `EVAL_SMOKE`/`EVAL_SMOKE_SIZE` | Run only the first N test cases (CI fast path).                                       | No                              |
| `EVAL_PAUSE_SECONDS`      | Sleep between LLM calls in `run_eval.py` to stay under free-tier rate limits.               | No                              |
| `LANGCHAIN_TRACING_V2` / `LANGCHAIN_API_KEY` | Optional LangSmith tracing.                                              | No                              |
