"""
Unit tests for SQL agent nodes.

Tests each node function in isolation with mocked dependencies.
Verifies state transformations, error handling, and routing logic.

Run with: pytest tests/test_nodes.py -v
"""

import pytest
from unittest.mock import patch, MagicMock, Mock
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END

from sql_agent.nodes import (
    generate_query,
    check_query,
    run_query,
    analyze_results,
    should_continue,
)


@pytest.fixture
def sample_state():
    """Provide a sample SQLAgentState for testing."""
    return {
        "user_query": "What is the average wage in Austin in 2023?",
        "available_tables": [],
        "table_schema": "",
        "generated_sql": None,
        "sql_valid": False,
        "validation_error": None,
        "query_results": None,
        "execution_error": None,
        "analysis": "",
        "num_retries": 0,
        "messages": [],
    }


class TestGenerateQuery:
    """Test the generate_query node."""

    def test_generate_query_success(self, sample_state):
        """Test successful SQL query generation."""
        # Create mock LLM with tool call
        mock_llm = MagicMock()
        mock_response = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "sql_db_query",
                    "args": {"query": "SELECT AVG(avg_annual_pay) FROM msa_wages_employment_data WHERE area_title ILIKE '%Austin%' AND year = 2023 AND qtr = 'A' LIMIT 100;"},
                    "id": "call_123",
                }
            ],
        )
        mock_llm.bind_tools.return_value.invoke.return_value = mock_response

        # Mock tools
        mock_tool = MagicMock()
        mock_tool.name = "sql_db_query"

        with patch("sql_agent.nodes.llm", mock_llm):
            with patch("sql_agent.nodes.tools", [mock_tool]):
                result = generate_query(sample_state)

                # Verify state updates
                assert "generated_sql" in result
                assert "SELECT" in result["generated_sql"].upper()
                assert "avg_annual_pay" in result["generated_sql"].lower()
                assert "messages" in result
                assert len(result["messages"]) > 0

    def test_generate_query_no_tool_call(self, sample_state):
        """Test query generation when LLM doesn't return tool call."""
        mock_llm = MagicMock()
        mock_response = AIMessage(
            content="I cannot generate a query for this request.",
            tool_calls=[]
        )
        mock_llm.bind_tools.return_value.invoke.return_value = mock_response

        mock_tool = MagicMock()
        mock_tool.name = "sql_db_query"

        with patch("sql_agent.nodes.llm", mock_llm):
            with patch("sql_agent.nodes.tools", [mock_tool]):
                result = generate_query(sample_state)

                # Verify error handling
                assert result["generated_sql"] is None
                assert "execution_error" in result
                assert "did not generate a tool call" in result["execution_error"]

    def test_generate_query_with_retry_context(self, sample_state):
        """Test query generation includes retry context on failure."""
        sample_state["validation_error"] = "Column 'invalid_col' does not exist"

        mock_llm = MagicMock()
        mock_response = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "sql_db_query",
                    "args": {"query": "SELECT * FROM table"},
                    "id": "call_123",
                }
            ],
        )
        mock_llm.bind_tools.return_value.invoke.return_value = mock_response

        mock_tool = MagicMock()
        mock_tool.name = "sql_db_query"

        with patch("sql_agent.nodes.llm", mock_llm):
            with patch("sql_agent.nodes.tools", [mock_tool]):
                result = generate_query(sample_state)

                # Verify retry context was passed to LLM
                call_args = mock_llm.bind_tools.return_value.invoke.call_args[0][0]
                assert len(call_args) > 2  # Should have system, user, and retry message
                # Check that error context was included
                has_retry_context = any(
                    "Previous attempt failed" in str(msg)
                    for msg in call_args
                )
                assert has_retry_context, "Should include retry context in messages"


