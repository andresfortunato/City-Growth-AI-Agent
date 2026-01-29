"""
agent.py - Conversational ReAct agent for City Growth AI

Uses LangGraph's create_react_agent with pre_model_hook for system prompt
injection and message trimming.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from langchain_core.messages import SystemMessage
from langchain_core.messages.utils import trim_messages
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import InMemorySaver

# Add src to path for tool imports
sys.path.insert(0, str(Path(__file__).parent))

from tools import get_all_tools

load_dotenv()

SYSTEM_PROMPT = """You are a data analyst assistant specializing in urban economics and city growth analysis.

You have access to QCEW (Quarterly Census of Employment and Wages) data for Metropolitan Statistical Areas (MSAs), including:
- Employment levels (annual_avg_emplvl)
- Average wages (avg_annual_pay, annual_avg_wkly_wage)
- Number of establishments (annual_avg_estabs_count)
- Data from 2001-2024 for ~400 MSAs across the United States

## Your Tools

1. **data_analysis_workflow** - Your primary tool for answering analytical questions and creating visualizations.
   Use this when the user wants:
   - Specific data answers (e.g., "What is the average wage in Austin?")
   - Charts and visualizations (e.g., "Show wage trends for Austin")
   - Comparisons (e.g., "Compare employment growth in Austin vs Dallas")
   - Calculations like CAGR, growth rates, rankings

2. **get_schema** - Get table/column metadata.
   Use when you need to understand what data fields are available.

3. **sample_data** - Get sample rows from the database.
   Use to see what actual data values look like (city name formats, year ranges).

4. **list_cities** - List available MSAs.
   Use when the user asks what cities are available, or to verify a city name exists.
   Can filter by state (e.g., list_cities(state_filter='TX')).

5. **query_database** - Direct SQL queries for exploration.
   Use ONLY for exploratory queries to understand the data.
   Do NOT use for user-facing analysis - use data_analysis_workflow instead.

## Guidelines

- For analytical questions (trends, comparisons, rankings, calculations), use data_analysis_workflow
- If the workflow fails, examine the error and consider:
  - Rephrasing the question more specifically
  - Using list_cities to verify city names
  - Using get_schema to check available columns
- For simple questions about data availability, use the schema/sample tools first
- Be conversational - explain what you're doing and what you found
- If a visualization was created, mention the file path so the user can open it
- When comparing cities, make sure to spell out the full MSA name or use wildcards

## Data Notes

- Annual data uses qtr = 'A' (this is handled automatically by the tools)
- City names are full MSA titles like "Austin-Round Rock-Georgetown, TX"
- Use ILIKE with wildcards for partial matching (e.g., '%Austin%')

## What You Cannot Answer

- GDP data (not available - only employment/wage data)
- Population data (not available)
- Housing prices or cost of living (not available)
- Future predictions (no forecasting capability)
- Industry-specific breakdowns (coming soon, not yet available)
"""


def prepare_llm_input(state: dict) -> dict:
    """Pre-model hook: inject system prompt and trim messages.

    This runs before each LLM call to:
    1. Add the system prompt (without polluting checkpoint state)
    2. Trim old messages to stay within context limits
    """
    # Trim messages to fit context window
    trimmed = trim_messages(
        state["messages"],
        strategy="last",
        token_counter=len,  # Simple character-based approximation
        max_tokens=100_000,
        allow_partial=False,
    )

    return {
        "llm_input_messages": [
            SystemMessage(content=SYSTEM_PROMPT),
            *trimmed,
        ]
    }


def create_conversational_agent(checkpointer=None):
    """Create the conversational ReAct agent.

    Args:
        checkpointer: Optional checkpointer for persistence.
                     Defaults to InMemorySaver for development.

    Returns:
        Compiled LangGraph agent
    """
    if checkpointer is None:
        checkpointer = InMemorySaver()

    # Get model from environment, default to Gemini
    model_name = os.getenv("MODEL_OVERRIDE", "google_genai:gemini-2.0-flash")

    # Ensure API key is set
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        os.environ["GOOGLE_API_KEY"] = gemini_key

    return create_react_agent(
        model=model_name,
        tools=get_all_tools(),
        checkpointer=checkpointer,
        pre_model_hook=prepare_llm_input,
    )


# Singleton agent instance
_agent = None
_checkpointer = None


def get_agent():
    """Get or create the singleton agent instance.

    The agent is created once and reused across requests.
    Thread isolation is achieved through thread_id in config.
    """
    global _agent, _checkpointer

    if _agent is None:
        _checkpointer = InMemorySaver()
        _agent = create_conversational_agent(checkpointer=_checkpointer)

    return _agent


def reset_agent():
    """Reset the singleton agent (useful for testing)."""
    global _agent, _checkpointer
    _agent = None
    _checkpointer = None
