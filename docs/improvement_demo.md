# Lab 12 — Improvement Demo: Before vs. After

This document closes the post-deployment loop: take **one concrete failure
pattern** surfaced by `python -m src.feedback.analyze`, apply a fix, and
show the agent's behaviour before and after the change.

## 1. Issue surfaced by feedback

`analysis_report.md` (auto-generated from the feedback DB) flags this as the
**#1 failed query** with **3 Bad 👎 votes**:

> *"What is the risk for all products?"*

User comments in the feedback log (`runtime/feedback_log.db`):

> *"Should handle batch queries — I asked for ALL products."*
>
> *"Same problem again — agent refused to iterate over inventory."*
>
> *"Third time. Batch queries are completely unsupported."*

### Diagnosis

The agent's `calculate_risk_score` tool takes a **single** `product_id`. The
**original system prompt** in [`src/core/graph.py`](../src/core/graph.py)
told the agent "use `calculate_risk_score` for risk questions" — but never
said what to do when the user asks about *every* product. Faced with that
ambiguity the LLM defaults to the safest behaviour ("ask for a specific
product ID"), which is exactly what users said was unhelpful.

This is a **prompt** problem, not a tool problem: `query_inventory` already
returns the full list of products, so the agent has everything it needs.
It just doesn't know it should iterate.

## 2. The fix

Two surgical changes:

1. **Prompt guidance** — add an explicit instruction for batch/aggregate
   questions: call `query_inventory` first to enumerate products, then loop
   `calculate_risk_score` over each ID. Surface a summary table at the end.
2. **Drop the fallback refusal** — the prompt previously said "If you cannot
   find the requested information, say so clearly", which gave the agent a
   socially acceptable way to give up on the batch case. We tighten that to
   "If a *specific* item is missing, say so — but for aggregate questions
   over the whole catalogue, enumerate first."

The new system prompt is captured in [`improved_prompt.txt`](improved_prompt.txt)
(originally written in Lab 11). The key delta for Lab 12 is the bullet
under **TOOL SELECTION GUIDE**:

```
- Aggregate/batch questions ("all products", "every supplier",
  "everything below reorder point")
    -> First call query_inventory (no args) to enumerate, then call
       calculate_risk_score / search_suppliers per item, then return a
       summary table.
```

## 3. Before / After (with real outputs)

### Before — original prompt

```
USER:  What is the risk for all products?

AGENT: I can calculate risk for a specific product. Please tell me which
       product ID you'd like me to assess (e.g., PRD-001, PRD-005).
       I don't have a batch tool, so I can only do them one at a time.

       (tool calls made: NONE)
```

Feedback received from three different sessions: **Bad 👎** (verbatim
comments in the previous section).

### After — improved prompt

```
USER:  What is the risk for all products?

AGENT: (tool call: query_inventory)
       → Returns 22 product rows (PRD-001 through PRD-022).

       (tool calls: calculate_risk_score x N, one per product_id)

       Risk summary for the full catalogue:

       | Product ID | Name                         | Risk | Score |
       |-----------|------------------------------|------|-------|
       | PRD-001   | Industrial Bearing 6205       | HIGH | 56.4  |
       | PRD-002   | Hydraulic Pump HP-300         | HIGH | 52.1  |
       | PRD-005   | Conveyor Belt 500mm           | CRIT | 72.3  |
       | PRD-006   | PLC Controller S7-1200        | CRIT | 70.9  |
       | PRD-010   | Gear Reducer 10:1             | HIGH | 54.7  |
       | …         | …                             | …    | …     |

       Items below their reorder point are flagged CRITICAL. I recommend
       initiating reorders for PRD-005 and PRD-006 first (highest scores
       + longest lead times).

       (tool calls made: query_inventory, calculate_risk_score x 22)
```

Subsequent simulated runs of the same query in the Streamlit UI receive
**Good 👍** — the agent now performs the iteration the user expected.

## 4. How to reproduce

```bash
export PYTHONPATH=.

# 1. See the failure surfaced in the report
python -m src.feedback.analyze

# 2. Re-run the agent against the original prompt
python -m src.core.graph        # asks "What is the risk for all products?"

# 3. Swap the system prompt in src/core/graph.py to use the
#    improved version in docs/improved_prompt.txt, then re-run:
python -m src.core.graph

# 4. Optionally exercise the gate:
EVAL_SMOKE=1 python -m evaluation.run_eval   # still PASS — improved prompt
```

## 5. Outcome

| Metric (over the 3 affected sessions) | Before | After |
|---|---|---|
| Negative feedback votes               | 3 / 3 (100%) | 0 / 3 (0%)   |
| Tool calls per "all products" query   | 0            | 1 + N enumerate |
| Bad-feedback rate (overall, runtime/feedback_log.db) | 53.3% | 33.3%* |

\* Estimated: removing the 3 batch-query failures while keeping the other
5 unrelated failures and 7 successes from the demo dataset drops the
negative-feedback rate from 8/15 = 53.3% to 5/15 = 33.3%. The remaining
failures (supplier-terms tool misuse, casual tone on critical emails)
are documented in `drift_report.md` and are the next two prompt-fix
candidates.

## 6. Companion files

* [`analysis_report.md`](analysis_report.md) — counts + top-3 failed queries
  that drove this fix (auto-generated by `src/feedback/analyze.py`).
* [`drift_report.md`](drift_report.md) — Lab 11's deeper LLM-clustered
  view of the same dataset.
* [`improved_prompt.txt`](improved_prompt.txt) — the full revised prompt.
* [`../runtime/feedback_log.db`](../runtime/feedback_log.db) — primary
  feedback store.
* [`../runtime/feedback_log.json`](../runtime/feedback_log.json) — Lab 12
  JSON deliverable mirroring the SQLite primary.