class TestCheckQuery:
    """Test the check_query node."""

    def test_check_query_valid_unchanged(self, sample_state):
        """Test query validation passes without changes."""
        sample_state["generated_sql"] = "SELECT * FROM msa_wages_employment_data LIMIT 100"

        mock_llm = MagicMock()
        mock_response = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "sql_db_query",
                    "args": {"query": "SELECT * FROM msa_wages_employment_data LIMIT 100"},
                    "id": "call_123",
                }
            ],
        )
        mock_llm.bind_tools.return_value.invoke.return_value = mock_response

        mock_tool = MagicMock()
        mock_tool.name = "sql_db_query"

        with patch("sql_agent.nodes.llm", mock_llm):
            with patch("sql_agent.nodes.tools", [mock_tool]):
                result = check_query(sample_state)

                # Verify validation passed without changes
                assert result["sql_valid"] is True
                assert result["generated_sql"] == "SELECT * FROM msa_wages_employment_data LIMIT 100"
                assert result.get("validation_error") is None

    def test_check_query_rewritten(self, sample_state):
        """Test query is rewritten by validator."""
        sample_state["generated_sql"] = "SELECT * FROM msa_wages_employment_data"

        mock_llm = MagicMock()
        mock_response = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "sql_db_query",
                    "args": {"query": "SELECT * FROM msa_wages_employment_data LIMIT 100"},
                    "id": "call_123",
                }
            ],
        )
        mock_llm.bind_tools.return_value.invoke.return_value = mock_response

        mock_tool = MagicMock()
        mock_tool.name = "sql_db_query"

        with patch("sql_agent.nodes.llm", mock_llm):
            with patch("sql_agent.nodes.tools", [mock_tool]):
                result = check_query(sample_state)

                # Verify query was rewritten
                assert result["sql_valid"] is True
                assert "LIMIT 100" in result["generated_sql"]
                assert result["validation_error"] is not None
                assert "rewritten" in result["validation_error"].lower()

    def test_check_query_no_sql(self, sample_state):
        """Test validation when no SQL query exists."""
        result = check_query(sample_state)

        assert result["sql_valid"] is False
        assert "No SQL query to validate" in result["validation_error"]

    def test_check_query_validator_fails(self, sample_state):
        """Test when validator doesn't produce valid output."""
        sample_state["generated_sql"] = "SELECT * FROM table"

        mock_llm = MagicMock()
        mock_response = AIMessage(
            content="This query has errors",
            tool_calls=[]
        )
        mock_llm.bind_tools.return_value.invoke.return_value = mock_response

        mock_tool = MagicMock()
        mock_tool.name = "sql_db_query"

        with patch("sql_agent.nodes.llm", mock_llm):
            with patch("sql_agent.nodes.tools", [mock_tool]):
                result = check_query(sample_state)

                # Verify validation failed
                assert result["sql_valid"] is False
                assert "did not produce valid output" in result["validation_error"]


class TestRunQuery:
    """Test the run_query node."""

    def test_run_query_success_with_tool_call(self, sample_state):
        """Test successful query execution from tool call in messages."""
        sample_state["generated_sql"] = "SELECT COUNT(*) FROM msa_wages_employment_data"
        sample_state["messages"] = [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "sql_db_query",
                        "args": {"query": "SELECT COUNT(*) FROM msa_wages_employment_data"},
                        "id": "call_123",
                        "type": "tool_call",
                    }
                ],
            )
        ]

        # Mock the query tool
        mock_tool = MagicMock()
        mock_tool.name = "sql_db_query"
        mock_tool.invoke.return_value = ToolMessage(
            content="[(10847,)]",
            tool_call_id="call_123"
        )

        with patch("sql_agent.nodes.tools", [mock_tool]):
            result = run_query(sample_state)

            # Verify results were extracted
            assert "query_results" in result
            assert result["query_results"] is not None
            assert len(result["query_results"]) > 0
            assert "count" in result["query_results"][0] or "col_0" in result["query_results"][0]

    def test_run_query_success_json_format(self, sample_state):
        """Test query execution with JSON formatted results."""
        sample_state["generated_sql"] = "SELECT AVG(avg_annual_pay) as avg FROM msa_wages_employment_data"
        sample_state["messages"] = []

        # Mock the query tool returning JSON
        mock_tool = MagicMock()
        mock_tool.name = "sql_db_query"
        mock_tool.invoke.return_value = ToolMessage(
            content='[{"avg": 68450}]',
            tool_call_id="call_123"
        )

        with patch("sql_agent.nodes.tools", [mock_tool]):
            result = run_query(sample_state)

            # Verify JSON parsing worked
            assert result["query_results"] is not None
            assert len(result["query_results"]) == 1
            assert result["query_results"][0]["avg"] == 68450

    def test_run_query_empty_results(self, sample_state):
        """Test query execution with no results."""
        sample_state["generated_sql"] = "SELECT * FROM msa_wages_employment_data WHERE 1=0"
        sample_state["messages"] = []

        mock_tool = MagicMock()
        mock_tool.name = "sql_db_query"
        mock_tool.invoke.return_value = ToolMessage(
            content="[]",
            tool_call_id="call_123"
        )

        with patch("sql_agent.nodes.tools", [mock_tool]):
            result = run_query(sample_state)

            assert result["query_results"] == []

    def test_run_query_execution_error(self, sample_state):
        """Test query execution failure."""
        sample_state["generated_sql"] = "SELECT invalid_column FROM msa_wages_employment_data"
        sample_state["messages"] = []

        mock_tool = MagicMock()
        mock_tool.name = "sql_db_query"
        mock_tool.invoke.side_effect = Exception("column 'invalid_column' does not exist")

        with patch("sql_agent.nodes.tools", [mock_tool]):
            result = run_query(sample_state)

            # Verify error handling
            assert result["query_results"] == []
            assert "execution_error" in result
            assert "invalid_column" in result["execution_error"]

    def test_run_query_no_tool_call(self, sample_state):
        """Test run_query when no tool call exists."""
        sample_state["messages"] = []
        sample_state["generated_sql"] = None

        result = run_query(sample_state)

        assert result["query_results"] == []
        assert "No SQL query found to execute" in result["execution_error"]


