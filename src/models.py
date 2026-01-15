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


class AnalysisOutput(BaseModel):
    """Structured output for chart analysis."""
    summary: str = Field(description="Brief description of what the chart shows")
    insights: List[str] = Field(description="2-3 key insights or trends", max_length=4)
