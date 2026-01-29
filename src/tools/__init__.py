"""
tools - Tool registry for the conversational agent

Exports all tools and provides get_all_tools() function.
"""

from .schema_tools import get_schema, sample_data, list_cities
from .query_tool import query_database
from .workflow_tool import data_analysis_workflow

__all__ = [
    "get_schema",
    "sample_data",
    "list_cities",
    "query_database",
    "data_analysis_workflow",
    "get_all_tools",
]


def get_all_tools():
    """Return all tools available to the conversational agent.

    Tools are ordered by typical usage:
    1. data_analysis_workflow - Primary tool for analysis and visualization
    2. get_schema - Understand available data
    3. sample_data - Preview data values
    4. list_cities - Find available MSAs
    5. query_database - Direct SQL for exploration
    """
    return [
        data_analysis_workflow,  # Primary tool for analysis/viz
        get_schema,              # Schema exploration
        sample_data,             # Data preview
        list_cities,             # City name lookup
        query_database,          # Direct SQL (exploration only)
    ]
