"""
visualization_nodes.py - Nodes for visualization workflow

These nodes handle:
1. Classifying user intent (LLM-driven with multi-chart detection)
2. Validating columns exist (anti-hallucination, optional)
3. Generating Plotly code with structured output
4. Analyzing results with artifact
"""

import time
from typing import Optional
from langchain_core.messages import AIMessage

from models import IntentClassification, PlotlyCodeOutput, AnalysisOutput, QueryPlan
from prompts import (
    INTENT_CLASSIFICATION_PROMPT,
    GENERATE_PLOTLY_PROMPT,
    ANALYZE_WITH_ARTIFACT_PROMPT,
    SQL_REVIEW_PROMPT,
    QUERY_PLAN_PROMPT
)


def _extract_text(response) -> str:
    """Extract plain text from an LLM response, handling all content formats.

    Gemini can return response.content as:
    - str: "VALID"
    - list of dicts: [{"type": "text", "text": "VALID"}]
    - list of objects with .text attribute
    - list of strings
    """
    content = response.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if not content:
            return ""
        first = content[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            return first.get("text", str(first))
        if hasattr(first, "text"):
            return first.text
        return str(first)
    return str(content)


def classify_intent(state: dict, model) -> dict:
    """
    Determine if user wants a text answer, single chart, or multiple charts.

    Uses LLM classification (not keyword matching) to handle nuanced queries like:
    - "How has Austin's economy grown?" → visualize (implies trend)
    - "Show wages AND employment" → multi_chart (two metrics)
    """
    start_time = time.time()
    user_query = state["messages"][-1].content if hasattr(state["messages"][-1], 'content') else state["messages"][-1]["content"]

    structured_model = model.with_structured_output(IntentClassification)

    try:
        response = structured_model.invoke([
            {"role": "system", "content": INTENT_CLASSIFICATION_PROMPT},
            {"role": "user", "content": f"Classify this request: {user_query}"}
        ])

        elapsed = int((time.time() - start_time) * 1000)

        return {
            "intent": response.intent,
            "suggested_chart_types": response.chart_types,
            "num_charts": response.num_charts,
            "intent_reasoning": response.reasoning,
            "classify_time_ms": elapsed
        }
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


def plan_queries(state: dict, model) -> dict:
    """
    Decompose the user's request into a structured query plan.

    This node runs BEFORE SQL generation and produces a detailed plan
    that guides the SQL generator. It prevents the LLM from writing
    incomplete queries (e.g., SELECT MAX(year) when user wants time series).
    """
    user_query = state["messages"][0].content if hasattr(state["messages"][0], 'content') else state["messages"][0]["content"]

    prompt = QUERY_PLAN_PROMPT.format(user_request=user_query)

    structured_model = model.with_structured_output(QueryPlan)

    try:
        response = structured_model.invoke([
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Plan the query strategy for: {user_query}"}
        ])

        # Format the plan as guidance text for the SQL generator
        plan_text = (
            f"DATA REQUIREMENTS: {response.data_requirements}\n"
            f"SQL STRATEGY: {response.sql_strategy}\n"
            f"EXPECTED COLUMNS: {', '.join(response.expected_columns)}\n"
            f"EXPECTED ROWS: {response.expected_row_estimate}"
        )

        return {
            "query_plan": plan_text,
            "query_plan_reasoning": response.sql_strategy
        }
    except Exception as e:
        from logger import log_warning
        warning = log_warning(f"Query planning failed: {e}")
        return {
            "query_plan": None,
            "query_plan_reasoning": None,
            "warnings": [warning]
        }


def validate_request_feasibility(state: dict, model) -> dict:
    """
    Check if the user's request can be answered with available data.
    If not, generate a clarifying question.

    This prevents hallucination where the agent generates wrong output
    for impossible queries (e.g., "show GDP" when we don't have GDP data).
    """
    user_query = state["messages"][-1].content if hasattr(state["messages"][-1], 'content') else state["messages"][-1]["content"]
    intent = state.get("intent", "answer")

    # Validate ALL intents, not just visualization requests
    # Note: intent should always be set by classify_intent, but default to "answer"

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
- Metrics: Employment levels, wages, pay, establishments, trends over time

UNAVAILABLE DATA (reject these):
- GDP (Gross Domestic Product)
- Population
- Housing prices
- Cost of living
- Stock prices
- Revenue
- Profit
- Market share

USER REQUEST: {user_query}

TASK: Determine if this request can be answered with the available data.

IMPORTANT: Check for mentions of unavailable metrics (GDP, population, housing, cost of living, etc.).
Even if the request includes words like "show" or "visualize", if it's asking for unavailable data, respond with a clarification.

If the request asks for data we DON'T have, respond with a clarifying question suggesting what we CAN provide.

If the request CAN be answered with available metrics, respond with "VALID".

Examples:
- "Show GDP trends" → "I don't have GDP data. Would you like to see wage or employment trends instead?"
- "Population of cities" → "I don't have population data. I can show employment levels which indicate workforce size. Would that help?"
- "Wage trends for Austin" → "VALID"
- "Employment in California cities" → "VALID"
"""

    try:
        response = model.invoke([{"role": "user", "content": validation_prompt}])
        result = _extract_text(response).strip()

        # Check if response indicates the request is valid
        # Only "VALID" (exact match or starting with VALID) means proceed
        if result.upper() == "VALID" or result.upper().startswith("VALID"):
            return {"request_valid": True}
        else:
            # Request needs clarification - response contains clarifying message
            return {
                "request_valid": False,
                "clarification_needed": result,
                "warnings": [f"Request validation flagged: {result[:100]}"]
            }
    except Exception as e:
        # On error, proceed anyway (don't block the workflow)
        from logger import log_warning
        warning = log_warning(f"Validation check failed: {e}")
        return {"request_valid": True, "warnings": [warning]}


def validate_columns(state: dict) -> dict:
    """
    Anti-hallucination: Verify that columns exist in the CSV.

    NOTE: This adds ~100-200ms latency. Consider removing if it becomes a bottleneck.
    Can be disabled by setting SKIP_COLUMN_VALIDATION=true environment variable.

    This prevents generating code that references non-existent columns.
    """
    import os
    if os.getenv("SKIP_COLUMN_VALIDATION", "false").lower() == "true":
        return {}

    workspace = state.get("workspace")
    if not workspace or not workspace.data_path.exists():
        return {}

    try:
        import csv
        with open(workspace.data_path, 'r') as f:
            reader = csv.reader(f)
            actual_columns = next(reader)

        return {"columns": actual_columns, "columns_validated": True}
    except Exception:
        # Graceful degradation: pass through unchanged
        return {}


def review_sql(state: dict, model) -> dict:
    """
    Review the generated SQL to ensure it matches user intent.

    This is the key anti-hallucination check that catches queries like
    "SELECT MAX(year)" when the user asked for CAGR calculations.

    Returns:
        sql_review_passed: bool - whether SQL passes review
        sql_review_feedback: str - feedback if failed (used for retry)
        sql_attempts: int - incremented attempt counter
    """
    from logger import log_run, log_warning

    user_query = state["messages"][0].content if hasattr(state["messages"][0], 'content') else state["messages"][0]["content"]
    current_attempts = state.get("sql_attempts", 1)

    prompt = SQL_REVIEW_PROMPT.format(
        user_request=user_query,
        generated_sql=state.get("generated_sql", ""),
        columns=state.get("columns", []),
        row_count=state.get("row_count", 0),
        data_preview=state.get("data_preview", "")
    )

    try:
        response = model.invoke([{"role": "user", "content": prompt}])
        result = _extract_text(response).strip()

        if result.upper().startswith("PASS"):
            log_warning(f"SQL review PASSED (attempt {current_attempts})")
            return {
                "sql_review_passed": True,
                "sql_review_feedback": None,
                "sql_attempts": current_attempts
            }
        else:
            # Extract feedback after "FAIL:"
            feedback = result.replace("FAIL:", "").replace("FAIL", "").strip()

            log_warning(f"SQL review FAILED (attempt {current_attempts}): {feedback[:200]}")

            return {
                "sql_review_passed": False,
                "sql_review_feedback": feedback,
                "sql_attempts": current_attempts + 1
            }
    except Exception as e:
        log_warning(f"SQL review error: {e}")
        # On error, let it pass (don't block workflow)
        return {
            "sql_review_passed": True,
            "sql_review_feedback": None,
            "sql_attempts": current_attempts
        }


def generate_plotly_code(state: dict, model) -> dict:
    """
    Generate Plotly code using structured output (no string parsing).

    Uses Pydantic model to guarantee clean code output.
    """
    start_time = time.time()
    workspace = state["workspace"]
    user_query = state["messages"][-1].content if hasattr(state["messages"][-1], 'content') else state["messages"][-1]["content"]

    prompt = GENERATE_PLOTLY_PROMPT.format(
        data_path=str(workspace.data_path),
        output_path=str(workspace.output_path),
        columns=", ".join(state["columns"]),
        row_count=state["row_count"],
        data_preview=state["data_preview"],
        user_request=user_query
    )

    structured_model = model.with_structured_output(PlotlyCodeOutput)

    try:
        response = structured_model.invoke([
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Generate Plotly code for: {user_query}"}
        ])

        elapsed = int((time.time() - start_time) * 1000)
        workspace.record_timing("code_generation", elapsed)

        return {
            "plotly_code": response.code,
            "chart_type": response.chart_type,
            "columns_used": response.columns_used,
            "retry_count": 0
        }
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


def analyze_with_artifact(state: dict, model) -> dict:
    """
    Generate analysis text that accompanies the visualization.

    Uses structured output for consistent format.
    """
    start_time = time.time()
    workspace = state["workspace"]
    user_query = state["messages"][-1].content if hasattr(state["messages"][-1], 'content') else state["messages"][-1]["content"]

    prompt = ANALYZE_WITH_ARTIFACT_PROMPT.format(
        user_request=user_query,
        columns=", ".join(state["columns"]),
        row_count=state["row_count"]
    )

    structured_model = model.with_structured_output(AnalysisOutput)

    try:
        response = structured_model.invoke([
            {"role": "system", "content": prompt},
            {"role": "user", "content": "Provide analysis for the generated chart."}
        ])

        # Format as text for user
        analysis_text = response.summary + "\n\n"
        analysis_text += "Key insights:\n"
        for insight in response.insights:
            analysis_text += f"• {insight}\n"

        # Read artifact HTML
        artifact_html = None
        if workspace.output_path.exists():
            with open(workspace.output_path, 'r') as f:
                artifact_html = f.read()

        elapsed = int((time.time() - start_time) * 1000)
        workspace.record_timing("analysis", elapsed)

        return {
            "analysis": analysis_text,
            "artifact_html": artifact_html,
            "artifact_path": str(workspace.output_path),
            "messages": state["messages"] + [AIMessage(content=analysis_text)]
        }
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
