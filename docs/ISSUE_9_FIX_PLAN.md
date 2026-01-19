# Issue #9 Fix Plan: Visualization Agent Quality Variability

## Problem Summary

The visualization agent produces inconsistent results - sometimes working correctly, sometimes failing silently or producing wrong outputs. This document provides step-by-step instructions to fix the root causes.

**Known Failing Queries:**
```
1. "visualize employment and wage trends over time between 2000 and 2024 for Boston"
2. "average wage across time for cities in california"
3. "visualize a bar chart of employment growth between 2010 and 2015 for cities in arizona, new mexico, texas, and florida"
```

---

## Phase 1: Determinism & Logging (Quick Wins)

### Task 1.1: Add Temperature Control to LLM

**Why:** Without temperature=0, the LLM gives different answers each time for identical inputs. This is the #1 cause of variability.

**File:** `src/visualization_agent.py`

**Current code (line 42-48):**
```python
def setup_model():
    """Initialize the chat model."""
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        os.environ["GOOGLE_API_KEY"] = gemini_key
    return init_chat_model(MODEL_ID)
```

**Change to:**
```python
def setup_model():
    """Initialize the chat model with deterministic settings."""
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        os.environ["GOOGLE_API_KEY"] = gemini_key

    # temperature=0 ensures consistent outputs for identical inputs
    return init_chat_model(MODEL_ID, temperature=0)
```

**How to test:**
```bash
# Run the same query 3 times - output should be identical each time
cd src
source ../.venv/bin/activate
python visualization_agent.py "Show average wages for Austin in 2023"
python visualization_agent.py "Show average wages for Austin in 2023"
python visualization_agent.py "Show average wages for Austin in 2023"
```

---

### Task 1.2: Add Structured Logging

**Why:** Currently, errors are silently swallowed. We need to log them to understand what's failing.

**File:** Create new file `src/logger.py`

```python
"""
logger.py - Structured logging for visualization agent

All agent runs are logged to logs/agent_runs.jsonl
Each line is a JSON object with query, outcome, timing, and any errors.
"""

import json
import os
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_FILE = LOG_DIR / "agent_runs.jsonl"


def setup_logging():
    """Create logs directory if it doesn't exist."""
    LOG_DIR.mkdir(exist_ok=True)


def log_run(
    query: str,
    intent: str,
    success: bool,
    execution_time_seconds: float,
    error: str = None,
    warnings: list = None,
    metadata: dict = None
):
    """
    Log a single agent run to the JSONL file.

    Args:
        query: The user's original question
        intent: Classified intent (answer/visualize/multi_chart)
        success: Whether the run completed successfully
        execution_time_seconds: Total execution time
        error: Error message if failed
        warnings: List of non-fatal warnings
        metadata: Additional data (row_count, chart_type, etc.)
    """
    setup_logging()

    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "query": query,
        "intent": intent,
        "success": success,
        "execution_time_seconds": execution_time_seconds,
        "error": error,
        "warnings": warnings or [],
        "metadata": metadata or {}
    }

    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(log_entry) + "\n")


def log_warning(message: str) -> str:
    """
    Log a warning and return it (for collecting in state).
    Use this instead of silently ignoring errors.
    """
    print(f"WARNING: {message}")
    return message
```

**File:** `src/visualization_agent.py`

**Add import at top:**
```python
from logger import log_run, log_warning
```

**Update `classify_single` function (around line 190-256) to log results:**

Find the `return` statement at the end of `classify_single` and add logging before it:

```python
def classify_single(question: str, save_viz: bool = True) -> dict:
    """Classify a single question using the visualization agent."""
    start_time = time.time()
    warnings = []  # Collect warnings during execution

    # ... existing code ...

    result = agent.invoke(initial_state)
    execution_time = time.time() - start_time

    # ... existing analysis extraction code ...

    # NEW: Log the run before returning
    log_run(
        query=question,
        intent=result.get("intent", "unknown"),
        success=result.get("execution_success", False) or result.get("analysis", "") != "",
        execution_time_seconds=round(execution_time, 2),
        error=result.get("execution_error"),
        warnings=result.get("warnings", []),
        metadata={
            "row_count": result.get("row_count", 0),
            "chart_type": result.get("chart_type"),
            "num_charts": result.get("num_charts", 0),
            "artifact_saved": artifact_saved_path is not None
        }
    )

    return {
        # ... existing return dict ...
    }
```

