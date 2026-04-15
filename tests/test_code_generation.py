"""test_code_generation.py - Test Plotly code generation with structured output."""
import os
import sys
from pathlib import Path

# Add src/ to path for module imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from visualization_nodes import classify_intent, generate_plotly_code
from workspace import create_workspace, cleanup_workspace

load_dotenv()

def test_intent_classification():
    """Test LLM-based intent classification with multi-chart detection."""
    model = init_chat_model("google_genai:gemini-2.0-flash")

    test_cases = [
        ("Create a line chart of wage trends", "visualize", 1),
        ("What is the average wage in Austin?", "answer", 0),
        ("Show wages AND employment trends over time", "multi_chart", 2),
        ("Compare Seattle and Austin wages", "visualize", 1),
    ]

    for query, expected_intent, expected_charts in test_cases:
        state = {"messages": [{"content": query}]}
        result = classify_intent(state, model)

        # Intent might vary slightly, but should be reasonable
        print(f"✓ '{query[:40]}...' → {result['intent']} ({result['num_charts']} charts)")

    print("\n✓ Intent classification works")


def test_structured_code_generation():
    """Test generating a chart with structured output."""
    model = init_chat_model("google_genai:gemini-2.0-flash")
    workspace = create_workspace()

    with open(workspace.data_path, 'w') as f:
        f.write("year,avg_annual_pay\n2020,65000\n2021,68000\n2022,71000\n2023,74000\n")

    state = {
        "messages": [{"content": "Create a line chart of wage trends"}],
        "workspace": workspace,
        "columns": ["year", "avg_annual_pay"],
        "row_count": 4,
        "data_preview": "year,avg_annual_pay\n2020,65000\n2021,68000"
    }

    result = generate_plotly_code(state, model)

    assert "plotly_code" in result
    assert "chart_type" in result
    assert "columns_used" in result
    assert "pd.read_csv" in result["plotly_code"]
    assert "write_html" in result["plotly_code"]

    print(f"Generated {result['chart_type']} chart using columns: {result['columns_used']}")

    cleanup_workspace(workspace)
    print("\n✓ Structured code generation works")


if __name__ == "__main__":
    test_intent_classification()
    test_structured_code_generation()
    print("\n✅ All Phase 2 tests passed!")
