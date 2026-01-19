# Quick Fix Plan: SQL Review Node + Iterative Loop

**Status:** Awaiting Approval
**Created:** 2026-01-18
**Target:** Fix the CAGR query failure by adding SQL validation and retry loop

---

## Problem Summary

The query `"visualize a bar chart of cagr of employment and average wage between 2014 and 2024 for Boston, NYC, LA, Chicago, Miami, Austin, and Washington DC"` generated:

```sql
SELECT MAX(year) FROM msa_wages_employment_data;
```

Instead of a proper CAGR calculation with city filtering.

---

## Solution Overview

### Changes to Implement

| # | Change | File | Purpose |
|---|--------|------|---------|
| 1 | Add `review_sql` node | `visualization_nodes.py` | Validate SQL matches user intent |
| 2 | Add SQL loop routing | `visualization_agent.py` | Allow retry if SQL is wrong |
| 3 | Increase temperature to 1 | `visualization_agent.py` | More creative SQL generation |
| 4 | Add state fields for SQL loop | `state.py` | Track SQL attempts and feedback |
| 5 | Add SQL review prompt | `prompts.py` | LLM prompt for SQL validation |

---

## Detailed Implementation

### 1. New State Fields (`state.py`)

Add these fields to track the SQL review loop:

```python
# SQL review loop tracking
sql_review_passed: Optional[bool]       # Did the SQL pass review?
sql_review_feedback: Optional[str]      # Feedback if review failed
sql_attempts: Optional[int]             # Number of SQL generation attempts
max_sql_attempts: int = 3               # Max attempts before giving up
```

---

### 2. New Prompt (`prompts.py`)

Add `SQL_REVIEW_PROMPT`:

```python
SQL_REVIEW_PROMPT = """You are a SQL query reviewer validating that a query matches the user's request.

USER REQUEST: {user_request}

GENERATED SQL:
{generated_sql}

QUERY RESULT PREVIEW:
- Columns: {columns}
- Row count: {row_count}
- Data preview: {data_preview}

VALIDATION CHECKLIST:
1. Does the query retrieve the correct METRICS mentioned in the request?
   - Employment data: annual_avg_emplvl
   - Wage data: avg_annual_pay, total_annual_wages, annual_avg_wkly_wage
   - Establishments: annual_avg_estabs_count

2. Does the query filter for the correct LOCATIONS (cities/states)?
   - Check if WHERE clause includes the requested areas

3. Does the query cover the correct TIME RANGE?
   - Check year filtering matches the request

4. For CALCULATIONS (growth, CAGR, change, comparison):
   - CAGR formula: ((end_value / start_value) ^ (1/years) - 1) * 100
   - Growth: (end_value - start_value) / start_value * 100
   - Does the query perform the calculation or just return raw data?

5. Is the ROW COUNT reasonable?
   - If user asks for 7 cities and we get 1 row, something is wrong
   - If user asks for trends over 10 years and we get 1 row, something is wrong

RESPOND WITH ONE OF:
- "PASS" - if the query correctly addresses the user's request
- "FAIL: <specific feedback>" - if the query is wrong, with instructions for what to fix

Be strict. If the query doesn't calculate what the user asked for, it should FAIL.
"""
```

---

### 3. New Node (`visualization_nodes.py`)

Add `review_sql` function:

```python
def review_sql(state: dict, model) -> dict:
    """
    Review the generated SQL to ensure it matches user intent.

    This is the key anti-hallucination check that catches queries like
    "SELECT MAX(year)" when the user asked for CAGR calculations.
    """
    user_query = state["messages"][0].content if hasattr(state["messages"][0], 'content') else state["messages"][0]["content"]

    prompt = SQL_REVIEW_PROMPT.format(
        user_request=user_query,
        generated_sql=state.get("generated_sql", ""),
        columns=state.get("columns", []),
        row_count=state.get("row_count", 0),
        data_preview=state.get("data_preview", "")
    )

    try:
        response = model.invoke([{"role": "user", "content": prompt}])

        # Extract text from response
        if isinstance(response.content, list):
            result = response.content[0].get('text', '') if response.content else ''
        else:
            result = str(response.content)

        result = result.strip()

        if result.upper().startswith("PASS"):
            return {
                "sql_review_passed": True,
                "sql_review_feedback": None
            }
        else:
            # Extract feedback after "FAIL:"
            feedback = result.replace("FAIL:", "").strip()
            attempts = state.get("sql_attempts", 1)

            from logger import log_warning
            log_warning(f"SQL review failed (attempt {attempts}): {feedback[:100]}")

            return {
                "sql_review_passed": False,
                "sql_review_feedback": feedback,
                "sql_attempts": attempts + 1
            }
    except Exception as e:
        from logger import log_warning
        log_warning(f"SQL review error: {e}")
        # On error, let it pass (don't block workflow)
        return {"sql_review_passed": True}
```

