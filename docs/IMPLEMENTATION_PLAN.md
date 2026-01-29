# Implementation Plan: Conversational Agent Architecture

**Goal:** Transform the City Growth AI from a deterministic LangGraph workflow into a conversation-based ReAct agent that uses the existing workflow as one of its tools.

**Key Decisions:**
- Framework: `create_react_agent` from LangGraph prebuilt
- Router: New router node; existing workflow becomes a callable tool
- Tools: Keep existing structure; `runner.py` remains a utility
- Semantic Layer: Deferred (improve prompts instead)
- Streaming: Deferred but planned
- Escalation: Include failure context; increase max attempts to 5
- Async: All new code uses async; sync workflow wrapped with `asyncio.to_thread()`
- CLI: Simple text output for now (no progress indicators)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CONVERSATIONAL AGENT                                 │
│                      (create_react_agent + tools)                           │
│                                                                             │
│   User Message ────────────────────────────────────────────────────────┐   │
│        │                                                                │   │
│        ▼                                                                │   │
│   ┌─────────────────────────────────────────────────────────────────┐  │   │
│   │                    ReAct LOOP (LLM decides)                      │  │   │
│   │                                                                   │  │   │
│   │   ┌─────────────┐    ┌──────────────────────────────────────┐   │  │   │
│   │   │ pre_model   │    │           TOOL REGISTRY              │   │  │   │
│   │   │ _hook       │    │                                      │   │  │   │
│   │   │ - system    │    │  ┌──────────────────────────────┐   │   │  │   │
│   │   │   prompt    │    │  │ data_analysis_workflow       │   │   │  │   │
│   │   │ - context   │    │  │ (wraps existing StateGraph)  │   │   │  │   │
│   │   │   trimming  │    │  │ - answer intent              │   │   │  │   │
│   │   └─────────────┘    │  │ - visualize intent           │   │   │  │   │
│   │                      │  │ - multi_chart intent         │   │   │  │   │
│   │                      │  └──────────────────────────────┘   │   │  │   │
│   │   LLM decides:       │                                      │   │  │   │
│   │   - which tool       │  ┌──────────────────────────────┐   │   │  │   │
│   │   - tool args        │  │ get_schema                   │   │   │  │   │
│   │   - when done        │  │ (table/column metadata)      │   │   │  │   │
│   │                      │  └──────────────────────────────┘   │   │  │   │
│   │                      │                                      │   │  │   │
│   │                      │  ┌──────────────────────────────┐   │   │  │   │
│   │                      │  │ sample_data                  │   │   │  │   │
│   │                      │  │ (N rows from table)          │   │   │  │   │
│   │                      │  └──────────────────────────────┘   │   │  │   │
│   │                      │                                      │   │  │   │
│   │                      │  ┌──────────────────────────────┐   │   │  │   │
│   │                      │  │ query_database               │   │   │  │   │
│   │                      │  │ (direct SQL for exploration) │   │   │  │   │
│   │                      │  └──────────────────────────────┘   │   │  │   │
│   │                      │                                      │   │  │   │
│   │                      │  ┌──────────────────────────────┐   │   │  │   │
│   │                      │  │ list_cities                  │   │   │  │   │
│   │                      │  │ (available MSAs)             │   │   │  │   │
│   │                      │  └──────────────────────────────┘   │   │  │   │
│   │                      │                                      │   │  │   │
│   │                      └──────────────────────────────────────┘   │  │   │
│   │                                                                   │  │   │
│   └───────────────────────────────────────────────────────────────────┘  │   │
│                                                                          │   │
│   Loop continues until LLM returns response without tool calls ──────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Phase 0: Preparation (Estimated: 1-2 hours)

### 0.1 Update Dependencies

Add to `pyproject.toml`:
```toml
[project.dependencies]
# Existing deps...
langgraph = ">=0.2.0"  # Ensure we have create_react_agent
```

### 0.2 Increase SQL Retry Limit

**File:** `src/visualization_nodes.py`

