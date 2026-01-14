"""Visualize the HTS Classification Agent workflow graph.

This script generates a visual representation of the LangGraph workflow
and saves it as a PNG image.
"""

from pathlib import Path


def visualize_workflow(graph, output_path: str = "workflow_graph.png"):
    """
    Generate and save a visualization of the workflow graph.

    Args:
        graph: The compiled LangGraph graph
        output_path: Path where the PNG image will be saved
    """
    # Get the graph visualization as PNG bytes
    try:
        png_bytes = graph.get_graph().draw_mermaid_png()

        # Save to file
        output_file = Path(output_path)
        output_file.write_bytes(png_bytes)

    except Exception as e:
        print(f"Error generating visualization: {e}")
        print("\nAlternative: Print ASCII representation")
        try:
            print(graph.get_graph().draw_ascii())
        except Exception as e2:
            print(f"Error generating ASCII: {e2}")


if __name__ == "__main__":
    import sys

    # Import the graph from interactive_workflow_new
    # from interactive_workflow_new import graph
    from simplified_workflow import graph

    # Default output path
    output_path = "simplified_graph.png"

    # Allow custom output path from command line
    if len(sys.argv) > 1:
        output_path = sys.argv[1]

    # Generate visualization
    print("\nGenerating visualization...")
    visualize_workflow(graph, output_path)
