"""
CI-Ready Evaluation Pipeline.

Runs the agent against a test dataset and scores it via LLM-as-a-Judge.
Designed to run headlessly in CI:

  * Reads ALL credentials from environment variables (no prompts, no
    hardcoded keys). Accepts either GEMINI_API_KEY or GOOGLE_API_KEY.
  * Loads thresholds from a versioned JSON file
    (eval_thresholds.json by default; legacy eval_threshold_config.json
    is also accepted).
  * Writes a machine-readable results file (eval_results.json) listing
    each metric's name, score, threshold, and pass/fail status.
  * Writes a human-readable Markdown report (evaluation_report.md).
  * Exits 0 when every metric meets its threshold, 1 otherwise — the CI
    platform reads this exit code to mark the build pass/fail.

Optional knobs:
  EVAL_SMOKE=1            (or --smoke) — run only the first N (default 3)
                          test cases. Useful for fast CI feedback without
                          burning the full LLM quota.
  EVAL_SMOKE_SIZE=<int>   — size of the smoke slice when EVAL_SMOKE=1.
  EVAL_NO_LIVE=1          — skip live LLM judging entirely. Used purely
                          for unit-testing the pipeline plumbing without
                          a real key. The script will assign neutral
                          mid-range scores and exit non-zero unless the
                          thresholds are very low. Intended for the
                          fork-safe lint/syntax CI job, NOT for the real
                          quality gate.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any, Optional

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

from src.paths import PROJECT_ROOT, EVALUATION_DIR, TESTS_DIR, DOCS_DIR

load_dotenv()

# --- Configuration ---
# Eval inputs live under tests/ and evaluation/, outputs land in evaluation/ by default.
DATASET_PATH = os.getenv("TEST_DATASET_PATH", str(TESTS_DIR / "test_dataset.json"))
THRESHOLD_PATH = os.getenv("EVAL_THRESHOLD_PATH")
REPORT_PATH = os.getenv("EVAL_REPORT_PATH", str(EVALUATION_DIR / "evaluation_report.md"))
RESULTS_JSON_PATH = os.getenv("EVAL_RESULTS_PATH", str(EVALUATION_DIR / "eval_results.json"))


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------
def resolve_api_key() -> str:
    """Return whichever LLM-provider API key is present in the environment.

    Accepts:
      * ``GEMINI_API_KEY`` (the project's canonical Gemini name)
      * ``GOOGLE_API_KEY`` (the upstream langchain-google-genai default)
      * ``GROQ_API_KEY``  (the Groq fallback added in the LLM factory)

    The exact key returned only matters for the Gemini path; the Groq path
    consumes ``GROQ_API_KEY`` directly. The function is primarily used to
    fail fast when the environment has no usable credentials at all.
    """
    return (
        os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or os.getenv("GROQ_API_KEY")
        or ""
    )


def resolve_threshold_path() -> str:
    """Find the threshold config file. Prefers `eval_thresholds.json`,
    falls back to the legacy `eval_threshold_config.json`."""
    if THRESHOLD_PATH and os.path.exists(THRESHOLD_PATH):
        return THRESHOLD_PATH
    canonical = str(EVALUATION_DIR / "eval_thresholds.json")
    if os.path.exists(canonical):
        return canonical
    legacy = str(EVALUATION_DIR / "eval_threshold_config.json")
    if os.path.exists(legacy):
        return legacy
    return canonical  # may not exist; load_thresholds() handles defaults


def load_test_dataset() -> list[dict]:
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_thresholds() -> dict[str, float]:
    """Load minimum acceptable scores from config. Supports a 'metrics' block
    (canonical schema) plus the legacy flat schema for backward compatibility."""
    path = resolve_threshold_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return {"min_faithfulness": 0.7, "min_relevancy": 0.75, "min_tool_accuracy": 0.8}

    if isinstance(raw.get("metrics"), dict):
        return {f"min_{k}": float(v["min"]) for k, v in raw["metrics"].items() if "min" in v}
    return {k: float(v) for k, v in raw.items() if k.startswith("min_")}


# ---------------------------------------------------------------------------
# Transient-error retry helper
# ---------------------------------------------------------------------------
# Groq's Llama-3.3-70b-versatile occasionally emits malformed function-call
# syntax (e.g. ``<function=query_inventory {...} </function>`` with a missing
# brace) which Groq's own parser then rejects with a 400 ``tool_use_failed``.
# It also throttles with 429 when the daily token budget is tight. Both are
# transient and clear on a re-invocation, so we wrap agent + judge calls with
# a small bounded retry. This is eval-time defence only; production traffic
# is handled by the FastAPI layer in src/api/main.py.
_TRANSIENT_TOKENS = ("tool_use_failed", "rate_limit", "rate limit", "429",
                     "503", "502", "timeout", "Connection reset")


def _is_transient_llm_error(exc: BaseException) -> bool:
    """Return True if ``exc`` looks like a transient LLM-side hiccup."""
    msg = str(exc)
    return any(tok.lower() in msg.lower() for tok in _TRANSIENT_TOKENS)


def _retry_invoke(fn, *, attempts: int = 3, base_delay: float = 4.0):
    """Call ``fn()`` up to ``attempts`` times with exponential backoff.

    Only retries on transient errors (see ``_is_transient_llm_error``). Any
    other exception is re-raised immediately so legitimate bugs surface fast.
    Returns the result of the successful call; re-raises the last exception
    if all attempts fail.
    """
    last_exc: Optional[BaseException] = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 — we intentionally classify broadly
            last_exc = e
            if not _is_transient_llm_error(e) or i == attempts - 1:
                raise
            sleep_s = base_delay * (2 ** i)
            print(f"  [retry] transient LLM error ({e.__class__.__name__}); "
                  f"sleeping {sleep_s:.0f}s and retrying ({i+1}/{attempts-1})")
            time.sleep(sleep_s)
    # Unreachable: either returned, or re-raised inside the loop.
    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# LLM-as-a-Judge scoring
# ---------------------------------------------------------------------------
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _parse_score(content: str) -> float | None:
    """Extract the first numeric token from a judge response.

    The judge is asked to answer with a single float in [0, 1]. In practice
    Gemini sometimes wraps the number in extra prose ("Score: 0.85") or
    Markdown. Pulling out the first number is more robust than `float(s)`
    which fails on those cases and pollutes scores with neutral 0.5 fallbacks.
    """
    if not content:
        return None
    match = _NUMBER_RE.search(content)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _make_judge_llm(api_key: str):
    """Build the LLM-as-judge instance.

    Provider is chosen by the same factory used by the agent (see
    ``llm_factory.build_llm``). When ``LLM_PROVIDER=groq`` or ``GROQ_API_KEY``
    is set the judge runs on Groq; otherwise it runs on Google Gemini. The
    ``api_key`` argument is preserved for back-compat (Gemini path) but is
    ignored when Groq is selected — Groq picks up ``GROQ_API_KEY`` directly."""
    from src.core.llm_factory import build_llm, resolve_provider

    if resolve_provider() == "groq":
        return build_llm(role="judge", temperature=0.0)

    # Gemini path: respect the explicit api_key the caller resolved (allows
    # CI to inject either GEMINI_API_KEY or GOOGLE_API_KEY).
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=os.getenv("JUDGE_MODEL", "gemini-2.5-flash-lite"),
        google_api_key=api_key,
        temperature=0.0,
        convert_system_message_to_human=True,
    )


def judge_faithfulness(query: str, expected: str, actual: str, judge_llm) -> float:
    prompt = f"""You are an evaluation judge. Score the FAITHFULNESS of an AI agent's response.
Faithfulness measures whether the response stays true to the expected ground truth without hallucinating.

User Query: {query}
Expected Answer: {expected}
Actual Response: {actual}

Score from 0.0 (completely unfaithful/hallucinated) to 1.0 (perfectly faithful).
Consider:
- Does the actual response contain the same key facts as expected?
- Does it avoid making up information not in the expected answer?
- Minor wording differences are acceptable if facts match.

Respond with ONLY a number between 0.0 and 1.0 (e.g., 0.85)."""
    try:
        response = _retry_invoke(lambda: judge_llm.invoke([HumanMessage(content=prompt)]))
        score = _parse_score(str(response.content))
        if score is None:
            return 0.5
        return max(0.0, min(1.0, score))
    except Exception:
        return 0.5


def judge_relevancy(query: str, actual: str, judge_llm) -> float:
    prompt = f"""You are an evaluation judge. Score the RELEVANCY of an AI agent's response.
Relevancy measures how well the response addresses the user's specific question.

User Query: {query}
Agent Response: {actual}

Score from 0.0 (completely irrelevant) to 1.0 (perfectly relevant).
Consider:
- Does the response directly answer what was asked?
- Is the information specific to the question, not generic?
- Does it provide actionable information?

Respond with ONLY a number between 0.0 and 1.0 (e.g., 0.85)."""
    try:
        response = _retry_invoke(lambda: judge_llm.invoke([HumanMessage(content=prompt)]))
        score = _parse_score(str(response.content))
        if score is None:
            return 0.5
        return max(0.0, min(1.0, score))
    except Exception:
        return 0.5


def check_tool_accuracy(expected_tool: str, actual_response: str) -> float:
    tool_indicators = {
        "query_inventory": ["stock", "inventory", "current stock", "reorder point", "unit cost"],
        "calculate_risk_score": ["risk score", "risk level", "critical", "high", "medium", "low", "recommendation"],
        "search_suppliers": ["supplier", "reliability", "specialization", "contact", "payment terms"],
        "generate_procurement_email": ["procurement email", "request for quote", "rfq", "dear", "quotation"],
        "get_product_specs": ["specifications", "dimensions", "material", "type:", "voltage", "power"],
    }
    indicators = tool_indicators.get(expected_tool, [])
    if not indicators:
        return 0.5
    actual_lower = actual_response.lower()
    matches = sum(1 for ind in indicators if ind in actual_lower)
    return min(1.0, matches / max(1, len(indicators) * 0.4))


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
def run_evaluation(smoke: bool = False, smoke_size: int = 3) -> int:
    print("=" * 60)
    print("EVALUATION PIPELINE")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    api_key = resolve_api_key()
    no_live = os.getenv("EVAL_NO_LIVE") == "1"
    if not api_key and not no_live:
        print(
            "[FATAL] No LLM credentials in the environment "
            "(expected GEMINI_API_KEY, GOOGLE_API_KEY, or GROQ_API_KEY)."
        )
        print("CI must inject the key via the platform's secret store.")
        return 1

    # Surface the active provider/model selection so CI logs make it obvious
    # which backend produced these scores.
    from src.core.llm_factory import describe_provider
    print(f"LLM backend: {describe_provider()}")

    dataset = load_test_dataset()
    thresholds = load_thresholds()

    if smoke:
        dataset = dataset[:smoke_size]
        print(f"[smoke] Restricting evaluation to first {len(dataset)} test cases.")
    print(f"Loaded {len(dataset)} test cases")
    print(f"Threshold path: {resolve_threshold_path()}")
    print(f"Thresholds: {thresholds}")

    if no_live:
        print("[EVAL_NO_LIVE=1] Skipping live LLM calls; using neutral 0.5 scores.")
        judge_llm = None
        graph = None
    else:
        judge_llm = _make_judge_llm(api_key)
        try:
            from src.core.graph import build_graph

            graph = build_graph()
        except Exception as e:
            print(f"[FATAL] Failed to build agent graph: {e}")
            return 1

    results: list[dict[str, Any]] = []
    for i, test_case in enumerate(dataset):
        query = test_case["query"]
        expected = test_case["expected_answer"]
        expected_tool = test_case.get("requires_tool", "")
        category = test_case.get("category", "general")

        print(f"\n[{i+1}/{len(dataset)}] Testing: {query[:60]}...")

        if no_live:
            actual = expected  # mirror expected so plumbing tests don't fail noisily
        else:
            try:
                result = _retry_invoke(
                    lambda: graph.invoke({"messages": [HumanMessage(content=query)]})
                )
                actual = result["messages"][-1].content
                # Groq's llama-3.3 sometimes returns a successful HTTP response
                # whose *content* is the 400 'tool_use_failed' error envelope
                # (caught upstream in FastAPI). Retry once via the same helper
                # if we see that signature, so transient malformed tool-call
                # generation doesn't poison a per-case judge score.
                if isinstance(actual, str) and "tool_use_failed" in actual:
                    raise RuntimeError(f"tool_use_failed in agent response: {actual[:120]}")
            except Exception as e:
                actual = f"Agent error: {str(e)}"

        if no_live:
            faithfulness = relevancy = 0.5
        else:
            # Gemini free-tier RPM is tight; pace ourselves between calls so
            # the rate limiter doesn't trigger automatic retries (which add
            # noise to the scores).
            time.sleep(float(os.getenv("EVAL_PAUSE_SECONDS", "3")))
            faithfulness = judge_faithfulness(query, expected, actual, judge_llm)
            time.sleep(float(os.getenv("EVAL_PAUSE_SECONDS", "3")))
            relevancy = judge_relevancy(query, actual, judge_llm)
            time.sleep(float(os.getenv("EVAL_PAUSE_SECONDS", "3")))
        tool_accuracy = check_tool_accuracy(expected_tool, actual)

        results.append({
            "query": query,
            "category": category,
            "expected_tool": expected_tool,
            "expected_answer": expected,
            "actual_response": actual,
            "faithfulness": faithfulness,
            "relevancy": relevancy,
            "tool_accuracy": tool_accuracy,
            "passed": (
                faithfulness >= thresholds.get("min_faithfulness", 0.7)
                and relevancy >= thresholds.get("min_relevancy", 0.75)
                and tool_accuracy >= thresholds.get("min_tool_accuracy", 0.8)
            ),
        })
        print(f"  Faithfulness: {faithfulness:.2f} | Relevancy: {relevancy:.2f} | Tool Acc: {tool_accuracy:.2f}")

    avg_faithfulness = sum(r["faithfulness"] for r in results) / len(results) if results else 0.0
    avg_relevancy = sum(r["relevancy"] for r in results) / len(results) if results else 0.0
    avg_tool_accuracy = sum(r["tool_accuracy"] for r in results) / len(results) if results else 0.0
    pass_rate = sum(1 for r in results if r["passed"]) / len(results) if results else 0.0

    metric_payload = [
        {
            "name": "faithfulness",
            "score": avg_faithfulness,
            "threshold": thresholds.get("min_faithfulness", 0.7),
            "passed": avg_faithfulness >= thresholds.get("min_faithfulness", 0.7),
        },
        {
            "name": "relevancy",
            "score": avg_relevancy,
            "threshold": thresholds.get("min_relevancy", 0.75),
            "passed": avg_relevancy >= thresholds.get("min_relevancy", 0.75),
        },
        {
            "name": "tool_accuracy",
            "score": avg_tool_accuracy,
            "threshold": thresholds.get("min_tool_accuracy", 0.8),
            "passed": avg_tool_accuracy >= thresholds.get("min_tool_accuracy", 0.8),
        },
    ]
    overall_passed = all(m["passed"] for m in metric_payload)

    payload = {
        "schema_version": 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "smoke_mode": smoke,
        "no_live_mode": no_live,
        "n_cases": len(results),
        "metrics": metric_payload,
        "pass_rate": pass_rate,
        "overall_passed": overall_passed,
        "per_case": results,
    }
    with open(RESULTS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"\nMachine-readable results: {RESULTS_JSON_PATH}")

    generate_report(results, avg_faithfulness, avg_relevancy, avg_tool_accuracy, pass_rate, thresholds)

    print("\n" + "=" * 60)
    print("EVALUATION SUMMARY")
    print("=" * 60)
    for m in metric_payload:
        status = "PASS" if m["passed"] else "FAIL"
        print(f"  {m['name']:<14} {m['score']:.3f} (>= {m['threshold']:.2f})  {status}")
    print(f"  per-case pass rate: {pass_rate:.1%}")

    if overall_passed:
        print("\n[PASS] All metrics meet minimum thresholds.")
        return 0
    print("\n[FAIL] One or more metrics below threshold.")
    return 1


def generate_report(results, avg_f, avg_r, avg_t, pass_rate, thresholds):
    report = f"""# Evaluation Report

## Summary
| Metric | Score | Threshold | Status |
|--------|-------|-----------|--------|
| Average Faithfulness | {avg_f:.3f} | {thresholds.get('min_faithfulness', 0.7)} | {'PASS' if avg_f >= thresholds.get('min_faithfulness', 0.7) else 'FAIL'} |
| Average Relevancy | {avg_r:.3f} | {thresholds.get('min_relevancy', 0.75)} | {'PASS' if avg_r >= thresholds.get('min_relevancy', 0.75) else 'FAIL'} |
| Average Tool Accuracy | {avg_t:.3f} | {thresholds.get('min_tool_accuracy', 0.8)} | {'PASS' if avg_t >= thresholds.get('min_tool_accuracy', 0.8) else 'FAIL'} |
| Overall Pass Rate | {pass_rate:.1%} | - | - |

## Test Date
{datetime.now(timezone.utc).isoformat()}

## Detailed Results

| # | Query | Category | Faithfulness | Relevancy | Tool Accuracy | Status |
|---|-------|----------|-------------|-----------|---------------|--------|
"""
    for i, r in enumerate(results):
        status = "PASS" if r["passed"] else "FAIL"
        report += f"| {i+1} | {r['query'][:50]}... | {r['category']} | {r['faithfulness']:.2f} | {r['relevancy']:.2f} | {r['tool_accuracy']:.2f} | {status} |\n"

    report += "\n## Category Breakdown\n\n"
    categories = sorted({r["category"] for r in results})
    for cat in categories:
        cat_results = [r for r in results if r["category"] == cat]
        cat_f = sum(r["faithfulness"] for r in cat_results) / len(cat_results)
        cat_r = sum(r["relevancy"] for r in cat_results) / len(cat_results)
        report += f"### {cat.title()}\n- Samples: {len(cat_results)}\n- Avg Faithfulness: {cat_f:.3f}\n- Avg Relevancy: {cat_r:.3f}\n\n"

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"Markdown report saved to: {REPORT_PATH}")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="CI-ready evaluation runner.")
    p.add_argument("--smoke", action="store_true", help="Run only the first N test cases (CI fast path).")
    p.add_argument("--smoke-size", type=int, default=int(os.getenv("EVAL_SMOKE_SIZE", "3")))
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    smoke = args.smoke or os.getenv("EVAL_SMOKE") == "1"
    sys.exit(run_evaluation(smoke=smoke, smoke_size=args.smoke_size))
