"""
schema_tools.py - Tools for exploring database schema and data

These tools help the agent understand what data is available before
running analysis or generating visualizations.
"""

import asyncio
import os
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

# Database schema documentation (hardcoded for performance)
SCHEMA_DOC = """
Table: msa_wages_employment_data
Description: QCEW (Quarterly Census of Employment and Wages) data for Metropolitan Statistical Areas

Columns:
- area_fips (text): FIPS code for the area
- year (integer): Year of data, range 2001-2024
- qtr (text): Quarter - 'A' for annual aggregates, '1'-'4' for quarterly
- annual_avg_estabs_count (integer): Average number of establishments
- annual_avg_emplvl (integer): Average employment level (number of jobs)
- total_annual_wages (bigint): Total wages paid in the year
- avg_annual_pay (integer): Average annual pay per worker
- annual_avg_wkly_wage (integer): Average weekly wage
- area_title (text): Full MSA name (e.g., "Austin-Round Rock-Georgetown, TX")
- state (text): Primary 2-letter state code (e.g., 'TX', 'CA')

Important Notes:
- Always use qtr = 'A' for annual data (most common use case)
- area_title requires ILIKE with wildcards for matching (e.g., area_title ILIKE '%Austin%')
- state uses exact 2-letter codes (e.g., state = 'TX')
- Data covers ~400 MSAs across the United States
"""


def _get_db_engine():
    """Get database engine using environment variables."""
    DB_USER = os.getenv("DB_USER", "city_growth_postgres")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "CityGrowthDiagnostics2026")
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = os.getenv("DB_PORT", "5432")
    DB_NAME = os.getenv("DB_NAME", "postgres")

    db_uri = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    return create_engine(db_uri)


@tool
async def get_schema(table_name: str = "msa_wages_employment_data", config: RunnableConfig = None) -> str:
    """Get the schema (columns, types, descriptions) for a database table.

    Use this when you need to understand what data is available before writing queries.
    Returns column names, data types, and descriptions.

    Args:
        table_name: Name of the table to inspect (default: msa_wages_employment_data)
    """
    # For now, return hardcoded schema for the known table
    # This is faster and more reliable than querying information_schema
    if table_name == "msa_wages_employment_data":
        return SCHEMA_DOC

    # For other tables, query the information schema
    def _query_schema():
        engine = _get_db_engine()
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = :table_name
                ORDER BY ordinal_position
            """), {"table_name": table_name})
            rows = result.fetchall()

            if not rows:
                return f"Table '{table_name}' not found. Available table: msa_wages_employment_data"

            lines = [f"Table: {table_name}\n\nColumns:"]
            for col_name, data_type, nullable in rows:
                null_str = "" if nullable == "YES" else " (NOT NULL)"
                lines.append(f"- {col_name} ({data_type}){null_str}")

            return "\n".join(lines)

    return await asyncio.to_thread(_query_schema)


@tool
async def sample_data(table_name: str = "msa_wages_employment_data", n_rows: int = 5, config: RunnableConfig = None) -> str:
    """Get sample rows from a table to understand the data format.

    Use this to see what actual values look like (city names, year ranges, etc.)
    Do NOT use for analysis - use data_analysis_workflow for that.

    Args:
        table_name: Table to sample from (default: msa_wages_employment_data)
        n_rows: Number of rows to return (max 10)
    """
    n_rows = min(max(n_rows, 1), 10)

    def _sample():
        engine = _get_db_engine()
        with engine.connect() as conn:
            # For the main table, get a diverse sample (different cities, recent years)
            if table_name == "msa_wages_employment_data":
                result = conn.execute(text("""
                    SELECT area_title, year, annual_avg_emplvl, avg_annual_pay, state
                    FROM msa_wages_employment_data
                    WHERE qtr = 'A' AND year >= 2020
                    ORDER BY RANDOM()
                    LIMIT :n_rows
                """), {"n_rows": n_rows})
            else:
                result = conn.execute(text(f"""
                    SELECT * FROM {table_name} LIMIT :n_rows
                """), {"n_rows": n_rows})

            columns = list(result.keys())
            rows = result.fetchall()

            if not rows:
                return f"No data found in table '{table_name}'"

            # Format as readable table
            lines = [",".join(columns)]
            for row in rows:
                lines.append(",".join(str(v) for v in row))

            return f"Sample data from {table_name} ({len(rows)} rows):\n\n" + "\n".join(lines)

    return await asyncio.to_thread(_sample)


@tool
async def list_cities(state_filter: str = None, config: RunnableConfig = None) -> str:
    """List available cities (MSAs) in the database.

    Use this when user asks about available cities or you need to resolve city names.
    Can filter by state code (e.g., 'TX' for Texas).

    Args:
        state_filter: Optional 2-letter state code to filter results (e.g., 'TX', 'CA')
    """
    def _list():
        engine = _get_db_engine()
        with engine.connect() as conn:
            if state_filter:
                result = conn.execute(text("""
                    SELECT DISTINCT area_title, state
                    FROM msa_wages_employment_data
                    WHERE state = :state_filter AND qtr = 'A'
                    ORDER BY area_title
                """), {"state_filter": state_filter.upper()})
            else:
                # Without filter, return count by state for overview
                result = conn.execute(text("""
                    SELECT state, COUNT(DISTINCT area_title) as msa_count
                    FROM msa_wages_employment_data
                    WHERE qtr = 'A'
                    GROUP BY state
                    ORDER BY msa_count DESC
                """))

            rows = result.fetchall()

            if not rows:
                if state_filter:
                    return f"No MSAs found for state '{state_filter}'. Use a 2-letter state code."
                return "No data found."

            if state_filter:
                lines = [f"MSAs in {state_filter.upper()} ({len(rows)} total):"]
                for area_title, state in rows:
                    lines.append(f"- {area_title}")
                return "\n".join(lines)
            else:
                lines = ["MSA count by state (top states shown):"]
                for state, count in rows[:15]:
                    lines.append(f"- {state}: {count} MSAs")
                total = sum(count for _, count in rows)
                lines.append(f"\nTotal: {total} MSAs across {len(rows)} states")
                lines.append("\nUse list_cities(state_filter='XX') to see MSAs in a specific state.")
                return "\n".join(lines)

    return await asyncio.to_thread(_list)
