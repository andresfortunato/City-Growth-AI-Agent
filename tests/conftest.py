"""
Shared pytest fixtures for SQL agent tests.

This module provides common test fixtures including:
- Mocked LLM responses
- Mocked database connections
- Sample state objects
- Performance measurement utilities
"""

import pytest
from unittest.mock import Mock, MagicMock
from langchain_core.messages import AIMessage, ToolMessage

# Legacy import - sql_agent is deprecated, fixtures below are for old tests
try:
    from sql_agent.state import SQLAgentState
except ImportError:
    SQLAgentState = None


@pytest.fixture
def sample_state():
    """Provide a sample SQLAgentState for testing."""
    return {
        "user_query": "What is the average wage in Austin in 2023?",
        "available_tables": ["msa_wages_employment_data"],
        "table_schema": """
CREATE TABLE msa_wages_employment_data (
    area_fips TEXT,
    year INTEGER,
    qtr TEXT,
    size_code TEXT,
    size_title TEXT,
    annual_avg_estabs_count INTEGER,
    annual_avg_emplvl INTEGER,
    total_annual_wages BIGINT,
    avg_annual_pay INTEGER,
    annual_avg_wkly_wage INTEGER,
    area_title TEXT,
    state TEXT
)
        """.strip(),
        "generated_sql": None,
        "sql_valid": False,
        "validation_error": None,
        "query_results": None,
        "execution_error": None,
        "analysis": "",
        "num_retries": 0,
        "messages": [],
    }


@pytest.fixture
def sample_sql_query():
    """Provide a sample SQL query."""
    return """
SELECT AVG(avg_annual_pay) as average_wage
FROM msa_wages_employment_data
WHERE area_title ILIKE '%Austin%'
  AND year = 2023
  AND qtr = 'A'
LIMIT 100;
    """.strip()


@pytest.fixture
def sample_query_results():
    """Provide sample query results."""
    return [{"average_wage": 68450}]


@pytest.fixture
def mock_llm():
    """Mock ChatGoogleGenerativeAI for testing."""
    mock = MagicMock()
    return mock


@pytest.fixture
def mock_llm_with_tool_call(sample_sql_query):
    """Mock LLM that returns a tool call."""
    mock = MagicMock()
    response = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "sql_db_query",
                "args": {"query": sample_sql_query},
                "id": "call_123",
                "type": "tool_call",
            }
        ],
    )
    mock.invoke.return_value = response
    return mock


@pytest.fixture
def mock_llm_no_tool_call():
    """Mock LLM that returns no tool call (error case)."""
    mock = MagicMock()
    response = AIMessage(
        content="I cannot generate a query for this request.",
        tool_calls=[],
    )
    mock.invoke.return_value = response
    return mock


@pytest.fixture
def mock_db_tools():
    """Mock database tools."""
    list_tables_tool = MagicMock()
    list_tables_tool.name = "sql_db_list_tables"
    list_tables_tool.invoke.return_value = ToolMessage(
        content="msa_wages_employment_data", tool_call_id="list_call"
    )

    schema_tool = MagicMock()
    schema_tool.name = "sql_db_schema"
    schema_tool.invoke.return_value = ToolMessage(
        content="""
CREATE TABLE msa_wages_employment_data (
    area_title TEXT,
    year INTEGER,
    avg_annual_pay INTEGER
)
        """.strip(),
        tool_call_id="schema_call",
    )

    query_tool = MagicMock()
    query_tool.name = "sql_db_query"
    query_tool.invoke.return_value = ToolMessage(
        content='[{"avg": 68450}]', tool_call_id="query_call"
    )

    return [list_tables_tool, schema_tool, query_tool]


@pytest.fixture
def mock_analysis_response():
    """Mock LLM response for analysis."""
    mock = MagicMock()
    response = AIMessage(
        content="In 2023, the average annual pay in the Austin-Round Rock, TX metro area was $68,450."
    )
    mock.invoke.return_value = response
    return mock