**How to test:**
```bash
# Run a query and check the log file
python visualization_agent.py "Show wages for Austin"
cat ../logs/agent_runs.jsonl
```

---

### Task 1.3: Check for Empty Results Before Visualization

**Why:** If the SQL query returns 0 rows, the Plotly code will fail with a cryptic pandas error. We should catch this early and give a clear message.

**File:** `src/visualization_agent.py`

**Find `run_query_node` function (around line 108) and update it:**

```python
def run_query_node(state):
    messages = list(state["messages"])
    last_message = messages[-1]

    if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
        return {"sql_valid": False}

    query = last_message.tool_calls[0]["args"]["query"]
    result = execute_query_with_handoff(db, query, intent=state.get("intent", "answer"))

    # NEW: Check for empty results when visualization is needed
    if state.get("intent") in ["visualize", "multi_chart"]:
        if result["row_count"] == 0:
            return {
                "sql_valid": False,
                "execution_error": "Query returned 0 rows. Cannot create visualization. Please refine your query.",
                "warnings": [f"Empty result for query: {query[:100]}..."]
            }

    return {
        "generated_sql": query,
        "sql_valid": result["success"],
        "columns": result["columns"],
        "row_count": result["row_count"],
        "data_preview": result["data_preview"],
        "workspace": result["workspace"]
    }
```

**How to test:**
```bash
# This query should return a clear error instead of a cryptic pandas error
python visualization_agent.py "Show wages for NonexistentCity in 2023"
```

---

## Phase 2: Request Validation & Clarification

### Task 2.1: Add Query Feasibility Check

**Why:** The agent should ask for clarification when a query can't be answered with available data, instead of hallucinating a wrong answer.

**File:** `src/visualization_nodes.py`

**Add new function after `classify_intent` (around line 59):**

```python
def validate_request_feasibility(state: dict, model) -> dict:
    """
    Check if the user's request can be answered with available data.
    If not, generate a clarifying question.

    This prevents hallucination where the agent generates wrong output
    for impossible queries (e.g., "show GDP" when we don't have GDP data).
    """
    user_query = state["messages"][-1].content if hasattr(state["messages"][-1], 'content') else state["messages"][-1]["content"]
    intent = state.get("intent", "answer")

    # Only validate visualization requests (text answers can be more flexible)
    if intent == "answer":
        return {}

    # Available columns in our database
    AVAILABLE_COLUMNS = [
        "area_fips", "year", "qtr", "annual_avg_estabs_count", "annual_avg_emplvl",
        "total_annual_wages", "avg_annual_pay", "annual_avg_wkly_wage",
        "area_title", "state"
    ]

    AVAILABLE_METRICS = [
        "employment", "wages", "pay", "establishments", "weekly wage",
        "annual pay", "employment level"
    ]

    validation_prompt = f"""You are validating if a data visualization request can be fulfilled.

AVAILABLE DATA:
- Table: msa_wages_employment_data (US Metropolitan Statistical Areas)
- Columns: {', '.join(AVAILABLE_COLUMNS)}
- Years: 2000-2024
- Geographic: US MSAs (cities/metro areas) with area_title and state

USER REQUEST: {user_query}

TASK: Determine if this request can be answered with the available data.

If the request asks for data we DON'T have (GDP, population, housing prices, etc.),
respond with a clarifying question suggesting what we CAN provide.

If the request CAN be answered, respond with "VALID".

Examples:
- "Show GDP trends" → "I don't have GDP data. Would you like to see wage or employment trends instead?"
- "Population of cities" → "I don't have population data. I can show employment levels which indicate workforce size. Would that help?"
- "Wage trends for Austin" → "VALID"
- "Employment in California cities" → "VALID"
"""

    try:
        response = model.invoke([{"role": "user", "content": validation_prompt}])
        result = response.content.strip()

        if result.upper() == "VALID" or result.upper().startswith("VALID"):
            return {"request_valid": True}
        else:
            # Request needs clarification
            return {
                "request_valid": False,
                "clarification_needed": result,
                "warnings": [f"Request validation flagged: {result[:100]}"]
            }
    except Exception as e:
        # On error, proceed anyway (don't block the workflow)
        return {"request_valid": True, "warnings": [f"Validation check failed: {e}"]}
```

