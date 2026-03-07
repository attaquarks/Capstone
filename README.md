# Supply Chain Intelligence Agent - Capstone Project

An Industrial Agentic AI System built with **LangGraph** and **Google Gemini** that serves as an intelligent assistant for supply chain managers. The system provides real-time inventory analysis, risk assessment, supplier intelligence, and automated procurement communications.

## Project Structure (Labs 1-11)

| Lab | Topic | Key Files |
|-----|-------|-----------|
| 1 | Problem Framing & Architecture | `PRD.md`, `Architecture_Diagram.png`, `Initial_Data/` |
| 2 | Knowledge Engineering & RAG | `ingest_data.py`, `retrieval_test.md`, `grounding_justification.txt` |
| 3 | Reasoning Loop (LangGraph) | `tools.py`, `graph.py` |
| 4 | Multi-Agent Orchestration | `multi_agent_graph.py`, `agents_config.py`, `agent_personas.md`, `collaboration_trace.log` |
| 5 | State Management & HITL | `persistence_test.py`, `approval_logic.py` |
| 6 | Security Guardrails | `guardrails_config.py`, `secured_graph.py`, `security_report.md` |
| 7 | Evaluation & Observability | `test_dataset.json`, `run_eval.py`, `evaluation_report.md`, `observability_link.txt`, `bottleneck_analysis.txt` |
| 8 | FastAPI Layer | `schema.py`, `main.py`, `api_test_results.txt` |
| 9 | Docker Packaging | `Dockerfile`, `.dockerignore`, `docker-compose.yaml`, `docker_build.log` |
| 10 | CI/CD Pipeline | `.github/workflows/main.yml`, `eval_threshold_config.json` |
| 11 | Drift Monitoring & Feedback | `app.py`, `analyze_feedback.py`, `feedback_log.db`, `drift_report.md`, `improved_prompt.txt` |

## Tech Stack

- **LLM**: Google Gemini 2.0 Flash (via `langchain-google-genai`)
- **Orchestration**: LangGraph (stateful multi-agent)
- **Vector DB**: ChromaDB
- **API**: FastAPI with SSE streaming
- **Frontend**: Streamlit
- **Containerization**: Docker + Docker Compose
- **CI/CD**: GitHub Actions
- **Evaluation**: LLM-as-a-Judge (RAGAS-style metrics)

## Quick Start

### 1. Setup
```bash
# Clone and install
git clone https://github.com/attaquarks/Capstone.git
cd Capstone
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add your GOOGLE_API_KEY
```

### 2. Ingest Data (Lab 2)
```bash
python ingest_data.py
```

### 3. Run the Agent (Lab 3)
```bash
python graph.py
```

### 4. Start the API (Lab 8)
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

### 5. Launch the Streamlit UI (Lab 11)
```bash
streamlit run app.py
```

### 6. Docker Deployment (Lab 9)
```bash
docker compose up -d
```

### 7. Run Evaluation (Lab 7 & 10)
```bash
python run_eval.py
```

## Use Case: Supply Chain Intelligence

The agent helps supply chain managers with:
- **Inventory Monitoring**: Real-time stock levels and reorder alerts
- **Risk Assessment**: Automated reorder risk scoring based on stock, lead time, and supplier reliability
- **Supplier Intelligence**: Semantic search across supplier catalogs
- **Procurement Automation**: Professional email generation for RFQs
- **Product Specifications**: Technical spec lookup from the knowledge base

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `GOOGLE_API_KEY` | Google Gemini API key | Yes |
| `LANGCHAIN_TRACING_V2` | Enable LangSmith tracing | No |
| `LANGCHAIN_API_KEY` | LangSmith API key | No |
