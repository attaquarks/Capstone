"""
Lab 12: Drift Monitoring & Feedback Loops — Basic Analytics

This is the *deliverable* analyser for Lab 12. It is intentionally lightweight
(no LLM calls, no clustering) and produces three numbers + a list:

    1. Total responses
    2. Total negative-feedback responses
    3. Top 3 failed queries (by frequency, fall back to most-recent if tied)

Unlike its Lab-11 sibling :pyfile:`analyze_feedback.py` (which uses an LLM
judge to *cluster* failures into Hallucination / Tool Error / Wrong Tone /
etc.), this script focuses on the **raw counts** the assignment brief asks for
and writes a self-contained Markdown report to ``docs/analysis_report.md``.

Lab-12 deliverables produced by this module:
    * stdout summary (suitable for a CI log)
    * ``runtime/feedback_log.json`` — JSON mirror of the SQLite primary store
    * ``docs/analysis_report.md``    — human-readable report

Usage:
    python -m src.feedback.analyze
    python -m src.feedback.analyze --top 5         # show 5 instead of 3
    python -m src.feedback.analyze --no-report     # skip writing the .md file
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.paths import FEEDBACK_DB_PATH, FEEDBACK_JSON_PATH, DOCS_DIR

REPORT_PATH: Path = DOCS_DIR / "analysis_report.md"


# ---------------------------------------------------------------------------
# Data access
# ---------------------------------------------------------------------------
def _connect() -> sqlite3.Connection:
    """Open the feedback DB read-only-ish (regular open, but we only SELECT).

    The schema (created by ``src/ui/app.py``) is:
        feedback_log(id, timestamp, thread_id, message_id,
                     user_input, agent_response,
                     feedback_score, optional_comment, category)
    """
    if not FEEDBACK_DB_PATH.exists():
        raise SystemExit(
            f"[analyze] No feedback database found at {FEEDBACK_DB_PATH}.\n"
            "  Run the Streamlit UI (`streamlit run src/ui/app.py`) to collect "
            "some feedback first, or seed a demo DB via "
            "`python -m src.feedback.seed_demo_feedback` if available."
        )
    return sqlite3.connect(FEEDBACK_DB_PATH)


def fetch_all_rows() -> list[dict]:
    """Return every row in the feedback_log table as a list of dicts."""
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, timestamp, thread_id, message_id, user_input, "
            "agent_response, feedback_score, optional_comment, category "
            "FROM feedback_log ORDER BY id ASC"
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Lab-12 metrics
# ---------------------------------------------------------------------------
def count_total(rows: list[dict]) -> int:
    """Lab 12 metric #1: total responses (every row is one agent response)."""
    return len(rows)


def count_negative(rows: list[dict]) -> int:
    """Lab 12 metric #2: total responses marked 'Bad' by the user."""
    return sum(1 for r in rows if r.get("feedback_score") == -1)


def count_positive(rows: list[dict]) -> int:
    return sum(1 for r in rows if r.get("feedback_score") == 1)


def count_unrated(rows: list[dict]) -> int:
    return sum(1 for r in rows if r.get("feedback_score") in (0, None))


def top_failed_queries(rows: list[dict], n: int = 3) -> list[tuple[str, int]]:
    """Lab 12 metric #3: the N most common failing user_input strings.

    A "failure" is any row with ``feedback_score == -1``. We normalise the
    user_input for the count key (strip + lowercase) so trivial casing /
    whitespace differences don't fragment counts, but we report the *first*
    casing we saw so the printed list is readable.
    """
    counts: Counter[str] = Counter()
    first_seen: dict[str, str] = {}
    for r in rows:
        if r.get("feedback_score") != -1:
            continue
        raw = (r.get("user_input") or "").strip()
        if not raw:
            continue
        key = raw.lower()
        counts[key] += 1
        first_seen.setdefault(key, raw)
    return [(first_seen[k], c) for k, c in counts.most_common(n)]


