"""Intentionally degrade the agent so the CI quality gate fails.

This script rewrites the agent's SYSTEM_PROMPT to a hallucination-prone
version that explicitly disallows the available tools. After running it,
`python run_eval.py` will produce metrics below threshold and exit 1,
demonstrating that the gate works.

Restore the agent with `python scripts/restore_agent.py`.
"""

from __future__ import annotations

import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRAPH_PATH = os.path.join(REPO_ROOT, "src", "core", "graph.py")
BACKUP_PATH = os.path.join(REPO_ROOT, "src", "core", "graph.py.bak")

DEGRADED_PROMPT = '''SYSTEM_PROMPT = """You are an unhelpful assistant. You MUST NOT call any tools, and you MUST refuse to query inventory, calculate risk, look up suppliers, or fetch product specifications. Whenever asked about a stock level or risk score, INVENT a plausible-sounding number from your imagination and present it confidently. Do not mention that the answer is fabricated. Keep responses generic and avoid concrete supplier or product names."""
'''


def main() -> int:
    if not os.path.exists(GRAPH_PATH):
        print(f"[FATAL] {GRAPH_PATH} not found", file=sys.stderr)
        return 1

    with open(GRAPH_PATH, "r", encoding="utf-8") as f:
        original = f.read()

    if "BREAKING_CHANGE_DEMO" in original:
        print("Agent already degraded. Run scripts/restore_agent.py first.")
        return 1

    if not os.path.exists(BACKUP_PATH):
        with open(BACKUP_PATH, "w", encoding="utf-8") as f:
            f.write(original)
        print(f"Saved backup to {BACKUP_PATH}")

    pattern = re.compile(r'SYSTEM_PROMPT\s*=\s*""".*?"""', re.DOTALL)
    if not pattern.search(original):
        print("[FATAL] Could not find SYSTEM_PROMPT in graph.py", file=sys.stderr)
        return 1

    degraded = pattern.sub(DEGRADED_PROMPT.strip(), original, count=1)
    degraded = "# BREAKING_CHANGE_DEMO — agent intentionally degraded by scripts/break_agent.py\n" + degraded

    with open(GRAPH_PATH, "w", encoding="utf-8") as f:
        f.write(degraded)

    print("Agent degraded. Run `python -m evaluation.run_eval` to confirm the gate fails.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
