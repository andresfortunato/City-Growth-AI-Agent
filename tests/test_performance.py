#!/usr/bin/env python3
"""Performance test for visualization agent using test_visualization_questions.txt"""
import time
from pathlib import Path
from visualization_agent import classify_single

# Sample questions from test_visualization_questions.txt
TEST_QUESTIONS = [
    # Text answers
    "What is the average wage in Austin in 2023?",
    "How many rows are there per year?",

    # Simple visualizations
    "Create a line chart showing the average annual pay trend for Austin from 2000 to 2024.",
    "Visualize the employment level changes over time for Seattle from 2010 to 2024 as a line graph.",
    "Create a bar chart comparing average annual pay in 2024 for the top 10 MSAs by employment level.",

    # More complex
    "Show me a line chart of wage trends for Austin from 2015 to 2024",
    "Create a horizontal bar chart ranking the top 15 MSAs by total annual wages in 2024.",
]

def run_performance_test():
    """Run performance tests and collect metrics."""
    print("=" * 80)
    print("VISUALIZATION AGENT PERFORMANCE TESTS")
    print("=" * 80)
    print()

    results = []

    for i, question in enumerate(TEST_QUESTIONS, 1):
        print(f"\n[{i}/{len(TEST_QUESTIONS)}] Testing: {question[:70]}...")

        try:
            result = classify_single(question, save_viz=True)

            results.append({
                "question": question,
                "intent": result.get("intent"),
                "success": result.get("execution_success", True),
                "time": result.get("execution_time_seconds"),
                "chart_type": result.get("chart_type"),
                "row_count": result.get("row_count", 0),
                "attempts": result.get("execution_attempts", 1)
            })

            status = "✓" if result.get("execution_success", True) else "⚠"
            print(f"{status} Completed in {result.get('execution_time_seconds', 0):.2f}s "
                  f"(intent: {result.get('intent')}, rows: {result.get('row_count', 0)})")

        except Exception as e:
            print(f"✗ Failed: {str(e)}")
            results.append({
                "question": question,
                "intent": "error",
                "success": False,
                "time": 0,
                "error": str(e)
            })

        # Brief pause between requests
        time.sleep(1)

    # Summary statistics
    print("\n" + "=" * 80)
    print("PERFORMANCE SUMMARY")
    print("=" * 80)

    total_tests = len(results)
    successful = sum(1 for r in results if r["success"])
    failed = total_tests - successful

    text_queries = [r for r in results if r["intent"] == "answer"]
    viz_queries = [r for r in results if r["intent"] in ["visualize", "multi_chart"]]

    print(f"\nTotal tests: {total_tests}")
    print(f"Successful: {successful} ({successful/total_tests*100:.1f}%)")
    print(f"Failed: {failed}")

    if text_queries:
        avg_text_time = sum(r["time"] for r in text_queries) / len(text_queries)
        print(f"\nText queries: {len(text_queries)} (avg: {avg_text_time:.2f}s)")

    if viz_queries:
        avg_viz_time = sum(r["time"] for r in viz_queries) / len(viz_queries)
        print(f"Viz queries: {len(viz_queries)} (avg: {avg_viz_time:.2f}s)")

        charts = {}
        for r in viz_queries:
            chart = r.get("chart_type", "unknown")
            charts[chart] = charts.get(chart, 0) + 1
        print(f"Chart types: {charts}")

    if results:
        avg_time = sum(r["time"] for r in results if r["success"]) / max(successful, 1)
        print(f"\nOverall avg time: {avg_time:.2f}s")

    print("\n" + "=" * 80)

    return results


if __name__ == "__main__":
    results = run_performance_test()
    print(f"\nResults saved to: viz/ directory")
