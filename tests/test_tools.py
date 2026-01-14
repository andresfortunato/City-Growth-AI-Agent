"""
Unit tests for SQL agent database tools.

Tests database connection setup and tool creation.

Run with: pytest tests/test_tools.py -v
"""

import pytest
from unittest.mock import patch, MagicMock, Mock
import os


class TestDatabaseConnection:
    """Test database URI construction and connection."""

    def test_get_db_uri_from_env(self):
        """Test database URI construction from environment variables."""
        with patch.dict(os.environ, {
            "DB_USER": "test_user",
            "DB_PASSWORD": "test_pass",
            "DB_HOST": "testhost",
            "DB_PORT": "5433",
            "DB_NAME": "testdb"
        }):
            from sql_agent.tools import get_db_uri

            uri = get_db_uri()

            assert uri == "postgresql://test_user:test_pass@testhost:5433/testdb"

    def test_get_db_uri_defaults(self):
        """Test database URI construction with default values."""
        # Clear environment variables
        with patch.dict(os.environ, {}, clear=True):
            from sql_agent.tools import get_db_uri

            uri = get_db_uri()

            # Should use default values
            assert "city_growth_postgres" in uri
            assert "localhost" in uri
            assert "5432" in uri
            assert "postgres" in uri

    def test_get_db_uri_partial_env(self):
        """Test database URI with some env vars set."""
        with patch.dict(os.environ, {
            "DB_USER": "custom_user",
            "DB_PASSWORD": "custom_pass"
            # DB_HOST, DB_PORT, DB_NAME should use defaults
        }, clear=True):
            from sql_agent.tools import get_db_uri

            uri = get_db_uri()

            assert "custom_user" in uri
            assert "custom_pass" in uri
            assert "localhost" in uri
            assert "5432" in uri


class TestToolCreation:
    """Test creation of LangChain SQL tools."""

    @patch('sql_agent.tools.create_engine')
    @patch('sql_agent.tools.SQLDatabase')
    def test_create_tools_success(self, mock_sqldb, mock_engine):
        """Test successful tool creation."""
        # Mock the database and engine
        mock_db_instance = MagicMock()
        mock_sqldb.return_value = mock_db_instance
        mock_engine_instance = MagicMock()
        mock_engine.return_value = mock_engine_instance

        from sql_agent.tools import create_tools

        tools = create_tools()

        # Verify tools were created
        assert len(tools) == 3

        # Verify engine was created with correct URI
        mock_engine.assert_called_once()
        call_args = str(mock_engine.call_args)
        assert "postgresql://" in call_args

        # Verify SQLDatabase wrapper was created
        mock_sqldb.assert_called_once_with(mock_engine_instance)

    @patch('sql_agent.tools.create_engine')
    @patch('sql_agent.tools.SQLDatabase')
    def test_tools_have_correct_types(self, mock_sqldb, mock_engine):
        """Test that created tools are of correct types."""
        mock_db_instance = MagicMock()
        mock_sqldb.return_value = mock_db_instance
        mock_engine_instance = MagicMock()
        mock_engine.return_value = mock_engine_instance

        from sql_agent.tools import create_tools
        from langchain_community.tools.sql_database.tool import (
            QuerySQLDataBaseTool,
            InfoSQLDatabaseTool,
            ListSQLDatabaseTool,
        )

        tools = create_tools()

        # Check tool types
        assert isinstance(tools[0], ListSQLDatabaseTool)
        assert isinstance(tools[1], InfoSQLDatabaseTool)
        assert isinstance(tools[2], QuerySQLDataBaseTool)

    @patch('sql_agent.tools.create_engine')
    def test_create_tools_connection_error(self, mock_engine):
        """Test handling of database connection errors."""
        # Simulate connection error
        mock_engine.side_effect = Exception("Connection refused")

        from sql_agent.tools import create_tools

        with pytest.raises(Exception) as exc_info:
            create_tools()

        assert "Connection refused" in str(exc_info.value)


class TestToolsModuleImport:
    """Test that tools module can be imported and tools are initialized."""

    def test_tools_module_exports_tools_list(self):
        """Test that tools list is available on import."""
        from sql_agent import tools as tools_module

        assert hasattr(tools_module, 'tools')
        assert isinstance(tools_module.tools, list)

    def test_tools_list_has_expected_names(self):
        """Test that tools have expected names."""
        from sql_agent.tools import tools

        tool_names = [tool.name for tool in tools]

        assert "sql_db_list_tables" in tool_names
        assert "sql_db_schema" in tool_names
        assert "sql_db_query" in tool_names

    def test_tools_list_length(self):
        """Test that we have exactly 3 tools."""
        from sql_agent.tools import tools

        assert len(tools) == 3


# Integration test markers
class TestDatabaseIntegration:
    """Integration tests with actual database (requires DB connection)."""

    @pytest.mark.integration
    @pytest.mark.skipif(
        not os.getenv("DB_USER") or not os.getenv("DB_PASSWORD"),
        reason="Database credentials not set"
    )
    def test_list_tables_with_real_db(self):
        """Test listing tables with real database connection."""
        from sql_agent.tools import tools

        list_tables_tool = next(
            tool for tool in tools if tool.name == "sql_db_list_tables"
        )

        # Invoke the tool
        tool_call = {
            "name": "sql_db_list_tables",
            "args": {},
            "id": "test_call",
            "type": "tool_call",
        }

        result = list_tables_tool.invoke(tool_call)

        # Verify we got table names back
        assert result.content is not None
        assert len(result.content) > 0
        # Should contain our MSA data table
        assert "msa_wages_employment_data" in result.content

    @pytest.mark.integration
    @pytest.mark.skipif(
        not os.getenv("DB_USER") or not os.getenv("DB_PASSWORD"),
        reason="Database credentials not set"
    )
    def test_get_schema_with_real_db(self):
        """Test fetching schema with real database connection."""
        from sql_agent.tools import tools

        schema_tool = next(
            tool for tool in tools if tool.name == "sql_db_schema"
        )

        # Invoke the tool
        tool_call = {
            "name": "sql_db_schema",
            "args": {"table_names": "msa_wages_employment_data"},
            "id": "test_call",
            "type": "tool_call",
        }

        result = schema_tool.invoke(tool_call)

        # Verify we got schema information
        assert result.content is not None
        assert "msa_wages_employment_data" in result.content
        # Should contain column names
        assert "area_title" in result.content.lower()
        assert "year" in result.content.lower()
        assert "avg_annual_pay" in result.content.lower()

    @pytest.mark.integration
    @pytest.mark.skipif(
        not os.getenv("DB_USER") or not os.getenv("DB_PASSWORD"),
        reason="Database credentials not set"
    )
    def test_execute_query_with_real_db(self):
        """Test executing query with real database connection."""
        from sql_agent.tools import tools

        query_tool = next(
            tool for tool in tools if tool.name == "sql_db_query"
        )

        # Invoke the tool with a simple count query
        tool_call = {
            "name": "sql_db_query",
            "args": {"query": "SELECT COUNT(*) FROM msa_wages_employment_data LIMIT 1;"},
            "id": "test_call",
            "type": "tool_call",
        }

        result = query_tool.invoke(tool_call)

        # Verify we got results
        assert result.content is not None
        assert len(result.content) > 0
        # Should contain a number (count result)
        assert any(char.isdigit() for char in result.content)


# Mark unit tests
pytestmark = pytest.mark.unit
