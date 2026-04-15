"""
tools.py - Enhanced SQL tool with data handoff capability

The key insight: LLMs should reason about SCHEMA, not DATA.
For visualization, we save results to CSV and return only the schema.
"""

import csv
import time
from typing import Literal
from langchain_community.utilities import SQLDatabase
from workspace import create_workspace, JobWorkspace


def execute_query_with_handoff(
    db: SQLDatabase,
    query: str,
    intent: Literal["answer", "visualize", "multi_chart"],
    max_rows_in_context: int = 50
) -> dict:
    """
    Execute SQL query with smart data handoff.

    For 'answer' intent: Returns rows in context (for small results)
    For 'visualize'/'multi_chart' intent: Saves to CSV, returns only schema

    Args:
        db: SQLDatabase instance
        query: SQL query to execute
        intent: "answer" for text response, "visualize"/"multi_chart" for charts
        max_rows_in_context: Max rows to return in context (answer mode)

    Returns:
        dict with keys:
        - success: bool
        - row_count: int
        - columns: list[str]
        - data_preview: str (first few rows, for LLM context)
        - workspace: JobWorkspace (only for visualize intent)
        - error: str (if failed)
        - execution_time_ms: int
    """
    start_time = time.time()

    try:
        # Execute query and get results with column names
        # Use the underlying engine directly for better control
        from sqlalchemy import text
        with db._engine.connect() as conn:
            result = conn.execute(text(query))
            columns = list(result.keys())
            rows = [dict(zip(columns, row)) for row in result.fetchall()]

        execution_time_ms = int((time.time() - start_time) * 1000)

        if not rows:
            return {
                "success": True,
                "row_count": 0,
                "columns": [],
                "data_preview": "No results returned",
                "workspace": None,
                "error": None,
                "execution_time_ms": execution_time_ms
            }

        columns = list(rows[0].keys()) if rows else []
        row_count = len(rows)

        # For answer intent with small results, return in context
        if intent == "answer" and row_count <= max_rows_in_context:
            preview = _format_rows_for_context(rows[:max_rows_in_context])
            return {
                "success": True,
                "row_count": row_count,
                "columns": columns,
                "data_preview": preview,
                "workspace": None,
                "error": None,
                "execution_time_ms": execution_time_ms
            }

        # For visualize/multi_chart intent OR large data, save to file
        workspace = create_workspace()

        with open(workspace.data_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)

        workspace.record_timing("sql_execution", execution_time_ms)

        # Return only schema + preview (NOT full data)
        preview = _format_rows_for_context(rows[:5])

        return {
            "success": True,
            "row_count": row_count,
            "columns": columns,
            "data_preview": f"[{row_count} rows saved to {workspace.data_path}]\n\nPreview (first 5 rows):\n{preview}",
            "workspace": workspace,
            "error": None,
            "execution_time_ms": execution_time_ms
        }

    except Exception as e:
        return {
            "success": False,
            "row_count": 0,
            "columns": [],
            "data_preview": "",
            "workspace": None,
            "error": str(e),
            "execution_time_ms": int((time.time() - start_time) * 1000)
        }


def _format_rows_for_context(rows: list[dict], max_chars: int = 2000) -> str:
    """Format rows as readable text for LLM context."""
    if not rows:
        return "No data"

    columns = list(rows[0].keys())
    lines = [",".join(columns)]

    for row in rows:
        line = ",".join(str(row.get(col, "")) for col in columns)
        lines.append(line)

        if sum(len(l) for l in lines) > max_chars:
            lines.append(f"... ({len(rows) - len(lines) + 1} more rows)")
            break

    return "\n".join(lines)
