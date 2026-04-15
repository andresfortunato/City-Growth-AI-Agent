"""
Tests for the conversational agent.

These tests verify the ReAct agent, tools, and conversation interface work correctly.
"""

import pytest
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestToolImports:
    """Test that all tools can be imported and have correct structure."""

    def test_import_all_tools(self):
        """All tools should import without errors."""
        from tools import get_all_tools, get_schema, sample_data, list_cities, query_database, data_analysis_workflow

        tools = get_all_tools()
        assert len(tools) == 5

    def test_tools_have_names_and_descriptions(self):
        """Each tool should have a name and description."""
        from tools import get_all_tools

        for tool in get_all_tools():
            assert hasattr(tool, "name")
            assert hasattr(tool, "description")
            assert len(tool.name) > 0
            assert len(tool.description) > 0


class TestAgentImports:
    """Test that the agent module can be imported."""

    def test_import_agent(self):
        """Agent module should import without errors."""
        from agent import create_conversational_agent, get_agent, SYSTEM_PROMPT

        assert len(SYSTEM_PROMPT) > 100

    def test_import_conversation(self):
        """Conversation module should import without errors."""
        from conversation import chat, chat_sync

        assert callable(chat)
        assert callable(chat_sync)


@pytest.mark.asyncio
class TestSchemaTools:
    """Test the schema exploration tools."""

    async def test_get_schema_returns_documentation(self):
        """get_schema should return schema documentation."""
        from tools import get_schema

        result = await get_schema.ainvoke({"table_name": "msa_wages_employment_data"})

        assert "msa_wages_employment_data" in result
        assert "annual_avg_emplvl" in result
        assert "avg_annual_pay" in result

    async def test_list_cities_with_state_filter(self):
        """list_cities should filter by state."""
        from tools import list_cities

        result = await list_cities.ainvoke({"state_filter": "TX"})

        assert "TX" in result
        assert "Austin" in result

    async def test_list_cities_without_filter(self):
        """list_cities should return overview without filter."""
        from tools import list_cities

        result = await list_cities.ainvoke({})

        assert "MSA count by state" in result

    async def test_sample_data_returns_rows(self):
        """sample_data should return sample rows."""
        from tools import sample_data

        result = await sample_data.ainvoke({"n_rows": 3})

        assert "Sample data" in result
        assert "3 rows" in result


@pytest.mark.asyncio
class TestQueryTool:
    """Test the direct SQL query tool."""

    async def test_query_database_select(self):
        """query_database should execute SELECT queries."""
        from tools import query_database

        result = await query_database.ainvoke({
            "sql": "SELECT DISTINCT year FROM msa_wages_employment_data WHERE qtr = 'A' ORDER BY year DESC LIMIT 3"
        })

        assert "year" in result
        assert "row(s)" in result

    async def test_query_database_rejects_insert(self):
        """query_database should reject INSERT statements."""
        from tools import query_database

        result = await query_database.ainvoke({
            "sql": "INSERT INTO msa_wages_employment_data VALUES (1,2,3)"
        })

        assert "Validation Error" in result or "forbidden" in result.lower()

    async def test_query_database_rejects_delete(self):
        """query_database should reject DELETE statements."""
        from tools import query_database

        result = await query_database.ainvoke({
            "sql": "DELETE FROM msa_wages_employment_data"
        })

        assert "Validation Error" in result or "forbidden" in result.lower()


@pytest.mark.asyncio
@pytest.mark.slow
class TestConversation:
    """Test the conversation interface (requires LLM calls)."""

    async def test_simple_greeting(self):
        """Agent should respond to greetings without using tools."""
        from conversation import chat

        result = await chat("Hello!")

        assert "response" in result
        assert "thread_id" in result
        assert len(result["response"]) > 0

    async def test_schema_question_uses_tool(self):
        """Agent should use get_schema for schema questions."""
        from conversation import chat

        result = await chat("What columns are in the database?")

        assert any(tc["tool"] == "get_schema" for tc in result["tool_calls"])

    async def test_city_question_uses_list_cities(self):
        """Agent should use list_cities for city questions."""
        from conversation import chat

        result = await chat("What cities are available in California?")

        assert any(tc["tool"] == "list_cities" for tc in result["tool_calls"])

    async def test_conversation_returns_thread_id(self):
        """Conversation should return a thread_id for continuity."""
        from conversation import chat

        result = await chat("Hello")

        assert "thread_id" in result
        assert len(result["thread_id"]) == 8  # UUID hex[:8]


@pytest.mark.asyncio
@pytest.mark.slow
class TestWorkflowTool:
    """Test the data_analysis_workflow tool (requires LLM + DB)."""

    async def test_workflow_answers_question(self):
        """Workflow should answer data questions."""
        from conversation import chat

        result = await chat("What is the average wage in Austin in 2023?")

        # Should use the workflow tool
        assert any(tc["tool"] == "data_analysis_workflow" for tc in result["tool_calls"])
        # Should return a numeric answer
        assert "$" in result["response"] or "wage" in result["response"].lower()
