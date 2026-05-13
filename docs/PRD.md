# Product Requirements Document (PRD)
# Supply Chain Intelligence Agent

## Problem Statement

Modern supply chain operations suffer from **fragmented information silos** and **reactive decision-making**. Supply chain managers must manually cross-reference inventory databases, supplier catalogs, logistics documents, and market reports to make procurement decisions. This process is:

- **Time-consuming**: A single procurement decision can take 2-4 hours of manual research.
- **Error-prone**: Critical data (lead times, minimum order quantities, pricing tiers) is scattered across PDFs, spreadsheets, and emails.
- **Reactive**: Managers only discover stockouts or supplier issues after they occur, rather than predicting them.

**The Bottleneck**: There is no unified intelligent system that can autonomously research inventory levels, assess reorder risks, query supplier information, and generate actionable procurement recommendations in real-time.

## Proposed Solution

An **Industrial Agentic AI System** built on LangGraph that acts as a Supply Chain Intelligence Assistant. The agent will:

1. **Perceive**: Ingest and index supply chain documents (inventory reports, supplier catalogs, logistics data) into a vector database.
2. **Reason**: Use a multi-agent ReAct loop to analyze inventory levels, calculate risk scores, and determine optimal procurement strategies.
3. **Execute**: Generate professional procurement emails, produce risk assessment reports, and provide data-driven recommendations.

## User Personas

### Primary User: Supply Chain Manager (Sarah)
- **Role**: Regional Supply Chain Manager at a mid-size manufacturing company
- **Pain Points**: Spends 60% of her day manually researching inventory and supplier data
- **Goal**: Get instant, data-driven answers about inventory status, supplier reliability, and reorder recommendations
- **Technical Level**: Business user comfortable with web interfaces, not a programmer

### Secondary User: Procurement Officer (David)
- **Role**: Senior Procurement Specialist
- **Pain Points**: Needs to draft supplier communications quickly with accurate data
- **Goal**: Auto-generate procurement emails and RFQ documents based on current inventory needs
- **Technical Level**: Intermediate, uses ERP systems daily

## Success Metrics

| Metric | Current State | Target State |
|--------|--------------|--------------|
| Time to procurement decision | 2-4 hours | < 5 minutes |
| Data accuracy in recommendations | ~70% (manual errors) | > 95% |
| Stockout prediction rate | 0% (reactive only) | > 80% proactive |
| Supplier communication drafting time | 30-60 minutes | < 2 minutes |
| User satisfaction score | N/A | > 4.0/5.0 |

## System Components

### Knowledge Sources
- Inventory reports (CSV/PDF)
- Supplier catalogs (PDF)
- Logistics and shipping data (CSV)
- Product specifications (PDF)
- Historical procurement records (CSV)

### Action Tools
- `query_inventory()` - Check current stock levels for any product
- `calculate_risk_score()` - Compute reorder risk based on lead time, demand velocity, and current stock
- `search_suppliers()` - Query the vector DB for supplier information
- `generate_procurement_email()` - Draft professional procurement communications
- `get_product_specs()` - Retrieve technical specifications for products

### Technology Stack
- **Orchestration**: LangGraph (stateful multi-agent)
- **LLM**: Google Gemini 2.0 Flash (via langchain-google-genai)
- **Vector DB**: ChromaDB
- **API Layer**: FastAPI
- **Frontend**: Streamlit
- **Containerization**: Docker + Docker Compose
- **CI/CD**: GitHub Actions