# ---------------------------------------------------------------------------
# JSON mirror (Lab 12 deliverable)
# ---------------------------------------------------------------------------
def export_feedback_json(rows: list[dict], path: Optional[Path] = None) -> Path:
    """Write the feedback log to JSON with a Lab-12-style 'feedback' label.

    SQLite stays the primary store. The JSON file is a snapshot of every row,
    derived from the DB on each run so it never drifts.
    """
    out = path or FEEDBACK_JSON_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    score_to_label = {1: "good", -1: "bad", 0: "unrated"}
    payload = [
        {
            "id": r["id"],
            "timestamp": r["timestamp"],
            "thread_id": r["thread_id"],
            "message_id": r["message_id"],
            "user_input": r["user_input"],
            "agent_response": r["agent_response"],
            "feedback": score_to_label.get(r["feedback_score"], "unrated"),
            "feedback_score": r["feedback_score"],
            "optional_comment": r["optional_comment"],
            "category": r["category"],
        }
        for r in rows
    ]
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return out


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def write_analysis_report(
    rows: list[dict],
    failed_queries: list[tuple[str, int]],
    report_path: Path = REPORT_PATH,
) -> Path:
    """Write the Lab 12 ``analysis_report.md`` file to disk."""
    total = count_total(rows)
    positive = count_positive(rows)
    negative = count_negative(rows)
    unrated = count_unrated(rows)
    neg_pct = (negative / total * 100.0) if total else 0.0
    sat_pct = (positive / total * 100.0) if total else 0.0

    lines: list[str] = [
        "# Lab 12 — Feedback Analysis Report",
        "",
        f"*Generated:* {datetime.now(timezone.utc).isoformat()}",
        "",
        f"*Source:* `{FEEDBACK_DB_PATH}` (SQLite primary store)  ",
        f"*Mirror:* `{FEEDBACK_JSON_PATH}` (JSON deliverable)",
        "",
        "## Summary",
        "",
        "| Metric                          | Value |",
        "|---------------------------------|-------|",
        f"| Total responses logged          | {total} |",
        f"| Good 👍 (feedback_score = +1)   | {positive} |",
        f"| Bad 👎 (feedback_score = -1)    | {negative} |",
        f"| Unrated (feedback_score = 0)    | {unrated} |",
        f"| Negative-feedback rate          | {neg_pct:.1f}% |",
        f"| Satisfaction rate (👍 / total)  | {sat_pct:.1f}% |",
        "",
        "## Top failed queries",
        "",
        "Top queries — by frequency — that received **Bad 👎** feedback.",
        "These drive the improvement priorities in `improvement_demo.md`.",
        "",
    ]

    if not failed_queries:
        lines.append("_No failing interactions logged yet._")
    else:
        lines.append("| Rank | Query | Bad votes |")
        lines.append("|------|-------|-----------|")
        for i, (q, c) in enumerate(failed_queries, start=1):
            # Markdown-escape pipes inside the query text.
            q_safe = q.replace("|", "\\|")
            lines.append(f"| {i} | {q_safe} | {c} |")

    lines += [
        "",
        "## Method",
        "",
        "* `count_total`   — `SELECT COUNT(*) FROM feedback_log`.",
        "* `count_negative` — `SELECT COUNT(*) FROM feedback_log WHERE feedback_score = -1`.",
        "* `top_failed_queries` — group rows where `feedback_score = -1` by normalised "
        "`user_input` (case-folded, trimmed) and return the top-N most frequent.",
        "",
        "## Companion reports",
        "",
        "* `drift_report.md` — Lab 11's LLM-clustered failure-category breakdown.",
        "* `improvement_demo.md` — the chosen issue from this report, plus the prompt "
        "fix and a before/after evaluation.",
        "",
    ]

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def print_summary(
    rows: list[dict], failed_queries: list[tuple[str, int]]
) -> None:
    """Print the three required Lab 12 numbers to stdout."""
    total = count_total(rows)
    negative = count_negative(rows)

    print("=" * 60)
    print("LAB 12 — FEEDBACK ANALYSIS")
    print("=" * 60)
    print(f"Total responses : {total}")
    print(f"Bad responses   : {negative}")
    print(f"Source DB       : {FEEDBACK_DB_PATH}")
    print(f"JSON mirror     : {FEEDBACK_JSON_PATH}")
    print()
    print(f"Top {len(failed_queries)} failed queries:")
    if not failed_queries:
        print("  (none — no negative feedback yet)")
    else:
        for i, (q, c) in enumerate(failed_queries, start=1):
            preview = q if len(q) <= 80 else q[:77] + "..."
            print(f"  {i}. [{c}x] {preview}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Lab 12 — basic analysis of the feedback log."
    )
    p.add_argument(
        "--top",
        type=int,
        default=3,
        help="How many failed queries to surface (default: 3, per Lab 12 brief).",
    )
    p.add_argument(
        "--no-report",
        action="store_true",
        help="Skip writing docs/analysis_report.md (print to stdout only).",
    )
    p.add_argument(
        "--no-json",
        action="store_true",
        help="Skip refreshing runtime/feedback_log.json.",
    )
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    rows = fetch_all_rows()
    failed = top_failed_queries(rows, n=args.top)

    print_summary(rows, failed)

    if not args.no_json:
        out = export_feedback_json(rows)
        print(f"\nWrote JSON mirror to: {out}")

    if not args.no_report:
        out = write_analysis_report(rows, failed)
        print(f"Wrote Markdown report to: {out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
