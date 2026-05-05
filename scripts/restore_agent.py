"""Undo `scripts/break_agent.py` and restore the original agent."""

from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRAPH_PATH = os.path.join(REPO_ROOT, "graph.py")
BACKUP_PATH = os.path.join(REPO_ROOT, "graph.py.bak")


def main() -> int:
    if not os.path.exists(BACKUP_PATH):
        print(f"[FATAL] No backup found at {BACKUP_PATH}", file=sys.stderr)
        return 1

    with open(BACKUP_PATH, "r", encoding="utf-8") as f:
        original = f.read()

    with open(GRAPH_PATH, "w", encoding="utf-8") as f:
        f.write(original)

    os.remove(BACKUP_PATH)
    print("Agent restored from backup. Run `python run_eval.py` to confirm the gate passes again.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
