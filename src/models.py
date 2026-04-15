"""
models.py - Pydantic models for structured LLM output

Using structured output eliminates fragile string parsing and guarantees schema.
"""

from typing import Literal, Optional, List
from pydantic import BaseModel, Field


class IntentClassification(BaseModel):
    """Result of classifying user intent."""
    intent: Literal["answer", "visualize", "multi_chart"] = Field(
        description="'answer' for text, 'visualize' for single chart, 'multi_chart' for multiple charts"
    )
    chart_types: List[str] = Field(
        default_factory=list,
        description="Suggested chart types: line, bar, scatter, histogram, etc."
    )
    num_charts: int = Field(
        default=1,
        description="Number of distinct charts needed"
    )
    reasoning: str = Field(
        description="Brief explanation of classification decision"
    )


class PlotlyCodeOutput(BaseModel):
    """Structured output for Plotly code generation."""
    code: str = Field(description="Complete Python code for the visualization")
    chart_type: str = Field(description="The chart type used")
    columns_used: List[str] = Field(description="Columns from the CSV used in the chart")


class QueryPlan(BaseModel):
    """Structured output for SQL query planning."""
    data_requirements: str = Field(
        description="Plain-English description of exactly what data the SQL query must return. "
        "Include: metrics needed, filtering criteria, time range, grouping, sorting, and any calculations."
    )
    sql_strategy: str = Field(
        description="Specific SQL approach: e.g., 'Use CTE to first identify top 10 MSAs by X, "
        "then join back to get time series for those MSAs' or 'Simple GROUP BY with HAVING'"
    )
    expected_columns: List[str] = Field(
        description="Column names the result set should contain (e.g., ['area_title', 'year', 'annual_avg_emplvl'])"
    )
    expected_row_estimate: str = Field(
        description="Rough estimate of expected rows, e.g., '~50 rows (5 cities x 10 years)' or '10 rows (top 10)'"
    )


class AnalysisOutput(BaseModel):
    """Structured output for chart analysis."""
    summary: str = Field(description="Brief description of what the chart shows")
    insights: List[str] = Field(description="2-3 key insights or trends", max_length=4)