---

### 4. Updated Graph (`visualization_agent.py`)

#### 4.1 Temperature Change

```python
# Change from:
return init_chat_model(MODEL_ID, temperature=0)

# To:
return init_chat_model(MODEL_ID, temperature=1)
```

#### 4.2 Add Review Node and Loop

```python
# Add the review node
builder.add_node("review_sql", review_sql_node)

# New routing function for SQL loop
def route_after_sql_review(state) -> Literal["generate_query", "validate_columns", "analyze_results", END]:
    """Route based on SQL review results."""
    if state.get("sql_review_passed", True):
        # SQL is good, proceed based on intent
        if state.get("intent") in ["visualize", "multi_chart"] and state.get("workspace"):
            return "validate_columns"
        return "analyze_results"

    # SQL review failed - check attempt count
    attempts = state.get("sql_attempts", 1)
    if attempts >= 3:
        # Max attempts reached, proceed anyway with warning
        from logger import log_warning
        log_warning(f"SQL review failed after {attempts} attempts, proceeding anyway")
        if state.get("intent") in ["visualize", "multi_chart"] and state.get("workspace"):
            return "validate_columns"
        return "analyze_results"

    # Retry SQL generation
    return "generate_query"
```

#### 4.3 Updated Graph Edges

```
Current:
  run_query ──► route_by_intent ──► validate_columns OR analyze_results

New:
  run_query ──► review_sql ──► route_after_sql_review ──┬──► validate_columns
                     ▲                                  ├──► analyze_results
                     │                                  └──► generate_query (retry)
                     │                                              │
                     └──────────────────────────────────────────────┘
```

---

### 5. Enhanced SQL Generation Prompt

Update `generate_query_system_prompt` in `visualization_agent.py` to include:

```python
# Add to the existing prompt:
"""
CALCULATION REQUIREMENTS:
- If user asks for "growth" or "change": Calculate percentage change
- If user asks for "CAGR": Use formula POWER(end_value::numeric / start_value, 1.0/years) - 1
- If user asks for "comparison": Get data for all entities being compared

IMPORTANT: If you previously attempted a query and received feedback, incorporate that feedback:
{sql_review_feedback}
"""
```

The feedback will be passed from the state when regenerating.

---

## New Graph Flow

```
START
  │
  ▼
classify_intent
  │
  ▼
validate_request ──► [invalid] ──► clarify ──► END
  │
  │ [valid]
  ▼
generate_query ◄─────────────────────────────────────┐
  │                                                   │
  ▼                                                   │
run_query                                             │
  │                                                   │
  ▼                                                   │
review_sql ──► [FAIL + attempts < 3] ─────────────────┘
  │
  │ [PASS or attempts >= 3]
  ▼
route_by_intent
  │
  ├──► analyze_results ──► END
  │
  └──► validate_columns ──► generate_plotly ──► execute_code ──► analyze_artifact ──► END
```

---

## Files to Modify

| File | Lines | Changes |
|------|-------|---------|
| `src/state.py` | +5 | Add sql_review_passed, sql_review_feedback, sql_attempts fields |
| `src/prompts.py` | +40 | Add SQL_REVIEW_PROMPT |
| `src/visualization_nodes.py` | +50 | Add review_sql function |
| `src/visualization_agent.py` | +30 | Add review node, loop routing, temperature=1 |

**Total:** ~125 lines of changes

---

## Testing Plan

After implementation, test with:

1. **The failing query:**
   ```
   uv run src/visualization_agent.py "visualize a bar chart of cagr of employment and average wage between 2014 and 2024 for Boston, NYC, LA, Chicago, Miami, Austin, and Washington DC"
   ```

2. **Simpler regression tests:**
   ```
   uv run src/visualization_agent.py "Show a line chart of wage trends for Austin from 2010 to 2024"
   uv run src/visualization_agent.py "Create a bar chart of top 10 cities by employment in 2023"
   ```

3. **Edge cases:**
   ```
   uv run src/visualization_agent.py "employment growth rate for Texas cities"
   uv run src/visualization_agent.py "compare wages between 2019 and 2024 for Miami and Seattle"
   ```

---

## Rollback Plan

If the fix introduces regressions:
1. Revert temperature to 0
2. Comment out review_sql node
3. Restore direct routing from run_query to route_by_intent

---

## Approval Required

Please review this plan and approve before I implement the changes.

**Questions:**
1. Is the max 3 SQL attempts acceptable? (adds latency on failures)
2. Should we log all SQL review feedback to the runs log?
3. Any additional test cases to include?