Change `MAX_SQL_ATTEMPTS` from 3 to 5:
```python
MAX_SQL_ATTEMPTS = 5  # was 3
```

### 0.3 Create Tool Wrappers Directory

```
src/
├── tools/
│   ├── __init__.py           # Export all tools
│   ├── workflow_tool.py      # Wraps existing visualization workflow
│   ├── schema_tools.py       # get_schema, sample_data, list_tables
│   └── query_tool.py         # Direct SQL execution for exploration
├── agent.py                  # New: ReAct agent definition
└── ... (existing files)
```

---

## Phase 1: Tool Definitions (Estimated: 2-3 hours)

### 1.1 Schema Tools (`src/tools/schema_tools.py`)

All tools use `asyncio.to_thread()` to wrap sync SQLAlchemy calls.

```python
import asyncio
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

@tool
async def get_schema(table_name: str = "msa_wages_employment_data", config: RunnableConfig = None) -> str:
    """Get the schema (columns, types, descriptions) for a database table.

    Use this when you need to understand what data is available before writing queries.
    Returns column names, data types, and descriptions.

    Args:
        table_name: Name of the table to inspect (default: msa_wages_employment_data)
    """
    def _get_schema():
        # Query information_schema or return hardcoded schema
        ...
    return await asyncio.to_thread(_get_schema)

@tool
async def sample_data(table_name: str = "msa_wages_employment_data", n_rows: int = 5, config: RunnableConfig = None) -> str:
    """Get sample rows from a table to understand the data format.

    Use this to see what actual values look like (city names, year ranges, etc.)
    Do NOT use for analysis - use data_analysis_workflow for that.

    Args:
        table_name: Table to sample from
        n_rows: Number of rows to return (max 10)
    """
    n_rows = min(max(n_rows, 1), 10)

    def _sample():
        # SELECT * FROM table LIMIT n_rows
        ...
    return await asyncio.to_thread(_sample)

@tool
async def list_cities(state_filter: str = None, config: RunnableConfig = None) -> str:
    """List available cities (MSAs) in the database.

    Use this when user asks about available cities or you need to resolve city names.
    Can filter by state code (e.g., 'TX' for Texas).

    Args:
        state_filter: Optional 2-letter state code to filter results
    """
    def _list():
        # SELECT DISTINCT area_title FROM ... WHERE state ILIKE ...
        ...
    return await asyncio.to_thread(_list)
```

### 1.2 Query Tool (`src/tools/query_tool.py`)

```python
import asyncio
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

@tool
async def query_database(sql: str, config: RunnableConfig = None) -> str:
    """Execute a read-only SQL query against the database.

    Use for exploratory queries when you need to understand the data.
    For user-facing analysis or visualizations, use data_analysis_workflow instead.

    CRITICAL RULES:
    - Only SELECT statements allowed
    - Always use qtr = 'A' for annual data
    - Use ILIKE with wildcards for area_title matching
    - Results limited to 100 rows

    Args:
        sql: The SQL query to execute (SELECT only)
    """
    def _execute():
        # Validate SQL (SELECT only), execute with timeout, format results
        ...
    return await asyncio.to_thread(_execute)
```

### 1.3 Workflow Tool (`src/tools/workflow_tool.py`)

This is the key integration - wrapping the existing workflow as a tool:

```python
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

@tool
async def data_analysis_workflow(
    question: str,
    intent: str = "auto",
    config: RunnableConfig = None
) -> str:
    """Run the full data analysis and visualization pipeline.

    Use this tool when the user wants:
    - Data analysis with a specific answer (intent="answer")
    - A visualization/chart (intent="visualize")
    - Multiple charts comparing data (intent="multi_chart")
    - Auto-detect the best approach (intent="auto")

    This tool handles:
    - SQL generation with validation and retry
    - Query execution and data extraction
    - Visualization generation (Plotly charts)
    - Analysis and insights generation

    Do NOT use this for:
    - Simple schema questions (use get_schema)
    - Exploring what data exists (use sample_data, list_cities)
    - Testing SQL queries (use query_database)

    Args:
        question: The user's analytical question (e.g., "Show wage trends in Austin")
        intent: "answer" | "visualize" | "multi_chart" | "auto" (default: auto)

    Returns:
        Analysis text, and if visualization was created, the path to the HTML artifact.
    """
    import asyncio
    from src.visualization_agent import classify_single

    # Wrap sync workflow in asyncio.to_thread() to avoid blocking
    result = await asyncio.to_thread(classify_single, question, save_viz=True)

    # Format response for the agent
    response_parts = []

    if result.get("analysis"):
        response_parts.append(f"Analysis:\n{result['analysis']}")

    if result.get("artifact_path"):
        response_parts.append(f"\nVisualization saved to: {result['artifact_path']}")

    if result.get("warnings"):
        response_parts.append(f"\nWarnings: {', '.join(result['warnings'])}")

    if result.get("error"):
        response_parts.append(f"\nError: {result['error']}")
        if result.get("sql_review_feedback"):
            response_parts.append(f"SQL Review Feedback: {result['sql_review_feedback']}")

    return "\n".join(response_parts) if response_parts else "No results returned."
```

### 1.4 Tool Registry (`src/tools/__init__.py`)

```python
from .schema_tools import get_schema, sample_data, list_cities
from .query_tool import query_database
from .workflow_tool import data_analysis_workflow

def get_all_tools():
    """Return all tools available to the conversational agent."""
    return [
        data_analysis_workflow,  # Primary tool for analysis/viz
        get_schema,              # Schema exploration
        sample_data,             # Data preview
        list_cities,             # City name lookup
        query_database,          # Direct SQL (exploration only)
    ]
```

---

## Phase 2: Conversational Agent (`src/agent.py`) (Estimated: 2-3 hours)

### 2.1 Agent Definition

```python
import os
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.messages import SystemMessage
from langchain_core.messages.utils import trim_messages

from src.tools import get_all_tools

SYSTEM_PROMPT = """You are a data analyst assistant specializing in urban economics and city growth analysis.

You have access to QCEW (Quarterly Census of Employment and Wages) data for Metropolitan Statistical Areas (MSAs), including:
- Employment levels (annual_avg_emplvl)
- Average wages (avg_annual_pay, annual_avg_wkly_wage)
- Number of establishments (annual_avg_estabs)
- Data from 2001-2024 for ~400 MSAs

## Your Tools

1. **data_analysis_workflow** - Your primary tool for answering analytical questions and creating visualizations.
   Use this when the user wants analysis, charts, comparisons, trends, or rankings.

2. **get_schema** - Get table/column metadata. Use to understand available fields.

3. **sample_data** - Get sample rows. Use to see data formats and values.

4. **list_cities** - List available MSAs. Use when user asks about available cities or needs name resolution.

5. **query_database** - Direct SQL queries for exploration. Use only for exploratory queries, NOT for user-facing analysis.

## Guidelines

- For analytical questions (trends, comparisons, rankings), use data_analysis_workflow
- If the workflow fails, examine the error and try again with a refined question
- For simple questions about data availability, use the schema/sample tools first
- Always verify city names exist using list_cities if there's any ambiguity
- Be conversational - explain what you're doing and what you found
- If a visualization was created, mention the file path so the user can open it

## What You Cannot Do

- You cannot access GDP, population, housing prices, or cost of living data (only QCEW employment/wage data)
- You cannot make predictions about the future
- You cannot compare across different data sources
"""

def prepare_llm_input(state):
    """Pre-model hook: inject system prompt and trim messages."""
    trimmed = trim_messages(
        state["messages"],
        strategy="last",
        token_counter=len,
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
    """Create the conversational ReAct agent."""
    if checkpointer is None:
        checkpointer = InMemorySaver()

    model_name = os.getenv("MODEL_OVERRIDE", "google_genai:gemini-2.0-flash")

    return create_react_agent(
        model=model_name,
        tools=get_all_tools(),
        checkpointer=checkpointer,
        pre_model_hook=prepare_llm_input,
    )

# Singleton agent instance
_agent = None

def get_agent():
    """Get or create the singleton agent instance."""
    global _agent
    if _agent is None:
        _agent = create_conversational_agent()
    return _agent
```

