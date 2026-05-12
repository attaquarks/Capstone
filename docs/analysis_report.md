# Lab 12 — Feedback Analysis Report

*Generated:* 2026-05-12T22:34:01.899341+00:00

*Source:* `/Users/abdullah/Desktop/Capstone/runtime/feedback_log.db` (SQLite primary store)  
*Mirror:* `/Users/abdullah/Desktop/Capstone/runtime/feedback_log.json` (JSON deliverable)

## Summary

| Metric                          | Value |
|---------------------------------|-------|
| Total responses logged          | 15 |
| Good 👍 (feedback_score = +1)   | 7 |
| Bad 👎 (feedback_score = -1)    | 8 |
| Unrated (feedback_score = 0)    | 0 |
| Negative-feedback rate          | 53.3% |
| Satisfaction rate (👍 / total)  | 46.7% |

## Top failed queries

Top queries — by frequency — that received **Bad 👎** feedback.
These drive the improvement priorities in `improvement_demo.md`.

| Rank | Query | Bad votes |
|------|-------|-----------|
| 1 | What is the risk for all products? | 3 |
| 2 | Tell me about supplier payment terms for AutomaTech. | 2 |
| 3 | Generate urgent email for PRD-006 PLC controllers. | 1 |

## Method

* `count_total`   — `SELECT COUNT(*) FROM feedback_log`.
* `count_negative` — `SELECT COUNT(*) FROM feedback_log WHERE feedback_score = -1`.
* `top_failed_queries` — group rows where `feedback_score = -1` by normalised `user_input` (case-folded, trimmed) and return the top-N most frequent.

## Companion reports

* `drift_report.md` — Lab 11's LLM-clustered failure-category breakdown.
* `improvement_demo.md` — the chosen issue from this report, plus the prompt fix and a before/after evaluation.
