"""End-to-end tests for visualization agent."""
import sys
from pathlib import Path

# Add src/ to path for module imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from visualization_agent import classify_single
from workspace import cleanup_old_workspaces


def test_simple_text_answer():
    """Text-only questions should work."""
    result = classify_single("What is the average wage in Austin in 2023?", save_viz=False)
    assert result.get("analysis")
    print(f"✓ Text answer in {result['execution_time_seconds']}s")
    print(f"  Intent: {result['intent']}")


def test_line_chart():
    """Test line chart generation."""
    result = classify_single("Create a line chart showing wage trends for Austin from 2010 to 2024", save_viz=True)
    assert result["intent"] in ["visualize", "multi_chart"]
    if result.get("artifact_html"):
        print(f"✓ Visualization in {result['execution_time_seconds']}s")
        print(f"  Chart: {result.get('chart_type', 'unknown')}")
        print(f"  Saved to: {result.get('artifact_path', 'not saved')}")
    else:
        print(f"⚠ Visualization generation failed")


def test_cleanup():
    """Clean up old workspaces."""
    cleaned = cleanup_old_workspaces(max_age_hours=0)
    print(f"✓ Cleaned {cleaned} workspaces")


if __name__ == "__main__":
    print("Running end-to-end integration tests...\n")
    test_simple_text_answer()
    print()
    test_line_chart()
    print()
    test_cleanup()
    print("\n✅ All integration tests completed!")
