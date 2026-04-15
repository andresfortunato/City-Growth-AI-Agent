"""
workflow_tool.py - Tool that wraps the existing visualization workflow

This is the primary tool for data analysis and visualization. It invokes
the full LangGraph workflow that handles SQL generation, validation,
execution, and visualization.
"""

import asyncio
import json
import sys
from pathlib import Path
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


@tool
async def data_analysis_workflow(
    question: str,
    config: RunnableConfig = None
) -> str:
    """Run the full data analysis and visualization pipeline.

    Use this tool when the user wants:
    - Data analysis with a specific answer (e.g., "What is the average wage in Austin?")
    - A visualization/chart (e.g., "Show wage trends in Austin from 2010 to 2024")
    - Multiple charts comparing data (e.g., "Compare employment AND wages for Austin vs Dallas")

    This tool handles:
    - SQL generation with validation and retry (up to 5 attempts)
    - Query execution and data extraction
    - Visualization generation (Plotly charts)
    - Analysis and insights generation

    Do NOT use this for:
    - Simple schema questions (use get_schema instead)
    - Exploring what data exists (use sample_data or list_cities instead)
    - Testing SQL queries (use query_database instead)

    Args:
        question: The user's analytical question (e.g., "Show wage trends in Austin")

    Returns:
        Analysis text with insights. If visualization was created, includes the file path.
        On failure, includes detailed context about what went wrong.
    """
    # Import here to avoid circular imports
    from visualization_agent import classify_single

    # Run sync workflow in thread to avoid blocking
    result = await asyncio.to_thread(classify_single, question, True)

    # Build response based on success/failure
    response_parts = []

    if result.get("execution_success") and result.get("analysis"):
        # Success case
        response_parts.append(result["analysis"])

        if result.get("artifact_path"):
            response_parts.append(f"\nVisualization saved to: {result['artifact_path']}")

            # Try to read JSON spec for web embedding
            artifact_json = None
            artifact_path_obj = Path(result["artifact_path"])
            json_path = artifact_path_obj.with_suffix(".json")

            # Also check workspace for JSON
            if not json_path.exists() and result.get("workspace"):
                workspace_json = result["workspace"].json_path
                if workspace_json.exists():
                    json_path = workspace_json

            if json_path.exists():
                try:
                    artifact_json = json_path.read_text()
                    # Include as metadata marker for conversation.py to extract
                    metadata = {
                        "artifact_json": artifact_json,
                        "artifact_path": result["artifact_path"],
                    }
                    response_parts.append(f"\nARTIFACT_METADATA:{json.dumps(metadata)}")
                except Exception:
                    pass

        if result.get("row_count"):
            response_parts.append(f"\nData: {result['row_count']} rows analyzed")

    elif result.get("analysis") and result.get("row_count", 0) > 0:
        # Partial success - got analysis even if execution_success is False
        response_parts.append(result["analysis"])

        if result.get("artifact_path"):
            response_parts.append(f"\nVisualization saved to: {result['artifact_path']}")

            # Try to read JSON spec for partial success too
            artifact_json = None
            artifact_path_obj = Path(result["artifact_path"])
            json_path = artifact_path_obj.with_suffix(".json")

            if json_path.exists():
                try:
                    artifact_json = json_path.read_text()
                    metadata = {
                        "artifact_json": artifact_json,
                        "artifact_path": result["artifact_path"],
                    }
                    response_parts.append(f"\nARTIFACT_METADATA:{json.dumps(metadata)}")
                except Exception:
                    pass

    else:
        # Failure case - provide detailed context for agent to reason about
        response_parts.append("The workflow encountered issues processing this request.")

        if result.get("row_count", 0) == 0:
            response_parts.append("\nNo data was returned by the query.")

        if result.get("sql_review_passed") is False:
            response_parts.append(f"\nSQL Review: Failed after {result.get('sql_attempts', 0)} attempts")
            if result.get("sql_review_feedback"):
                response_parts.append(f"Feedback: {result['sql_review_feedback']}")

        if result.get("execution_error"):
            response_parts.append(f"\nExecution Error: {result['execution_error']}")

        if result.get("generated_sql"):
            # Include SQL for debugging (truncated)
            sql = result["generated_sql"]
            if len(sql) > 500:
                sql = sql[:500] + "..."
            response_parts.append(f"\nLast SQL attempted:\n```sql\n{sql}\n```")

        # Suggest alternatives
        response_parts.append("\n\nSuggestions:")
        response_parts.append("- Try rephrasing the question with more specific details")
        response_parts.append("- Use list_cities to verify city names are correct")
        response_parts.append("- Use get_schema to check available columns")
        response_parts.append("- Use query_database to explore the data first")

    # Add warnings if any
    if result.get("warnings"):
        response_parts.append(f"\nWarnings: {', '.join(result['warnings'])}")

    return "\n".join(response_parts) if response_parts else "No results returned from the workflow."
