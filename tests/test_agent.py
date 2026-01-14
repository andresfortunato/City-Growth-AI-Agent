"""
Integration tests for SQL agent.

Run with: pytest tests/test_agent.py -v
"""

import pytest
from sql_agent.agent import run_agent


def test_basic_count_query():
    """Test simple row count query."""
    result = run_agent("How many rows are in the table?")

    assert result["sql"] is not None, "Should generate SQL"
    assert "SELECT" in result["sql"].upper(), "SQL should contain SELECT"
    assert result["error"] is None, "Should not have errors"
    assert len(result["analysis"]) > 0, "Should have analysis"


def test_msa_specific_query():
    """Test MSA-specific filtering."""
    result = run_agent("What is the average wage in Austin in 2023?")

    assert result["sql"] is not None
    assert "austin" in result["sql"].lower(), "SQL should filter by Austin"
    assert "2023" in result["sql"], "SQL should filter by year 2023"
    assert result["error"] is None


def test_trend_analysis_query():
    """Test time-series queries."""
    result = run_agent("Show wage growth in Austin from 2010 to 2020")

    assert result["sql"] is not None
    assert "order by" in result["sql"].lower(), "Should order results"
    assert result["error"] is None


def test_comparison_query():
    """Test multi-MSA comparison."""
    result = run_agent("Compare Austin and San Francisco wages in 2022")

    sql_lower = result["sql"].lower()
    assert "austin" in sql_lower, "Should include Austin"
    assert "san francisco" in sql_lower, "Should include San Francisco"
    assert result["error"] is None


@pytest.mark.skip(reason="Requires manual verification of error handling")
def test_invalid_query():
    """Test graceful handling of nonsensical queries."""
    result = run_agent("asdfasdf random nonsense query")

    # Should either generate something reasonable or fail gracefully
    assert result["sql"] is not None or result["error"] is not None


def test_employment_query():
    """Test employment-related queries."""
    result = run_agent("What is the employment level in Austin in 2022?")

    assert result["sql"] is not None
    assert "emplvl" in result["sql"].lower() or "employment" in result["sql"].lower()
    assert result["error"] is None


def test_state_level_query():
    """Test state-level filtering."""
    result = run_agent("Which Texas MSAs have the highest wages?")

    sql_lower = result["sql"].lower()
    assert "texas" in sql_lower or "tx" in sql_lower.replace("'", "")
    assert result["error"] is None