class TestAnalyzeResults:
    """Test the analyze_results node."""

    def test_analyze_results_with_data(self, sample_state):
        """Test analysis of query results."""
        sample_state["query_results"] = [{"average_wage": 68450}]
        sample_state["generated_sql"] = "SELECT AVG(avg_annual_pay) as average_wage FROM msa_wages_employment_data WHERE area_title ILIKE '%Austin%' AND year = 2023"

        mock_llm = MagicMock()
        mock_response = AIMessage(
            content="The average wage in Austin in 2023 was $68,450."
        )
        mock_llm.invoke.return_value = mock_response

        with patch("sql_agent.nodes.llm", mock_llm):
            result = analyze_results(sample_state)

            # Verify analysis was generated
            assert "analysis" in result
            assert len(result["analysis"]) > 0
            assert "$68,450" in result["analysis"]

    def test_analyze_results_empty_data(self, sample_state):
        """Test analysis when no results found."""
        sample_state["query_results"] = []

        result = analyze_results(sample_state)

        # Verify helpful message for empty results
        assert "No data found" in result["analysis"]
        assert "misspelled" in result["analysis"] or "filter" in result["analysis"]

    def test_analyze_results_none_data(self, sample_state):
        """Test analysis when query_results is None."""
        sample_state["query_results"] = None

        result = analyze_results(sample_state)

        # Should handle None gracefully
        assert "No data found" in result["analysis"]

    def test_analyze_results_large_dataset(self, sample_state):
        """Test analysis limits result size for token efficiency."""
        # Create 100 result rows
        sample_state["query_results"] = [{"year": i, "value": i * 1000} for i in range(100)]
        sample_state["generated_sql"] = "SELECT year, value FROM table"

        mock_llm = MagicMock()
        mock_response = AIMessage(content="Analysis of large dataset")
        mock_llm.invoke.return_value = mock_response

        with patch("sql_agent.nodes.llm", mock_llm):
            result = analyze_results(sample_state)

            # Verify only first 50 rows were passed to LLM
            call_args = mock_llm.invoke.call_args[0][0]
            user_message_content = str(call_args[1]["content"])

            # Should include early rows
            assert "'year': 0" in user_message_content or "'year': 1" in user_message_content
            # Should not include rows beyond 50
            assert "'year': 51" not in user_message_content
            assert "'year': 99" not in user_message_content

    def test_analyze_results_structured_response(self, sample_state):
        """Test handling of structured Gemini response format."""
        sample_state["query_results"] = [{"count": 10847}]
        sample_state["generated_sql"] = "SELECT COUNT(*) as count FROM msa_wages_employment_data"

        # Simulate Gemini's structured response format
        mock_llm = MagicMock()
        mock_response = AIMessage(
            content=[
                {"type": "text", "text": "The table contains 10,847 rows of MSA wage data.", "extras": {}},
            ]
        )
        mock_llm.invoke.return_value = mock_response

        with patch("sql_agent.nodes.llm", mock_llm):
            result = analyze_results(sample_state)

            # Verify text extraction worked
            assert "10,847" in result["analysis"]
            assert "rows" in result["analysis"]


class TestShouldContinue:
    """Test the should_continue routing function."""

    def test_should_continue_with_tool_calls(self, sample_state):
        """Test routing when tool calls are present."""
        message = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "sql_db_query",
                    "args": {"query": "SELECT * FROM table"},
                    "id": "123"
                }
            ],
        )
        sample_state["messages"] = [message]

        result = should_continue(sample_state)

        assert result == "check_query"

    def test_should_continue_no_tool_calls(self, sample_state):
        """Test routing when no tool calls present."""
        message = AIMessage(
            content="Cannot generate query",
            tool_calls=[]
        )
        sample_state["messages"] = [message]

        result = should_continue(sample_state)

        assert result == END

    def test_should_continue_empty_messages(self, sample_state):
        """Test routing with empty message list."""
        sample_state["messages"] = []

        result = should_continue(sample_state)

        assert result == END

    def test_should_continue_no_tool_calls_attribute(self, sample_state):
        """Test routing when message has no tool_calls attribute."""
        # Create a message without tool_calls
        sample_state["messages"] = [{"role": "assistant", "content": "test"}]

        result = should_continue(sample_state)

        assert result == END


# Mark all tests as unit tests
pytestmark = pytest.mark.unit
