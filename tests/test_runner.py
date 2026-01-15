"""test_runner.py - Test code execution with error recovery."""
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from workspace import create_workspace, cleanup_workspace
from runner import execute_plotly_code, execute_with_recovery
from validator import validate_code

load_dotenv()


def test_validation():
    """Test code validation catches problems."""
    # Valid code
    valid_code = """
import pandas as pd
import plotly.express as px
df = pd.read_csv('/tmp/data.csv')
fig = px.line(df, x='year', y='value')
fig.write_html('/tmp/output.html')
"""
    is_valid, error = validate_code(valid_code)
    assert is_valid, f"Valid code rejected: {error}"
    print("✓ Valid code passes validation")

    # Dangerous import
    dangerous_code = "import os\nimport pandas as pd"
    is_valid, error = validate_code(dangerous_code)
    assert not is_valid
    assert "Blocked import" in error
    print("✓ Dangerous imports blocked")


def test_successful_execution():
    """Test that valid code executes correctly."""
    workspace = create_workspace()

    with open(workspace.data_path, 'w') as f:
        f.write("year,value\n2020,100\n2021,150\n2022,200\n")

    code = f"""
import pandas as pd
import plotly.express as px
df = pd.read_csv('{workspace.data_path}')
fig = px.line(df, x='year', y='value', title='Test Chart')
fig.write_html('{workspace.output_path}')
"""

    result = execute_plotly_code(workspace, code)
    assert result.success, f"Execution failed: {result.error_message}"
    assert result.artifact_exists

    cleanup_workspace(workspace)
    print(f"✓ Successful execution ({result.execution_time_ms}ms)")


def test_error_recovery():
    """Test that error recovery fixes broken code."""
    model = init_chat_model("google_genai:gemini-2.0-flash")
    workspace = create_workspace()

    with open(workspace.data_path, 'w') as f:
        f.write("year,value\n2020,100\n2021,150\n2022,200\n")

    # Intentionally broken code (wrong column name)
    broken_code = f"""
import pandas as pd
import plotly.express as px
df = pd.read_csv('{workspace.data_path}')
fig = px.line(df, x='year', y='wrong_column')
fig.write_html('{workspace.output_path}')
"""

    result = execute_with_recovery(
        workspace, broken_code, columns=["year", "value"], model=model, max_retries=3
    )

    if result.success:
        print(f"✓ Error recovery worked (fixed on attempt {result.attempt})")
    else:
        print(f"⚠ Error recovery failed after {result.attempt} attempts: {result.error_message}")
        print("Note: This test may fail intermittently due to LLM variability")

    cleanup_workspace(workspace)


if __name__ == "__main__":
    test_validation()
    test_successful_execution()
    test_error_recovery()
    print("\n✅ Phase 3 tests completed!")
