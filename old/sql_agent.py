#!/usr/bin/env python3
"""
SQL Agent - Interactive SQL database query agent for QCEW employment and wage data

Features:
- Natural language to SQL query generation
- Query mode classification (preview vs analysis)
- City name disambiguation with area_fips
- Natural language result analysis

Usage: uv run sql_agent.py "Your question here"

Examples:
  uv run sql_agent.py "What is the average wage in Austin in 2023?"
  uv run sql_agent.py "Show employment trends for Seattle from 2010-2020"
  uv run sql_agent.py "How many rows are there per year?"
"""

import os
import argparse
import time
from typing import Literal
from dotenv import load_dotenv
from sqlalchemy import create_engine
from langchain.chat_models import init_chat_model

# Load environment variables from .env file
load_dotenv()
from langchain.messages import AIMessage
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode


def setup_model():
    """Initialize the chat model"""
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        os.environ["GEMINI_API_KEY"] = gemini_key
        os.environ["GOOGLE_API_KEY"] = gemini_key
    return init_chat_model("google_genai:gemini-3-flash-preview")


def setup_database():
    """Create database connection"""
    DB_USER = os.getenv("DB_USER", "city_growth_postgres")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = os.getenv("DB_PORT", "5432")
    DB_NAME = os.getenv("DB_NAME", "postgres")

    db_uri = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    engine = create_engine(db_uri)
    db = SQLDatabase(engine)

    print(f"Connected! Tables: {db.get_usable_table_names()}")
    return db


