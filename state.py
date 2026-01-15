"""
state.py - Enhanced state for visualization agent

CRITICAL: Uses Annotated types with reducers for proper message accumulation.
"""

from typing import TypedDict, Optional, List, Annotated
from langgraph.graph.message import add_messages
from workspace import JobWorkspace


class VisualizationState(TypedDict, total=False):
    """State for the enhanced SQL + Visualization agent."""

    # Input - MUST use add_messages reducer
    messages: Annotated[list, add_messages]

    # Intent classification (LLM-driven with multi-chart support)
    intent: Optional[str]
    suggested_chart_types: Optional[List[str]]
    num_charts: Optional[int]

    # SQL phase
    generated_sql: Optional[str]
    sql_valid: Optional[bool]
    columns: Optional[List[str]]
    columns_validated: Optional[bool]
    row_count: Optional[int]
    data_preview: Optional[str]

    # Visualization phase
    workspace: Optional[JobWorkspace]
    plotly_code: Optional[str]
    chart_type: Optional[str]
    columns_used: Optional[List[str]]

    # Execution phase
    execution_success: Optional[bool]
    execution_error: Optional[str]
    execution_attempts: Optional[int]
    retry_count: Optional[int]

    # Output
    analysis: Optional[str]
    artifact_html: Optional[str]
    artifact_path: Optional[str]

    # Timing
    execution_time_seconds: Optional[float]