**File:** `src/visualization_agent.py`

**Update imports:**
```python
from visualization_nodes import classify_intent, validate_columns, generate_plotly_code, analyze_with_artifact, validate_request_feasibility
```

**Add the new node to the graph (in `build_visualization_agent`, around line 165-186):**

```python
def validate_request_node(state):
    return validate_request_feasibility(state, model)

# Add node
builder.add_node("validate_request", validate_request_node)

# Update edges - insert validation after intent classification
builder.add_edge(START, "classify_intent")
builder.add_edge("classify_intent", "validate_request")  # NEW

# Add conditional edge from validate_request
def route_after_validation(state) -> Literal["generate_query", "clarify"]:
    if state.get("request_valid", True):
        return "generate_query"
    return "clarify"

def clarify_node(state):
    """Return clarification message to user instead of proceeding."""
    clarification = state.get("clarification_needed", "Could you please clarify your request?")
    from langchain_core.messages import AIMessage
    return {
        "messages": [AIMessage(content=clarification)],
        "analysis": clarification,
        "execution_success": False
    }

builder.add_node("clarify", clarify_node)
builder.add_conditional_edges("validate_request", route_after_validation)
builder.add_edge("clarify", END)
```

**How to test:**
```bash
# This should ask for clarification instead of hallucinating
python visualization_agent.py "Show GDP trends for Boston"
# Expected: "I don't have GDP data. Would you like to see wage or employment trends instead?"

# This should work normally
python visualization_agent.py "Show wage trends for Boston"
```

---

### Task 2.2: Improve Error Messages in Graceful Degradation

**Why:** Currently, exceptions are swallowed and users don't know what went wrong.

**File:** `src/visualization_nodes.py`

**Update `classify_intent` (line 51-58):**

```python
except Exception as e:
    # Log the error instead of silent degradation
    from logger import log_warning
    warning = log_warning(f"Intent classification failed: {e}. Defaulting to 'answer' mode.")
    return {
        "intent": "answer",
        "suggested_chart_types": [],
        "num_charts": 0,
        "intent_reasoning": f"Classification failed, defaulting to answer: {e}",
        "warnings": [warning]
    }
```

**Update `generate_plotly_code` (line 126-133):**

```python
except Exception as e:
    from logger import log_warning
    warning = log_warning(f"Code generation failed: {e}")
    return {
        "plotly_code": None,
        "chart_type": None,
        "columns_used": [],
        "code_generation_error": str(e),
        "execution_success": False,
        "warnings": [warning]
    }
```

**Update `analyze_with_artifact` (line 181-187):**

```python
except Exception as e:
    from logger import log_warning
    warning = log_warning(f"Analysis generation failed: {e}")

    # Still try to read artifact HTML if it exists
    artifact_html = None
    if workspace and workspace.output_path.exists():
        with open(workspace.output_path, 'r') as f:
            artifact_html = f.read()

    return {
        "analysis": f"Chart generated but analysis failed: {e}",
        "artifact_html": artifact_html,
        "artifact_path": str(workspace.output_path) if workspace else None,
        "warnings": [warning]
    }
```

---

### Task 2.3: Update State to Track Warnings

**File:** `src/state.py`

**Add warnings field to state:**

```python
class VisualizationState(TypedDict, total=False):
    """State for the enhanced SQL + Visualization agent."""

    # ... existing fields ...

    # NEW: Track warnings and validation status
    warnings: Optional[List[str]]
    request_valid: Optional[bool]
    clarification_needed: Optional[str]
```

---

## Phase 3: Evaluation Infrastructure

### Task 3.1: Create Evaluation Dataset

**File:** Create `tests/evaluation_dataset.json`

