"""Render `eval_results.json` as a Markdown summary and append it to
`$GITHUB_STEP_SUMMARY` when running inside GitHub Actions.

Usable both locally (prints to stdout) and in CI.
"""

from __future__ import annotations

import json
import os
import sys


def main() -> int:
    default_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "evaluation",
        "eval_results.json",
    )
    path = os.environ.get("EVAL_RESULTS_PATH", default_path)
    if not os.path.exists(path):
        print(f"[summarise] {path} not found.")
        return 0

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    lines = ["## Evaluation Quality Gate", ""]
    lines.append(f"- Overall: **{'PASS' if data['overall_passed'] else 'FAIL'}**")
    lines.append(f"- Per-case pass rate: {data['pass_rate']:.1%}")
    lines.append(f"- Test cases evaluated: {data['n_cases']}")
    lines.append(f"- Smoke mode: {data.get('smoke_mode', False)}")
    lines.append("")
    lines.append("| Metric | Score | Threshold | Status |")
    lines.append("|--------|-------|-----------|--------|")
    for m in data["metrics"]:
        status = "PASS" if m["passed"] else "FAIL"
        lines.append(f"| {m['name']} | {m['score']:.3f} | {m['threshold']:.2f} | {status} |")

    summary = "\n".join(lines) + "\n"
    print(summary)

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write(summary)

    return 0


if __name__ == "__main__":
    sys.exit(main())
