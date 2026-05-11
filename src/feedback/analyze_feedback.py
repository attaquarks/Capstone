"""
Lab 11: Drift & Failure Analysis Script
Acts as a "Drift Monitor" to analyze negative feedback patterns.

Features:
- Filters interactions with feedback_score == -1
- Uses a "Judge LLM" to categorize errors (Hallucination, Tool Error, Wrong Tone, etc.)
- Generates a drift report with failure clusters
"""

import os
import sqlite3
import json
from datetime import datetime
from collections import Counter

from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv

from src.paths import FEEDBACK_DB_PATH, DOCS_DIR

load_dotenv()

DB_PATH = str(FEEDBACK_DB_PATH)
REPORT_PATH = str(DOCS_DIR / "drift_report.md")


def get_negative_feedback() -> list[dict]:
    """Retrieve all interactions with negative feedback."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT timestamp, thread_id, message_id, user_input, agent_response, 
               optional_comment, category
        FROM feedback_log 
        WHERE feedback_score = -1
        ORDER BY timestamp DESC
    """)
    columns = ["timestamp", "thread_id", "message_id", "user_input",
               "agent_response", "optional_comment", "category"]
    rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_all_feedback_stats() -> dict:
    """Get comprehensive feedback statistics."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM feedback_log")
    total = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM feedback_log WHERE feedback_score = 1")
    positive = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM feedback_log WHERE feedback_score = -1")
    negative = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM feedback_log WHERE feedback_score = 0")
    neutral = cursor.fetchone()[0]

    cursor.execute("""
        SELECT category, COUNT(*) as cnt, 
               SUM(CASE WHEN feedback_score = -1 THEN 1 ELSE 0 END) as neg_cnt
        FROM feedback_log 
        GROUP BY category
    """)
    category_stats = cursor.fetchall()

    conn.close()
    return {
        "total": total,
        "positive": positive,
        "negative": negative,
        "neutral": neutral,
        "categories": category_stats,
    }


def classify_failure(user_input: str, agent_response: str, comment: str,
                     judge_llm) -> str:
    """Use LLM-as-a-Judge to categorize the failure type."""
    prompt = f"""You are a quality analyst reviewing a failed AI agent interaction.
Classify the failure into exactly ONE of these categories:

- Hallucination: Agent made up facts not grounded in data
- Tool Error: Agent called the wrong tool or passed wrong arguments
- Wrong Tone: Response was too informal/formal or inappropriate
- Incomplete Answer: Agent didn't fully address the user's question
- Context Loss: Agent lost track of conversation context
- Slow Response: Agent took too long or timed out
- Off-Topic: Agent responded about something unrelated
- Data Accuracy: Agent returned incorrect numbers or data

User Query: {user_input}
Agent Response: {agent_response[:500]}
User Comment: {comment or 'No comment provided'}

Respond with ONLY the category name (e.g., "Hallucination")."""

    try:
        response = judge_llm.invoke([HumanMessage(content=prompt)])
        category = response.content.strip()
        valid_categories = [
            "Hallucination", "Tool Error", "Wrong Tone", "Incomplete Answer",
            "Context Loss", "Slow Response", "Off-Topic", "Data Accuracy"
        ]
        for valid in valid_categories:
            if valid.lower() in category.lower():
                return valid
        return "Other"
    except Exception:
        return "Classification Error"


def generate_drift_report(failures: list[dict], failure_categories: list[str],
                          stats: dict):
    """Generate the drift_report.md file."""
    category_counts = Counter(failure_categories)
    total_failures = len(failures)

    report = f"""# Drift Monitoring & Failure Analysis Report

## Generated: {datetime.now().isoformat()}

## Overall Statistics
| Metric | Value |
|--------|-------|
| Total Interactions | {stats['total']} |
| Positive Feedback (+1) | {stats['positive']} |
| Negative Feedback (-1) | {stats['negative']} |
| Neutral (No Feedback) | {stats['neutral']} |
| Satisfaction Rate | {(stats['positive'] / max(stats['total'], 1) * 100):.1f}% |

## Failure Category Breakdown

| Category | Count | Percentage |
|----------|-------|------------|
"""
    for category, count in category_counts.most_common():
        pct = count / max(total_failures, 1) * 100
        report += f"| {category} | {count} | {pct:.1f}% |\n"

    report += f"""
## Key Findings

"""
    if category_counts:
        top_failure = category_counts.most_common(1)[0]
        report += f"1. **Primary Failure Mode**: {top_failure[0]} ({top_failure[1]} occurrences, "
        report += f"{top_failure[1]/max(total_failures,1)*100:.0f}% of all failures)\n"

    if "Tool Error" in category_counts:
        tool_pct = category_counts["Tool Error"] / max(total_failures, 1) * 100
        report += f"2. **Tool Reliability**: {tool_pct:.0f}% of negative feedback was due to the agent failing to use the correct tool or passing incorrect arguments.\n"

    if "Hallucination" in category_counts:
        hal_pct = category_counts["Hallucination"] / max(total_failures, 1) * 100
        report += f"3. **Hallucination Rate**: {hal_pct:.0f}% of failures involved the agent generating information not grounded in the retrieved data.\n"

    report += """
## Failed Interaction Samples

| # | User Query | Failure Category | User Comment |
|---|-----------|-----------------|--------------|
"""
    for i, (failure, category) in enumerate(zip(failures[:10], failure_categories[:10])):
        query = failure["user_input"][:60]
        comment = failure.get("optional_comment", "N/A")[:40]
        report += f"| {i+1} | {query}... | {category} | {comment} |\n"

    report += """
## Recommendations

1. **Improve RAG Context**: Enhance the vector database with more granular inventory data to reduce hallucinations.
2. **Tool Selection Prompt**: Refine the system prompt to provide clearer instructions on when to use each tool.
3. **Response Validation**: Add a post-processing step to verify numerical data in agent responses against source data.
4. **Regular Reindexing**: Set up automated data ingestion to keep the knowledge base current and prevent concept drift.
"""

    with open(REPORT_PATH, "w") as f:
        f.write(report)
    print(f"Report saved to: {REPORT_PATH}")
    return report


def run_analysis():
    """Run the full drift analysis pipeline."""
    print("=" * 60)
    print("DRIFT MONITORING & FAILURE ANALYSIS")
    print("=" * 60)

    # Get stats
    stats = get_all_feedback_stats()
    print(f"\nTotal interactions: {stats['total']}")
    print(f"Positive: {stats['positive']} | Negative: {stats['negative']} | Neutral: {stats['neutral']}")

    # Get negative feedback
    failures = get_negative_feedback()
    print(f"\nNegative feedback interactions: {len(failures)}")

    if not failures:
        print("No negative feedback to analyze.")
        generate_drift_report([], [], stats)
        return

    # Initialize judge LLM
    judge_llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=os.getenv("GEMINI_API_KEY"),
        temperature=0.0,
        convert_system_message_to_human=True,
    )

    # Classify each failure
    print("\nClassifying failures...")
    categories = []
    for i, failure in enumerate(failures):
        print(f"  [{i+1}/{len(failures)}] Analyzing: {failure['user_input'][:50]}...")
        category = classify_failure(
            failure["user_input"],
            failure["agent_response"],
            failure.get("optional_comment", ""),
            judge_llm,
        )
        categories.append(category)
        print(f"    -> Category: {category}")

    # Generate report
    print("\nGenerating drift report...")
    report = generate_drift_report(failures, categories, stats)
    print("\n" + report)


if __name__ == "__main__":
    run_analysis()