```json
{
  "version": "1.0",
  "description": "Test queries for visualization agent evaluation",
  "test_cases": [
    {
      "id": "text_001",
      "query": "What is the average wage in Austin in 2023?",
      "expected_intent": "answer",
      "expected_success": true,
      "category": "text_answer"
    },
    {
      "id": "text_002",
      "query": "How many MSAs are in the database?",
      "expected_intent": "answer",
      "expected_success": true,
      "category": "text_answer"
    },
    {
      "id": "viz_001",
      "query": "Show a line chart of wage trends for Austin from 2010 to 2024",
      "expected_intent": "visualize",
      "expected_success": true,
      "expected_chart_type": "line",
      "category": "single_chart"
    },
    {
      "id": "viz_002",
      "query": "Create a bar chart of top 10 cities by employment in 2023",
      "expected_intent": "visualize",
      "expected_success": true,
      "expected_chart_type": "bar",
      "category": "single_chart"
    },
    {
      "id": "viz_003",
      "query": "visualize employment and wage trends over time between 2000 and 2024 for Boston",
      "expected_intent": "multi_chart",
      "expected_success": true,
      "category": "multi_chart",
      "notes": "Known failing query - dual axis or subplot expected"
    },
    {
      "id": "viz_004",
      "query": "average wage across time for cities in california",
      "expected_intent": "visualize",
      "expected_success": true,
      "category": "multi_city",
      "notes": "Known failing query - should show multiple CA cities"
    },
    {
      "id": "viz_005",
      "query": "visualize a bar chart of employment growth between 2010 and 2015 for cities in arizona, new mexico, texas, and florida",
      "expected_intent": "visualize",
      "expected_success": true,
      "expected_chart_type": "bar",
      "category": "multi_state",
      "notes": "Known failing query - multi-state comparison"
    },
    {
      "id": "edge_001",
      "query": "visualize",
      "expected_intent": "visualize",
      "expected_success": true,
      "category": "edge_case",
      "notes": "Vague query - should produce something reasonable or ask for clarification"
    },
    {
      "id": "edge_002",
      "query": "Show GDP and population trends",
      "expected_intent": "visualize",
      "expected_success": false,
      "expected_clarification": true,
      "category": "impossible_query",
      "notes": "Should ask for clarification - GDP/population not in database"
    },
    {
      "id": "edge_003",
      "query": "wages for NonexistentCity",
      "expected_intent": "answer",
      "expected_success": false,
      "category": "nonexistent_data",
      "notes": "Should return clear error about no data found"
    },
    {
      "id": "multi_001",
      "query": "Create a dashboard showing employment AND wages for Seattle from 2015 to 2024",
      "expected_intent": "multi_chart",
      "expected_success": true,
      "category": "multi_chart"
    },
    {
      "id": "multi_002",
      "query": "Compare Austin vs Seattle vs Denver wages over time",
      "expected_intent": "visualize",
      "expected_success": true,
      "expected_chart_type": "line",
      "category": "multi_city"
    },
    {
      "id": "ranking_001",
      "query": "Show top 15 MSAs by average annual pay in 2024",
      "expected_intent": "visualize",
      "expected_success": true,
      "expected_chart_type": "bar",
      "category": "ranking"
    },
    {
      "id": "state_001",
      "query": "employment trends for Texas cities from 2018 to 2024",
      "expected_intent": "visualize",
      "expected_success": true,
      "category": "state_filter"
    },
    {
      "id": "growth_001",
      "query": "Which cities had the highest wage growth between 2019 and 2024?",
      "expected_intent": "answer",
      "expected_success": true,
      "category": "growth_calculation"
    }
  ]
}
```

---

### Task 3.2: Create Evaluation Script

**File:** Create `tests/run_evaluation.py`

```python
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
            "success": result.get("execution_success", False) or bool(result.get("analysis")),
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
    actual_success = result.get("execution_success", False) or bool(result.get("analysis"))
    if test_case.get("expected_success") != actual_success:
        evaluation["passed"] = False
        evaluation["failures"].append(
            f"Success mismatch: expected {test_case.get('expected_success')}, got {actual_success}"
        )

    # Check chart type if specified
    if "expected_chart_type" in test_case and actual_success:
        if result.get("chart_type") != test_case["expected_chart_type"]:
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
            result = classify_single(test_case["query"], save_viz=False)
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
```

