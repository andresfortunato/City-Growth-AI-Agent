"""Test the data handoff mechanism."""
import os
import sys
from pathlib import Path

# Add src/ to path for module imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv
from sqlalchemy import create_engine
from langchain_community.utilities import SQLDatabase
from sql_tools import execute_query_with_handoff
from workspace import create_workspace, cleanup_workspace

load_dotenv()

def get_test_db():
    """Create test database connection."""
    db_uri = f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    engine = create_engine(db_uri)
    return SQLDatabase(engine)

def test_small_result_answer_mode():
    """Small results should return data in context."""
    db = get_test_db()
    result = execute_query_with_handoff(
        db,
        "SELECT year, avg_annual_pay FROM msa_wages_employment_data WHERE area_title ILIKE '%Austin%' AND qtr = 'A' LIMIT 5",
        intent="answer"
    )

    assert result["success"]
    assert result["row_count"] > 0, f"Expected > 0 rows, got {result['row_count']}"
    assert result["row_count"] <= 5, f"Expected <= 5 rows, got {result['row_count']}"
    assert result["workspace"] is None
    assert "execution_time_ms" in result
    print(f"✓ Small result answer mode works ({result['row_count']} rows in {result['execution_time_ms']}ms)")

def test_large_result_visualize_mode():
    """Large results should save to CSV."""
    db = get_test_db()
    result = execute_query_with_handoff(
        db,
        "SELECT year, area_title, avg_annual_pay FROM msa_wages_employment_data WHERE qtr = 'A'",
        intent="visualize"
    )

    assert result["success"]
    assert result["row_count"] > 100
    assert result["workspace"] is not None
    assert result["workspace"].data_path.exists()

    import csv
    with open(result["workspace"].data_path) as f:
        reader = csv.DictReader(f)
        row = next(reader)
        assert "year" in row
        assert "area_title" in row

    cleanup_workspace(result["workspace"])
    print(f"✓ Large result visualize mode works ({result['row_count']} rows in {result['execution_time_ms']}ms)")

def test_workspace_lifecycle():
    """Test workspace creation and cleanup."""
    workspace = create_workspace()

    assert workspace.path.exists()
    assert workspace.job_id is not None

    with open(workspace.data_path, 'w') as f:
        f.write("test,data\n1,2")

    assert workspace.data_path.exists()

    workspace.record_timing("test_phase", 100)
    assert workspace.timings["test_phase"] == 100

    cleanup_workspace(workspace)
    assert not workspace.path.exists()
    print("✓ Workspace lifecycle works")

if __name__ == "__main__":
    test_workspace_lifecycle()
    test_small_result_answer_mode()
    test_large_result_visualize_mode()
    print("\n✅ All Phase 1 tests passed!")
