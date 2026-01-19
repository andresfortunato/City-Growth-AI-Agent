#!/usr/bin/env python3
"""
visualization_agent.py - Enhanced agent with visualization capability

Features:
1. LLM-driven intent classification with multi-chart detection
2. Data handoff (CSV file passing)
3. Structured output with Pydantic
4. Error recovery loop for code execution
5. Connection pooling for production
6. Execution timing
7. HTML output saved to /viz directory

Usage: uv run visualization_agent.py "Your question here"
"""

import os
import argparse
import time
import shutil
from pathlib import Path
from typing import Literal
from dotenv import load_dotenv
from sqlalchemy import create_engine, pool
from langchain.chat_models import init_chat_model
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from state import VisualizationState
from tools import execute_query_with_handoff
from visualization_nodes import classify_intent, validate_columns, generate_plotly_code, analyze_with_artifact, validate_request_feasibility
from runner import execute_code_node
from logger import log_run, log_warning

load_dotenv()

MODEL_ID = os.getenv("MODEL_OVERRIDE", "google_genai:gemini-3-flash-preview")
VIZ_DIR = Path(__file__).parent.parent / "viz"


def setup_model():
    """Initialize the chat model with deterministic settings."""
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        #os.environ["GEMINI_API_KEY"] = gemini_key
        os.environ["GOOGLE_API_KEY"] = gemini_key

    # temperature=0 ensures consistent outputs for identical inputs
    return init_chat_model(MODEL_ID, temperature=0)


def setup_database():
    """Create database connection with connection pooling."""
    DB_USER = os.getenv("DB_USER", "city_growth_postgres")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "CityGrowthDiagnostics2026")
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = os.getenv("DB_PORT", "5432")
    DB_NAME = os.getenv("DB_NAME", "postgres")

    db_uri = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

    engine = create_engine(
        db_uri,
        poolclass=pool.QueuePool,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=3600,
        pool_pre_ping=True,
    )
    return SQLDatabase(engine)