**How to run:**
```bash
cd /home/fortu/GitHub/City-Growth-AI-Agent/src
source ../.venv/bin/activate
python ../tests/run_evaluation.py
```

---

### Task 3.3: Create Quick Test Script for Known Failing Queries

**File:** Create `tests/test_known_failures.py`

```python
#!/usr/bin/env python3
"""
test_known_failures.py - Quick test of the three known failing queries

Run this after making fixes to verify they're resolved.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from visualization_agent import classify_single

KNOWN_FAILURES = [
    "visualize employment and wage trends over time between 2000 and 2024 for Boston",
    "average wage across time for cities in california",
    "visualize a bar chart of employment growth between 2010 and 2015 for cities in arizona, new mexico, texas, and florida",
]

def main():
    print("Testing Known Failure Cases")
    print("=" * 80)

    for i, query in enumerate(KNOWN_FAILURES, 1):
        print(f"\n[{i}/3] Query: {query}")
        print("-" * 40)

        try:
            result = classify_single(query, save_viz=True)

            print(f"Intent: {result.get('intent')}")
            print(f"Success: {result.get('execution_success')}")
            print(f"Chart Type: {result.get('chart_type')}")
            print(f"Row Count: {result.get('row_count')}")
            print(f"Time: {result.get('execution_time_seconds')}s")

            if result.get('artifact_path'):
                print(f"Artifact: {result.get('artifact_path')}")

            if result.get('analysis'):
                print(f"Analysis preview: {result.get('analysis')[:200]}...")

        except Exception as e:
            print(f"ERROR: {e}")

    print("\n" + "=" * 80)
    print("Done. Check the generated HTML files in src/viz/")


if __name__ == "__main__":
    main()
```

---

## Implementation Checklist

Use this checklist to track progress:

### Phase 1: Determinism & Logging
- [ ] Task 1.1: Add temperature=0 to model initialization
- [ ] Task 1.2: Create logger.py and add logging to classify_single
- [ ] Task 1.3: Add empty result check in run_query_node
- [ ] Test: Run same query 3x, verify identical output
- [ ] Test: Check logs/agent_runs.jsonl is being populated

### Phase 2: Validation & Clarification
- [ ] Task 2.1: Add validate_request_feasibility function
- [ ] Task 2.1: Add validate_request node to graph
- [ ] Task 2.1: Add clarify node and routing
- [ ] Task 2.2: Update error handling in classify_intent
- [ ] Task 2.2: Update error handling in generate_plotly_code
- [ ] Task 2.2: Update error handling in analyze_with_artifact
- [ ] Task 2.3: Add warnings field to state.py
- [ ] Test: Query for "GDP trends" should ask for clarification
- [ ] Test: Query for nonexistent city should return clear error

### Phase 3: Evaluation Infrastructure
- [ ] Task 3.1: Create evaluation_dataset.json
- [ ] Task 3.2: Create run_evaluation.py
- [ ] Task 3.3: Create test_known_failures.py
- [ ] Test: Run full evaluation suite
- [ ] Test: Verify known failing queries are in dataset

---

## Verification Commands

After implementing all phases, run these commands to verify:

```bash
cd /home/fortu/GitHub/City-Growth-AI-Agent/src
source ../.venv/bin/activate

# 1. Test determinism (should produce identical output)
python visualization_agent.py "Show wages for Austin 2023"
python visualization_agent.py "Show wages for Austin 2023"

# 2. Check logging works
cat ../logs/agent_runs.jsonl

# 3. Test clarification on impossible query
python visualization_agent.py "Show GDP trends for Boston"

# 4. Test known failures
python ../tests/test_known_failures.py

# 5. Run full evaluation
python ../tests/run_evaluation.py
```

---

## Notes for Reviewer

1. **Do not modify** files outside of `src/` and `tests/` directories
2. **Create** the `logs/` directory will be auto-created by logger.py
3. **Temperature=0** may slightly increase latency but ensures consistency
4. **Clarification feature** means some queries will now return questions instead of wrong answers - this is intended behavior
5. All changes are **backward compatible** - existing functionality is preserved