### 2.2 Agent Entry Point (`src/conversation.py`)

```python
import uuid
from src.agent import get_agent

async def chat(message: str, thread_id: str = None) -> dict:
    """
    Send a message to the conversational agent.

    Args:
        message: User's message
        thread_id: Conversation thread ID (creates new if None)

    Returns:
        dict with 'response', 'thread_id', 'tool_calls'
    """
    if thread_id is None:
        thread_id = uuid.uuid4().hex[:8]

    agent = get_agent()

    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": message}]},
        config,
    )

    # Extract the final response
    final_message = result["messages"][-1]

    # Collect tool calls made during this turn
    tool_calls = []
    for msg in result["messages"]:
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append({
                    "tool": tc["name"],
                    "args": tc["args"],
                })

    return {
        "response": final_message.content,
        "thread_id": thread_id,
        "tool_calls": tool_calls,
    }

# DEFERRED: chat_stream for future streaming support
# async def chat_stream(message: str, thread_id: str = None):
#     """Stream responses from the conversational agent."""
#     # Implementation deferred - see Phase 5.1
```

### 2.3 CLI Entry Point (`src/cli.py`)

Simple text-only output (no progress indicators for now).

```python
#!/usr/bin/env python3
"""
CLI for the City Growth AI conversational agent.

Usage:
    uv run src/cli.py                    # Interactive mode
    uv run src/cli.py "your question"    # Single question mode
"""

import asyncio
import sys

async def interactive_mode():
    """Run interactive conversation loop."""
    from src.conversation import chat

    print("City Growth AI Agent")
    print("Type 'quit' or 'exit' to end the conversation.")
    print("Type 'new' to start a new conversation thread.")
    print("-" * 50)

    thread_id = None

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit"):
            print("Goodbye!")
            break

        if user_input.lower() == "new":
            thread_id = None
            print("Starting new conversation...")
            continue

        result = await chat(user_input, thread_id)
        thread_id = result["thread_id"]

        print(f"\nAssistant: {result['response']}")

async def single_question_mode(question: str):
    """Answer a single question and exit."""
    from src.conversation import chat

    result = await chat(question)
    print(result["response"])

def main():
    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
        asyncio.run(single_question_mode(question))
    else:
        asyncio.run(interactive_mode())

if __name__ == "__main__":
    main()
```

---

## Phase 3: Graceful Escalation (Estimated: 1-2 hours)

### 3.1 Modify Workflow to Return Detailed Failure Context

**File:** `src/visualization_agent.py`

Update `classify_single` to return structured failure information:

```python
def classify_single(question: str, save_viz: bool = True) -> dict:
    # ... existing code ...

    result = {
        "analysis": analysis,
        "intent": intent,
        "num_charts": num_charts,
        "artifact_path": artifact_path,
        "execution_time_seconds": execution_time_seconds,
        "warnings": warnings,
        # NEW: Add failure context for escalation
        "success": success,
        "error": error_message if not success else None,
        "sql_attempts": final_state.get("sql_attempts", 0),
        "sql_review_passed": final_state.get("sql_review_passed", True),
        "sql_review_feedback": final_state.get("sql_review_feedback", ""),
        "generated_sql": final_state.get("generated_sql", ""),
        "execution_attempts": final_state.get("execution_attempts", 0),
        "execution_error": final_state.get("execution_error", ""),
    }

    return result
```

### 3.2 Workflow Tool with Escalation Context

Update `src/tools/workflow_tool.py` to format failure context:

```python
@tool
async def data_analysis_workflow(
    question: str,
    intent: str = "auto",
    config: RunnableConfig = None
) -> str:
    """..."""  # docstring unchanged

    from src.visualization_agent import classify_single

    result = await classify_single(question, save_viz=True)

    # Build response
    response_parts = []

    if result.get("success") and result.get("analysis"):
        response_parts.append(f"Analysis:\n{result['analysis']}")

        if result.get("artifact_path"):
            response_parts.append(f"\nVisualization saved to: {result['artifact_path']}")

    elif not result.get("success"):
        # Failure case - provide detailed context for agent to reason about
        response_parts.append("The workflow encountered issues:")

        if result.get("error"):
            response_parts.append(f"\nError: {result['error']}")

        if not result.get("sql_review_passed"):
            response_parts.append(f"\nSQL Review Failed after {result.get('sql_attempts', 0)} attempts")
            response_parts.append(f"Last feedback: {result.get('sql_review_feedback', 'None')}")
            response_parts.append(f"Last SQL attempted:\n```sql\n{result.get('generated_sql', 'N/A')}\n```")

        if result.get("execution_error"):
            response_parts.append(f"\nCode Execution Error: {result.get('execution_error')}")
            response_parts.append(f"Execution attempts: {result.get('execution_attempts', 0)}")

        response_parts.append("\nYou may need to:")
        response_parts.append("- Rephrase the question with more specific details")
        response_parts.append("- Use query_database to explore the data first")
        response_parts.append("- Check available columns with get_schema")

    if result.get("warnings"):
        response_parts.append(f"\nWarnings: {', '.join(result['warnings'])}")

    return "\n".join(response_parts) if response_parts else "No results returned."
```

---

## Phase 4: Migration & Testing (Estimated: 2-3 hours)

### 4.1 File Structure After Implementation

```
src/
├── agent.py                      # NEW: ReAct agent definition
├── conversation.py               # NEW: Chat interface (sync/async)
├── cli.py                        # NEW: CLI entry point
├── tools/
│   ├── __init__.py              # NEW: Tool registry
│   ├── workflow_tool.py         # NEW: Wraps visualization workflow
│   ├── schema_tools.py          # NEW: get_schema, sample_data, list_cities
│   └── query_tool.py            # NEW: Direct SQL tool
├── visualization_agent.py        # EXISTING: Keep as workflow implementation
├── visualization_nodes.py        # EXISTING: Increase MAX_SQL_ATTEMPTS to 5
├── tools.py                      # EXISTING: Keep SQL execution utility
├── workspace.py                  # EXISTING: Keep unchanged
├── runner.py                     # EXISTING: Keep as utility
├── validator.py                  # EXISTING: Keep unchanged
├── models.py                     # EXISTING: Keep unchanged
├── state.py                      # EXISTING: Keep unchanged
├── prompts.py                    # EXISTING: Keep unchanged
└── logger.py                     # EXISTING: Keep unchanged
```

### 4.2 Update README Quick Start

```markdown
## Quick Start

### Conversational Mode (NEW - Recommended)
```bash
# Interactive conversation
uv run src/cli.py

# Single question
uv run src/cli.py "What cities have the highest wage growth?"
```

### Direct Workflow Mode (Legacy)
```bash
# For direct visualization without conversation
uv run src/visualization_agent.py "Create a line chart of wage trends for Austin"
```
```

### 4.3 Test Cases

Create `tests/test_conversation.py`:

