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

from models import IntentClassification, PlotlyCodeOutput, AnalysisOutput
from prompts import (
    INTENT_CLASSIFICATION_PROMPT,
    GENERATE_PLOTLY_PROMPT,
    ANALYZE_WITH_ARTIFACT_PROMPT
)


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
        # Graceful degradation: default to answer intent
        return {
            "intent": "answer",
            "suggested_chart_types": [],
            "num_charts": 0,
            "intent_reasoning": f"Classification failed, defaulting to answer: {e}"
        }


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
        # Graceful degradation
        return {
            "plotly_code": None,
            "chart_type": None,
            "columns_used": [],
            "code_generation_error": str(e)
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
        # Graceful degradation
        return {
            "analysis": f"Chart generated but analysis failed: {e}",
            "artifact_html": None,
            "artifact_path": str(workspace.output_path) if workspace else None
        }
