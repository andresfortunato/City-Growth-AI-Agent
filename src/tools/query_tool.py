"""
query_tool.py - Direct SQL query tool for data exploration

This tool allows the agent to run read-only SQL queries for exploration.
For user-facing analysis and visualizations, use data_analysis_workflow instead.
"""

import asyncio
import re
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from sqlalchemy import text

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db import get_engine

# Maximum rows to return
MAX_ROWS = 100


def _validate_sql(sql: str) -> tuple[bool, str]:
    """Validate that SQL is a safe SELECT query."""
    sql_upper = sql.upper().strip()

    # Must start with SELECT or WITH (for CTEs)
    if not (sql_upper.startswith("SELECT") or sql_upper.startswith("WITH")):
        return False, "Only SELECT queries are allowed. Query must start with SELECT or WITH."

    # Block dangerous keywords
    dangerous = ["INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE", "GRANT", "REVOKE"]
    for keyword in dangerous:
        # Use word boundary matching to avoid false positives
        if re.search(rf'\b{keyword}\b', sql_upper):
            return False, f"Query contains forbidden keyword: {keyword}"

    return True, ""


@tool
async def query_database(sql: str, config: RunnableConfig = None) -> str:
    """Execute a read-only SQL query against the database.

    Use for exploratory queries when you need to understand the data.
    For user-facing analysis or visualizations, use data_analysis_workflow instead.

    CRITICAL RULES:
    - Only SELECT statements allowed (can use CTEs with WITH)
    - Always use qtr = 'A' for annual data
    - Use ILIKE with wildcards for area_title matching
    - Results limited to 100 rows

    Example queries:
    - SELECT DISTINCT year FROM msa_wages_employment_data ORDER BY year
    - SELECT area_title, avg_annual_pay FROM msa_wages_employment_data WHERE area_title ILIKE '%Austin%' AND qtr = 'A' AND year = 2023
    - SELECT COUNT(*) FROM msa_wages_employment_data WHERE qtr = 'A'

    Args:
        sql: The SQL query to execute (SELECT only)
    """
    # Validate SQL
    is_valid, error = _validate_sql(sql)
    if not is_valid:
        return f"SQL Validation Error: {error}"

    def _execute():
        engine = get_engine()

        # Add LIMIT if not present
        sql_modified = sql.strip().rstrip(";")
        if "LIMIT" not in sql_modified.upper():
            sql_modified = f"{sql_modified} LIMIT {MAX_ROWS}"

        try:
            with engine.connect() as conn:
                # Use read-only transaction
                conn.execute(text("SET TRANSACTION READ ONLY"))
                result = conn.execute(text(sql_modified))
                columns = list(result.keys())
                rows = result.fetchall()

                if not rows:
                    return "Query returned no results."

                # Format results
                lines = [f"Query returned {len(rows)} row(s):\n"]
                lines.append(",".join(columns))

                for row in rows:
                    lines.append(",".join(str(v) if v is not None else "NULL" for v in row))

                # Truncate if too long
                result_text = "\n".join(lines)
                if len(result_text) > 5000:
                    result_text = result_text[:5000] + f"\n... (truncated, {len(rows)} total rows)"

                return result_text

        except Exception as e:
            return f"Query Error: {str(e)}"

    return await asyncio.to_thread(_execute)