def build_agent(db, model):
    """Build the LangGraph SQL agent"""
    toolkit = SQLDatabaseToolkit(db=db, llm=model)
    tools = toolkit.get_tools()

    # Get query tool (schema is cached in system prompt - see docs/schema_caching.md)
    run_query_tool = next(tool for tool in tools if tool.name == "sql_db_query")
    run_query_node = ToolNode([run_query_tool], name="run_query")

    # Node: Generate query
    generate_query_system_prompt = f"""
You are an expert {db.dialect} query writer for QCEW employment and wage data.

DATABASE SCHEMA:
Table: msa_wages_employment_data
- area_fips: MSA identifier code (VARCHAR)
- year: Year (INTEGER, 2000-2024)
- qtr: Quarter (VARCHAR, 'A' = Annual average)
- size_code: Establishment size code (INTEGER)
- size_title: Size category description (VARCHAR)
- annual_avg_estabs_count: Number of establishments (INTEGER)
- annual_avg_emplvl: Employment level (INTEGER)
- total_annual_wages: Total wages (BIGINT)
- avg_annual_pay: Average annual pay (NUMERIC)
- annual_avg_wkly_wage: Average weekly wage (NUMERIC)
- area_title: MSA name, e.g., "Austin-Round Rock, TX" (VARCHAR)
- state: State abbreviation (VARCHAR)

QUERY MODES - Classify the user's question into one of these modes:

**PREVIEW MODE** (sample data requests):
- Keywords: "show me", "examples", "sample", "what does the data look like"
- Use: LIMIT 10, SELECT specific columns
- Example: "Show me some Austin data" → LIMIT 10

**ANALYSIS MODE** (aggregations, statistics, calculations):
- Keywords: "how many", "average", "total", "trend", "compare", "CAGR", "growth", "distribution"
- Use: GROUP BY, aggregation functions (SUM, AVG, COUNT), NO arbitrary LIMIT
- Example: "What's the CAGR for Austin 2010-2020?" → No LIMIT, use calculations
- Example: "How many rows per year?" → GROUP BY year, COUNT(*)

IMPORTANT RULES:
1. ALWAYS use qtr = 'A' for annual data (most common use case)
2. For MSA names, use ILIKE for case-insensitive matching:
   WHERE area_title ILIKE '%Austin%'
3. HANDLE DUPLICATE AREA NAMES: Some MSAs have duplicate rows with different area_title values
   but identical data (same area_fips). To avoid duplicates:
   - For aggregations: Use AVG/MAX to deduplicate (e.g., AVG(avg_annual_pay))
   - For simple selects: Add DISTINCT ON (area_fips, year) or GROUP BY area_fips, year
   - Example: SELECT DISTINCT ON (area_fips, year) area_fips, area_title, year, avg_annual_pay
4. For PREVIEW mode queries, LIMIT to 10 results
5. For ANALYSIS mode queries, do NOT add LIMIT (use aggregations instead)
6. Use proper aggregation functions (SUM, AVG, COUNT, MIN, MAX)
7. For trend analysis, ORDER BY year ASC
8. NEVER use DELETE, UPDATE, INSERT, DROP, or other DML/DDL statements
9. Only query relevant columns needed to answer the question

EXAMPLES:
Q: "What's the average wage in Austin in 2023?"
A: SELECT DISTINCT ON (area_fips) area_title, avg_annual_pay, year
   FROM msa_wages_employment_data
   WHERE area_title ILIKE '%Austin%' AND year = 2023 AND qtr = 'A'
   ORDER BY area_fips;

Q: "Show wage trends for Austin from 2010-2020"
A: SELECT year, AVG(avg_annual_pay) as avg_wage
   FROM msa_wages_employment_data
   WHERE area_title ILIKE '%Austin%' AND qtr = 'A'
     AND year BETWEEN 2010 AND 2020
   GROUP BY year
   ORDER BY year ASC;

Q: "How many rows are there per year?"
A: SELECT year, COUNT(*) as row_count
   FROM msa_wages_employment_data
   GROUP BY year
   ORDER BY year ASC;
"""

    def generate_query(state: MessagesState):
        system_message = {
            "role": "system",
            "content": generate_query_system_prompt,
        }
        llm_with_tools = model.bind_tools([run_query_tool])
        response = llm_with_tools.invoke([system_message] + state["messages"])
        return {"messages": [response]}

    # Node: Check query
    check_query_system_prompt = f"""
You are a SQL expert with a strong attention to detail.
Double check the {db.dialect} query for common mistakes, including:
- Using NOT IN with NULL values (always returns empty set)
- Using UNION when UNION ALL should have been used
- Using BETWEEN for exclusive ranges (BETWEEN is inclusive on both ends)
- Data type mismatch in predicates
- Properly quoting identifiers (PostgreSQL: double quotes for identifiers, single for strings)
- Using the correct number of arguments for functions
- Casting to the correct data type
- Using the proper columns for joins
- Missing GROUP BY for non-aggregated columns in aggregations
- For PREVIEW mode: ensure LIMIT is present (10 rows)
- For ANALYSIS mode: ensure no arbitrary LIMIT (unless user specified)

SPECIFIC CHECKS FOR THIS DATABASE:
- Ensure qtr = 'A' is used for annual data
- Ensure area_title uses ILIKE (not LIKE) for case-insensitive matching
- Verify aggregations use proper functions (AVG, SUM, COUNT, etc.)

If there are any of the above mistakes, rewrite the query. If there are no mistakes,
just reproduce the original query.

You will call the appropriate tool to execute the query after running this check.
"""

    def check_query(state: MessagesState):
        system_message = {
            "role": "system",
            "content": check_query_system_prompt,
        }

        tool_call = state["messages"][-1].tool_calls[0]
        user_message = {"role": "user", "content": tool_call["args"]["query"]}
        llm_with_tools = model.bind_tools([run_query_tool], tool_choice="any")
        response = llm_with_tools.invoke([system_message, user_message])
        response.id = state["messages"][-1].id

        return {"messages": [response]}

    # Node: Analyze results
    analyze_results_system_prompt = """
You are a data analyst interpreting query results for QCEW employment and wage data.

TASK: Provide a clear, concise natural language answer to the user's question
based on the SQL query results.

GUIDELINES:
1. Start with a direct answer to the question
2. Include relevant numbers and statistics with proper formatting ($68,450 not 68450.00)
3. Mention any notable patterns or insights
4. If results show duplicate area names (e.g., "Austin-Round Rock, TX" and "Austin-Round Rock-San Marcos, TX"),
   explain that these are the same MSA with different naming conventions and use the shorter name
5. If results are empty, explain possible reasons (misspelled MSA, no data for time period, etc.)
6. Keep it conversational and easy to understand
7. Use bullet points for multiple data points

EXAMPLE:
Question: "What's the average wage in Austin in 2023?"
Results: [{"area_title": "Austin-Round Rock, TX", "avg_annual_pay": 68450.00}]
Analysis: "In 2023, the average annual pay in Austin-Round Rock, TX was $68,450."
"""

    def analyze_results(state: MessagesState):
        """Convert SQL results to natural language answer"""
        messages = state["messages"]

        # Find the user's original query
        user_query = next(
            (msg.content for msg in messages if msg.__class__.__name__ == "HumanMessage"),
            "Unknown query"
        )

        # Find the most recent tool message (query results)
        tool_message = next(
            (msg for msg in reversed(messages) if msg.__class__.__name__ == "ToolMessage"),
            None
        )

        if not tool_message:
            response = AIMessage(content="No query results found to analyze.")
            return {"messages": [response]}

        # Extract results
        results = tool_message.content

        # Build analysis prompt
        system_message = {"role": "system", "content": analyze_results_system_prompt}
        user_message = {
            "role": "user",
            "content": f"Question: {user_query}\n\nQuery Results:\n{results}\n\nProvide analysis:"
        }

        # Generate analysis
        analysis_response = model.invoke([system_message, user_message])

        return {"messages": [analysis_response]}

    # Edge condition
    def should_continue(state: MessagesState) -> Literal[END, "check_query"]:
        messages = state["messages"]
        last_message = messages[-1]
        if not last_message.tool_calls:
            return END
        else:
            return "check_query"

    # Build the graph
    # Flow: generate_query → check_query → run_query → analyze_results → END
    # Note: Schema is cached in system prompt (see docs/schema_caching.md)
    # This skips dynamic schema discovery for faster execution
    builder = StateGraph(MessagesState)
    builder.add_node(generate_query)
    builder.add_node(check_query)
    builder.add_node(run_query_node, "run_query")
    builder.add_node(analyze_results)

    builder.add_edge(START, "generate_query")
    builder.add_conditional_edges("generate_query", should_continue)
    builder.add_edge("check_query", "run_query")
    builder.add_edge("run_query", "analyze_results")
    builder.add_edge("analyze_results", END)

    return builder.compile()


def main():
    parser = argparse.ArgumentParser(description="SQL Agent - Ask questions about your database")
    parser.add_argument("question", type=str, help="The question to ask the SQL agent")
    args = parser.parse_args()

    print("Initializing SQL Agent...")
    model = setup_model()
    db = setup_database()
    agent = build_agent(db, model)

    print(f"\nQuestion: {args.question}\n")
    print("=" * 80)

    # Measure execution time
    start_time = time.time()

    # Stream the agent's responses
    for step in agent.stream(
        {"messages": [{"role": "user", "content": args.question}]},
        stream_mode="values",
    ):
        step["messages"][-1].pretty_print()

    # Calculate and display execution time
    execution_time = time.time() - start_time
    print("\n" + "=" * 80)
    print(f"Execution time: {execution_time:.2f} seconds")
    print("=" * 80)


if __name__ == "__main__":
    main()