```python
import pytest
from src.conversation import chat

@pytest.mark.asyncio
async def test_simple_greeting():
    """Agent should respond to greetings without tools."""
    result = await chat("Hello!")
    assert result["response"]
    assert len(result["tool_calls"]) == 0

@pytest.mark.asyncio
async def test_schema_question():
    """Agent should use get_schema for schema questions."""
    result = await chat("What columns are in the database?")
    assert any(tc["tool"] == "get_schema" for tc in result["tool_calls"])

@pytest.mark.asyncio
async def test_analysis_question():
    """Agent should use workflow for analysis questions."""
    result = await chat("What is the average wage in Austin in 2023?")
    assert any(tc["tool"] == "data_analysis_workflow" for tc in result["tool_calls"])

@pytest.mark.asyncio
async def test_visualization_question():
    """Agent should use workflow for visualization requests."""
    result = await chat("Create a chart of wage trends in Austin")
    assert any(tc["tool"] == "data_analysis_workflow" for tc in result["tool_calls"])
    assert "artifact" in result["response"].lower() or "visualization" in result["response"].lower()

@pytest.mark.asyncio
async def test_city_lookup():
    """Agent should use list_cities for city name questions."""
    result = await chat("What cities are available in Texas?")
    assert any(tc["tool"] == "list_cities" for tc in result["tool_calls"])

@pytest.mark.asyncio
async def test_conversation_continuity():
    """Agent should maintain context across turns."""
    result1 = await chat("What is the average wage in Austin in 2023?")
    thread_id = result1["thread_id"]

    result2 = await chat("How does that compare to Dallas?", thread_id=thread_id)
    # Should understand "that" refers to wages from previous turn
    assert any(tc["tool"] == "data_analysis_workflow" for tc in result2["tool_calls"])
```

---

## Phase 5: Future Enhancements (Deferred)

### 5.1 Streaming (Priority: Medium)

- Add `chat_stream` to CLI with progress indicators
- SSE endpoint for web integration
- Show tool execution progress in real-time

### 5.2 Semantic Layer (Priority: Low)

- YAML config for metrics/dimensions/constraints
- Deterministic city name resolver
- Entity linking for common abbreviations (NYC → New York...)

### 5.3 Memory & Learning (Priority: Low)

- Store successful query patterns
- Retrieve similar past queries as few-shot examples
- Track common failure modes for prompt improvement

### 5.4 Specialized Subagents (Priority: Future)

From README goals:
- Peer selection expert
- Growth Trajectory Analyst
- Growth Narrative Designer
- Constraints Analyst
- Labor Demand/Supply Experts

---

## Implementation Order

| Phase | Task | Est. Time | Dependencies |
|-------|------|-----------|--------------|
| 0.1 | Update pyproject.toml | 10 min | None |
| 0.2 | Increase MAX_SQL_ATTEMPTS to 5 | 5 min | None |
| 0.3 | Create tools/ directory structure | 10 min | None |
| 1.1 | Implement schema_tools.py | 45 min | 0.3 |
| 1.2 | Implement query_tool.py | 30 min | 0.3 |
| 1.3 | Implement workflow_tool.py | 45 min | 0.3 |
| 1.4 | Create tools/__init__.py | 10 min | 1.1-1.3 |
| 2.1 | Create agent.py | 30 min | 1.4 |
| 2.2 | Create conversation.py | 30 min | 2.1 |
| 2.3 | Create cli.py | 20 min | 2.2 |
| 3.1 | Modify classify_single for failure context | 30 min | None |
| 3.2 | Update workflow_tool with escalation | 20 min | 1.3, 3.1 |
| 4.1 | Manual testing | 60 min | All above |
| 4.2 | Update README | 15 min | All above |
| 4.3 | Write test_conversation.py | 45 min | All above |

**Total Estimated Time:** 7-9 hours

---

## Success Criteria

1. **Conversational Interface Works**
   - User can have multi-turn conversations
   - Agent maintains context across turns
   - Greetings and simple questions don't trigger tools

2. **Workflow Integration Works**
   - `data_analysis_workflow` tool produces same results as direct workflow
   - Visualizations are saved and paths reported to user
   - Failure context is provided for agent reasoning

3. **Tool Selection is Appropriate**
   - Schema questions → get_schema
   - City lookup → list_cities
   - Analysis/visualization → data_analysis_workflow
   - Exploration → query_database

4. **Graceful Degradation**
   - Workflow failures include actionable context
   - Agent can suggest alternatives on failure
   - No silent failures

5. **Backward Compatibility**
   - `visualization_agent.py` still works standalone
   - Existing tests pass
   - Same output quality for same questions