def build_visualization_agent(db, model):
    """Build the enhanced LangGraph agent with visualization."""

    toolkit = SQLDatabaseToolkit(db=db, llm=model)
    tools = toolkit.get_tools()
    run_query_tool = next(tool for tool in tools if tool.name == "sql_db_query")

    generate_query_system_prompt = f"""
You are an expert {db.dialect} query writer for QCEW employment and wage data.

DATABASE SCHEMA:
Table: msa_wages_employment_data
- area_fips, year, qtr, annual_avg_estabs_count, annual_avg_emplvl
- total_annual_wages, avg_annual_pay, annual_avg_wkly_wage
- area_title, state

IMPORTANT:
- area_title contains full MSA names (e.g., "Boston-Cambridge-Newton, MA-NH")
- state contains 2-letter state codes ONLY (e.g., 'CA', 'TX', 'NY', not 'California')

RULES:
1. ALWAYS use qtr = 'A' for annual data
2. For MSA names, use ILIKE with wildcards: WHERE area_title ILIKE '%Austin%' (NOT exact matches)
3. For state filtering, use 2-letter state codes: WHERE state = 'CA' or WHERE state IN ('CA', 'TX')
   Common state codes: CA=California, TX=Texas, NY=New York, FL=Florida, AZ=Arizona,
   NM=New Mexico, MA=Massachusetts, IL=Illinois, WA=Washington, CO=Colorado
4. NEVER use ILIKE for state column - it contains codes, not full names
5. ORDER BY year ASC for trends
6. For aggregations, use AVG/MAX to handle duplicates (same area_fips)
7. NEVER use DELETE, UPDATE, INSERT, DROP
8. You MUST use the sql_db_query tool to execute queries
"""

    def classify_intent_node(state):
        return classify_intent(state, model)

    def generate_query_node(state):
        llm_with_tools = model.bind_tools([run_query_tool], tool_choice="any")
        response = llm_with_tools.invoke(
            [{"role": "system", "content": generate_query_system_prompt}] + list(state["messages"])
        )
        return {"messages": [response]}

    def run_query_node(state):
        messages = list(state["messages"])
        last_message = messages[-1]

        if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
            return {"sql_valid": False}

        query = last_message.tool_calls[0]["args"]["query"]
        result = execute_query_with_handoff(db, query, intent=state.get("intent", "answer"))

        # Check for empty results when visualization is needed
        if state.get("intent") in ["visualize", "multi_chart"]:
            if result["row_count"] == 0:
                return {
                    "sql_valid": False,
                    "execution_error": "Query returned 0 rows. Cannot create visualization. Please refine your query.",
                    "warnings": [f"Empty result for query: {query[:100]}..."]
                }

        return {
            "generated_sql": query,
            "sql_valid": result["success"],
            "columns": result["columns"],
            "row_count": result["row_count"],
            "data_preview": result["data_preview"],
            "workspace": result["workspace"]
        }

    def validate_columns_node(state):
        return validate_columns(state)

    def analyze_results_node(state):
        user_q = state["messages"][0].content if len(state["messages"]) > 0 else "Unknown"
        prompt = f"Analyze this data for: {user_q}\n\nData:\n{state.get('data_preview', 'No data')}"
        response = model.invoke([{"role": "user", "content": prompt}])

        # Extract text from response (handle both string and list formats)
        if isinstance(response.content, list):
            analysis_text = response.content[0].get('text', '') if response.content else ''
        else:
            analysis_text = str(response.content)

        return {
            "analysis": analysis_text,
            "messages": [AIMessage(content=analysis_text)],
            "execution_success": True
        }

    def generate_plotly_node(state):
        return generate_plotly_code(state, model)

    def execute_code_node_wrapper(state):
        return execute_code_node(state, model)

    def analyze_artifact_node(state):
        return analyze_with_artifact(state, model)

    def validate_request_node(state):
        return validate_request_feasibility(state, model)

    def clarify_node(state):
        """Return clarification message to user instead of proceeding."""
        clarification = state.get("clarification_needed", "Could you please clarify your request?")
        return {
            "messages": [AIMessage(content=clarification)],
            "analysis": clarification,
            "execution_success": False
        }

    # Routing functions
    def route_after_validation(state) -> Literal["generate_query", "clarify"]:
        if state.get("request_valid", True):
            return "generate_query"
        return "clarify"

    def route_by_intent(state) -> Literal["analyze_results", "validate_columns"]:
        if state.get("intent") in ["visualize", "multi_chart"] and state.get("workspace"):
            return "validate_columns"
        return "analyze_results"

    def route_after_execution(state) -> Literal["analyze_artifact", "generate_plotly", END]:
        if state.get("execution_success"):
            return "analyze_artifact"
        retry = state.get("retry_count", 0)
        if retry < 3:
            return "generate_plotly"
        return END

    def should_continue(state) -> Literal[END, "run_query"]:
        last = list(state["messages"])[-1]
        if not hasattr(last, 'tool_calls') or not last.tool_calls:
            return END
        return "run_query"

    # Build graph
    builder = StateGraph(VisualizationState)

    builder.add_node("classify_intent", classify_intent_node)
    builder.add_node("validate_request", validate_request_node)
    builder.add_node("clarify", clarify_node)
    builder.add_node("generate_query", generate_query_node)
    builder.add_node("run_query", run_query_node)
    builder.add_node("validate_columns", validate_columns_node)
    builder.add_node("analyze_results", analyze_results_node)
    builder.add_node("generate_plotly", generate_plotly_node)
    builder.add_node("execute_code", execute_code_node_wrapper)
    builder.add_node("analyze_artifact", analyze_artifact_node)

    builder.add_edge(START, "classify_intent")
    builder.add_edge("classify_intent", "validate_request")
    builder.add_conditional_edges("validate_request", route_after_validation)
    builder.add_edge("clarify", END)
    builder.add_conditional_edges("generate_query", should_continue)
    builder.add_conditional_edges("run_query", route_by_intent)
    builder.add_edge("validate_columns", "generate_plotly")
    builder.add_edge("generate_plotly", "execute_code")
    builder.add_conditional_edges("execute_code", route_after_execution)
    builder.add_edge("analyze_results", END)
    builder.add_edge("analyze_artifact", END)

    return builder.compile()


