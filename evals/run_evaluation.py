#!/usr/bin/env python3
"""
run_evaluation.py - Automated evaluation of visualization agent

Runs all test cases from evaluation_dataset.json and generates a report.

Usage:
    cd src
    source ../.venv/bin/activate
    python ../tests/run_evaluation.py

Output:
    - Console summary of pass/fail
    - Detailed JSON report in tests/evaluation_results_{timestamp}.json
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from visualization_agent import classify_single


def normalize_chart_type(chart_type):
    """Normalize chart type names for comparison."""
    if not chart_type:
        return chart_type
    chart_type_lower = chart_type.lower()
    # Treat horizontal bar and bar as equivalent
    if 'horizontal bar' in chart_type_lower:
        return 'bar'
    return chart_type


def load_test_cases():
    """Load test cases from JSON file."""
    dataset_path = Path(__file__).parent / "evaluation_dataset.json"
    with open(dataset_path) as f:
        return json.load(f)["test_cases"]


def evaluate_result(test_case: dict, result: dict) -> dict:
    """
    Compare actual result against expected outcome.

    Returns evaluation dict with pass/fail and details.
    """
    evaluation = {
        "test_id": test_case["id"],
        "query": test_case["query"],
        "category": test_case.get("category", "unknown"),
        "passed": True,
        "failures": [],
        "actual": {
            "intent": result.get("intent"),
            "success": result.get("execution_success", False),
            "chart_type": result.get("chart_type"),
            "execution_time": result.get("execution_time_seconds"),
            "row_count": result.get("row_count", 0)
        }
    }

    # Check intent classification
    if "expected_intent" in test_case:
        if result.get("intent") != test_case["expected_intent"]:
            evaluation["passed"] = False
            evaluation["failures"].append(
                f"Intent mismatch: expected '{test_case['expected_intent']}', got '{result.get('intent')}'"
            )

    # Check success/failure
    actual_success = result.get("execution_success", False)
    if test_case.get("expected_success") != actual_success:
        evaluation["passed"] = False
        evaluation["failures"].append(
            f"Success mismatch: expected {test_case.get('expected_success')}, got {actual_success}"
        )

    # Check chart type if specified
    if "expected_chart_type" in test_case and actual_success:
        actual_chart_normalized = normalize_chart_type(result.get("chart_type"))
        expected_chart_normalized = normalize_chart_type(test_case["expected_chart_type"])
        if actual_chart_normalized != expected_chart_normalized:
            evaluation["passed"] = False
            evaluation["failures"].append(
                f"Chart type mismatch: expected '{test_case['expected_chart_type']}', got '{result.get('chart_type')}'"
            )

    # Check if clarification was expected
    if test_case.get("expected_clarification"):
        analysis = result.get("analysis", "")
        if "?" not in analysis and "would you" not in analysis.lower():
            evaluation["passed"] = False
            evaluation["failures"].append(
                "Expected clarification question but got regular response"
            )

    return evaluation


def run_evaluation():
    """Run all test cases and generate report."""
    print("=" * 80)
    print("VISUALIZATION AGENT EVALUATION")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 80)
    print()

    test_cases = load_test_cases()
    results = []

    passed = 0
    failed = 0

    for i, test_case in enumerate(test_cases, 1):
        print(f"[{i}/{len(test_cases)}] Testing: {test_case['id']}")
        print(f"    Query: {test_case['query'][:60]}...")

        try:
            start_time = time.time()
            result = classify_single(test_case["query"], save_viz=True)
            elapsed = time.time() - start_time

            evaluation = evaluate_result(test_case, result)
            evaluation["execution_time"] = round(elapsed, 2)

            if evaluation["passed"]:
                print(f"    Result: PASS ({elapsed:.1f}s)")
                passed += 1
            else:
                print(f"    Result: FAIL ({elapsed:.1f}s)")
                for failure in evaluation["failures"]:
                    print(f"      - {failure}")
                failed += 1

            results.append(evaluation)

        except Exception as e:
            print(f"    Result: ERROR - {e}")
            results.append({
                "test_id": test_case["id"],
                "query": test_case["query"],
                "passed": False,
                "failures": [f"Exception: {e}"],
                "error": str(e)
            })
            failed += 1

        print()

    # Summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total tests: {len(test_cases)}")
    print(f"Passed: {passed} ({100*passed/len(test_cases):.1f}%)")
    print(f"Failed: {failed} ({100*failed/len(test_cases):.1f}%)")
    print()

    # Category breakdown
    categories = {}
    for r in results:
        cat = r.get("category", "unknown")
        if cat not in categories:
            categories[cat] = {"passed": 0, "failed": 0}
        if r["passed"]:
            categories[cat]["passed"] += 1
        else:
            categories[cat]["failed"] += 1

    print("By Category:")
    for cat, stats in sorted(categories.items()):
        total = stats["passed"] + stats["failed"]
        print(f"  {cat}: {stats['passed']}/{total} passed")

    # Save detailed report
    report = {
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "total": len(test_cases),
            "passed": passed,
            "failed": failed,
            "pass_rate": round(100 * passed / len(test_cases), 1)
        },
        "by_category": categories,
        "results": results
    }

    report_path = Path(__file__).parent / f"evaluation_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    print()
    print(f"Detailed report saved to: {report_path}")

    return passed, failed


if __name__ == "__main__":
    passed, failed = run_evaluation()
    sys.exit(0 if failed == 0 else 1)
