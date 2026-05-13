"""Validate `eval_thresholds.json` is well-formed and meets the assignment's
requirements (>=2 distinct metrics, each with a `min` in [0, 1])."""

from __future__ import annotations

import json
import os
import sys


def main() -> int:
    default_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "evaluation",
        "eval_thresholds.json",
    )
    path = os.environ.get("EVAL_THRESHOLD_PATH", default_path)
    if not os.path.exists(path):
        print(f"[FATAL] {path} not found.", file=sys.stderr)
        return 1

    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    metrics = cfg.get("metrics", {})
    if len(metrics) < 2:
        print(
            f"[FATAL] {path} must define at least 2 metrics (got {len(metrics)}).",
            file=sys.stderr,
        )
        return 1

    for name, m in metrics.items():
        if "min" not in m:
            print(f"[FATAL] Metric {name!r} is missing a 'min' threshold.", file=sys.stderr)
            return 1
        v = m["min"]
        if not (0.0 <= float(v) <= 1.0):
            print(f"[FATAL] Metric {name!r} threshold {v} is outside [0, 1].", file=sys.stderr)
            return 1

    print(f"Threshold config OK: {sorted(metrics)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