def classify_single(question: str, save_viz: bool = True) -> dict:
    """Classify a single question using the visualization agent."""
    start_time = time.time()
    warnings = []  # Collect warnings during execution

    print("Initializing Visualization Agent...")
    model = setup_model()
    db = setup_database()
    agent = build_visualization_agent(db, model)

    print(f"Question: {question}\n")
    print("=" * 80)

    initial_state = {
        "messages": [{"role": "user", "content": question}],
        "intent": "answer",
        "sql_valid": False,
        "columns": [],
        "row_count": 0,
        "workspace": None,
        "execution_success": False,
        "retry_count": 0,
    }

    result = agent.invoke(initial_state)
    execution_time = time.time() - start_time

    # Extract analysis from messages
    analysis = ""
    for msg in reversed(result.get("messages", [])):
        if hasattr(msg, "content") and isinstance(msg.content, str) and msg.content.strip():
            analysis = msg.content
            break

    # Check for empty results - mark as failure if row_count=0 for answer intent
    execution_success = result.get("execution_success", False)
    row_count = result.get("row_count", 0)
    intent = result.get("intent", "answer")

    if intent == "answer" and row_count == 0:
        execution_success = False
        if not analysis or "data found" not in analysis.lower():
            analysis = "No data found for your query. Please refine your request or check the city/state names."

    # Print analysis to terminal
    print("\n" + "=" * 80)
    print("ANALYSIS:")
    print("=" * 80)
    print(analysis)
    print("=" * 80)

    # Save HTML visualization to /viz directory
    artifact_saved_path = None
    if save_viz and result.get("artifact_html") and result.get("workspace"):
        VIZ_DIR.mkdir(exist_ok=True)
        job_id = result["workspace"].job_id
        viz_filename = f"{job_id}_output.html"
        viz_path = VIZ_DIR / viz_filename

        shutil.copy(result["workspace"].output_path, viz_path)
        artifact_saved_path = str(viz_path)

        print(f"\n✓ Visualization saved to: {viz_path}")

    print(f"\nExecution time: {execution_time:.2f} seconds")

    # Log the run before returning
    log_run(
        query=question,
        intent=intent,
        success=execution_success,
        execution_time_seconds=round(execution_time, 2),
        error=result.get("execution_error"),
        warnings=result.get("warnings", []),
        metadata={
            "row_count": row_count,
            "chart_type": result.get("chart_type"),
            "num_charts": result.get("num_charts", 0),
            "artifact_saved": artifact_saved_path is not None
        }
    )

    return {
        "analysis": analysis,
        "intent": intent,
        "num_charts": result.get("num_charts", 0),
        "artifact_html": result.get("artifact_html"),
        "artifact_path": artifact_saved_path,
        "chart_type": result.get("chart_type"),
        "execution_success": execution_success,
        "execution_attempts": result.get("execution_attempts", 1),
        "row_count": row_count,
        "execution_time_seconds": round(execution_time, 2)
    }


def main():
    parser = argparse.ArgumentParser(description="Visualization Agent - Ask questions and get visualizations")
    parser.add_argument("question", type=str, help="Your question")
    parser.add_argument("--no-save", action="store_true", help="Don't save HTML to /viz directory")
    args = parser.parse_args()

    result = classify_single(args.question, save_viz=not args.no_save)


if __name__ == "__main__":
    main()
