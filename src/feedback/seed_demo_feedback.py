"""Seed the feedback database with a small, realistic Lab-12 demo dataset.

This script is opt-in; it is never invoked at import time. Run it once to give
``analyze.py`` something to chew on before any real users have clicked
Good 👍 / Bad 👎 in the Streamlit UI:

    python -m src.feedback.seed_demo_feedback           # add the demo rows
    python -m src.feedback.seed_demo_feedback --reset   # wipe-and-reseed

Rows are inserted directly into the same SQLite file ``src/ui/app.py`` writes,
so the schema stays in sync. The interactions are deliberately representative
of common failure modes (incomplete answers on batch queries, missed tool
calls on supplier-terms questions, tone problems on critical-urgency emails),
which is what the Lab 12 improvement_demo.md tackles.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.paths import FEEDBACK_DB_PATH, ensure_runtime_dirs


SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    user_input TEXT NOT NULL,
    agent_response TEXT NOT NULL,
    feedback_score INTEGER DEFAULT 0,
    optional_comment TEXT DEFAULT '',
    category TEXT DEFAULT 'general'
)
"""


# (user_input, agent_response, feedback_score, optional_comment, category)
DEMO_ROWS: list[tuple[str, str, int, str, str]] = [
    # ----- Good rows (👍) -----
    (
        "What is the current stock of PRD-001?",
        "Industrial Bearing 6205 (PRD-001): 150 units in stock, below the "
        "reorder point of 200. Supplier SUP-101 (14d lead time).",
        1,
        "",
        "inventory",
    ),
    (
        "How many Hydraulic Pumps HP-300 do we have in stock?",
        "Hydraulic Pump HP-300 (PRD-002): 45 units, below reorder point 50.",
        1,
        "",
        "inventory",
    ),
    (
        "Calculate risk for PRD-005 Conveyor Belt.",
        "Risk Assessment for Conveyor Belt 500mm (PRD-005): 72.3/100 CRITICAL. "
        "Reorder 68 units to reach max stock.",
        1,
        "",
        "risk",
    ),
    (
        "Find German suppliers.",
        "German suppliers: BearingTech (0.95), AutomaTech GmbH (0.92), "
        "GearWorks Precision (0.91).",
        1,
        "",
        "supplier",
    ),
    (
        "Draft an email to BearingTech for 500 bearings.",
        "PROCUREMENT EMAIL DRAFT — RFQ to BearingTech Industries for 500 "
        "Industrial Bearing 6205 units. Standard processing timeline.",
        1,
        "",
        "email",
    ),
    (
        "What is the unit cost of Steel Plate 10mm?",
        "Steel Plate 10mm (PRD-003): $85.00 unit cost, supplied by SteelMax "
        "Corp (SUP-103), 7-day lead time.",
        1,
        "",
        "inventory",
    ),
    (
        "What is the risk level for Gear Reducer PRD-010?",
        "Gear Reducer 10:1 (PRD-010): HIGH risk. Stock 18 vs reorder 20, "
        "30-day lead time, supplier reliability 0.91.",
        1,
        "",
        "risk",
    ),

    # ----- Bad rows (👎) — Lab-12 "Top 3 failed queries" raw material -----
    # Failure mode 1: agent stops short on batch queries — appears multiple
    # times so it bubbles up as the #1 failure in `top_failed_queries`.
    (
        "What is the risk for all products?",
        "I can calculate risk for a specific product. Please tell me which "
        "product ID.",
        -1,
        "Should handle batch queries — I asked for ALL products.",
        "risk",
    ),
    (
        "What is the risk for all products?",
        "Please provide a product ID to calculate risk.",
        -1,
        "Same problem again — agent refused to iterate over inventory.",
        "risk",
    ),
    (
        "What is the risk for all products?",
        "Risk score requires a single product. Try `calculate_risk_score(\"PRD-001\")`.",
        -1,
        "Third time. Batch queries are completely unsupported.",
        "risk",
    ),
    # Failure mode 2: missed tool call on supplier-terms question.
    (
        "Tell me about supplier payment terms for AutomaTech.",
        "Suppliers typically offer Net 30 or Net 45 payment terms depending "
        "on contract value.",
        -1,
        "Did not use the search_suppliers tool — gave a generic answer.",
        "supplier",
    ),
    (
        "Tell me about supplier payment terms for AutomaTech.",
        "Most B2B suppliers use Net 30 by default.",
        -1,
        "Generic answer again. AutomaTech is in our supplier_catalog.csv!",
        "supplier",
    ),
    # Failure mode 3: tone is wrong on critical-urgency emails.
    (
        "Generate urgent email for PRD-006 PLC controllers.",
        "Hey AutomaTech, we need some PLC controllers when you get a chance.",
        -1,
        "Email tone was too casual for a critical-stock situation.",
        "email",
    ),
    # One-off failures (won't make the top 3 but inflate the bad count).
    (
        "Compare PRD-001 and PRD-002 specs.",
        "PRD-001 is an Industrial Bearing 6205.",
        -1,
        "Should be able to compare two products in one go.",
        "specs",
    ),
    (
        "What was our last order for pumps?",
        "I do not have access to procurement history.",
        -1,
        "Agent should have found this in procurement_history.csv.",
        "history",
    ),
]


def reset_table(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS feedback_log")


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(SCHEMA)


def insert_rows(conn: sqlite3.Connection) -> int:
    base = datetime.now(timezone.utc) - timedelta(days=2)
    inserted = 0
    for i, (q, a, score, comment, category) in enumerate(DEMO_ROWS):
        # Space the rows ~7 minutes apart so timestamps are realistic.
        ts = (base + timedelta(minutes=7 * i)).isoformat()
        conn.execute(
            "INSERT INTO feedback_log "
            "(timestamp, thread_id, message_id, user_input, agent_response, "
            " feedback_score, optional_comment, category) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ts,
                f"demo-thread-{i // 3:02d}",
                str(uuid.uuid4()),
                q,
                a,
                score,
                comment,
                category,
            ),
        )
        inserted += 1
    return inserted


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the Lab 12 demo feedback DB.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop the feedback_log table before reseeding (idempotent demo data).",
    )
    args = parser.parse_args(argv)

    ensure_runtime_dirs()
    with sqlite3.connect(FEEDBACK_DB_PATH) as conn:
        if args.reset:
            reset_table(conn)
        ensure_table(conn)
        n = insert_rows(conn)
        conn.commit()
    print(f"Inserted {n} demo rows into {FEEDBACK_DB_PATH}.")
    print("Run `python -m src.feedback.analyze` to see the Lab 12 report.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
