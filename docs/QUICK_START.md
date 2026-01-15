# SQL Agent - Quick Start Guide

This is a condensed implementation checklist. See `SQL_AGENT_DESIGN.md` for full details.

## Prerequisites
- Python 3.12+
- PostgreSQL running on localhost:5432
- API key for Google Gemini

## Installation (10 minutes)

```bash
# 1. Dependencies are already in pyproject.toml
# Verify these are present:
# - langgraph
# - langchain
# - langchain-community
# - langchain-google-genai
# - sqlalchemy
# - psycopg2-binary
# - python-dotenv
# - pytest
# - pytest-asyncio

# 2. Install if needed
uv sync  # or: pip install -e .

# 3. Environment variables are already in .env file:
# - GEMINI_API_KEY
# - DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME
# Verify your .env file contains these values
```

## Implementation Checklist

### Step 1: Create Project Structure (5 min)
```bash
mkdir -p sql_agent tests
touch sql_agent/__init__.py
touch sql_agent/{state.py,tools.py,prompts.py,nodes.py,agent.py}
touch tests/{test_agent.py,test_nodes.py}
```

### Step 2: Implement Core Files (2 hours)

Order of implementation:
1. `state.py` - Define state schema (10 min)
2. `tools.py` - Set up database tools (15 min)
3. `prompts.py` - Copy prompts from design doc (10 min)
4. `nodes.py` - Implement all 7 nodes (45 min)
5. `agent.py` - Build graph and compile (30 min)
6. `cli.py` - Create command-line interface (15 min)

### Step 3: Test Basic Functionality (30 min)

```bash
# Test database connection
python -c "
from sql_agent.tools import create_tools
tools = create_tools()
print('Tools created:', [t.name for t in tools])
"

# Test agent
python cli.py "How many rows are in the table?"
python cli.py "What is the average wage in Austin in 2023?"
```

### Step 4: Write Tests (30 min)
```bash
# Create basic tests in tests/test_agent.py
pytest tests/ -v
```

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                         START                                │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
                   ┌────────────────┐
                   │  list_tables   │  No LLM (direct tool call)
                   │                │  → Gets available tables
                   └────────┬───────┘
                            │
                            ▼
                   ┌────────────────┐
                   │ get_schema     │  No LLM (ToolNode)
                   │                │  → Fetches table structure
                   └────────┬───────┘
                            │
                            ▼
                   ┌────────────────┐
                   │generate_query  │  LLM Call #1
                   │                │  → Translates NL to SQL
                   └────────┬───────┘
                            │
                            ▼
                   [Conditional: Has tool_calls?]
                            │
                  ┌─────────┴─────────┐
                  │                   │
                Yes                  No → END (error)
                  │
                  ▼
           ┌────────────────┐
           │ check_query    │  LLM Call #2
           │                │  → Validates SQL
           └────────┬───────┘
                    │
                    ▼
           ┌────────────────┐
           │  run_query     │  Database Call
           │                │  → Executes SQL
           └────────┬───────┘
                    │
                    ▼
           ┌────────────────┐
           │analyze_results │  LLM Call #3
           │                │  → Interprets results
           └────────┬───────┘
                    │
                    ▼
                  ┌───┐
                  │END│
                  └───┘
```

## State Flow Example

```python
# Initial state
{
    "user_query": "What is the average wage in Austin in 2023?",
    "available_tables": [],
    "table_schema": "",
    "generated_sql": None,
    "messages": []
}

# After list_tables
{
    "user_query": "...",
    "available_tables": ["msa_wages_employment_data"],
    "messages": [...]
}

# After generate_query
{
    "user_query": "...",
    "available_tables": [...],
    "table_schema": "...",
    "generated_sql": "SELECT AVG(avg_annual_pay) FROM msa_wages_employment_data WHERE area_title ILIKE '%Austin%' AND year = 2023 AND qtr = 'A' LIMIT 100;",
    "messages": [...]
}

# Final state
{
    "user_query": "...",
    "generated_sql": "...",
    "query_results": [{"avg": 68450}],
    "analysis": "In 2023, the average annual pay in the Austin-Round Rock, TX metro area was $68,450.",
    "messages": [...]
}
```

## Key Design Patterns

### 1. Node Pattern
Every node follows this structure:
```python
def node_name(state: SQLAgentState) -> dict:
    """Node description."""
    # 1. Extract needed values from state
    user_query = state["user_query"]

    # 2. Do work (LLM call, DB query, etc.)
    result = do_something(user_query)

    # 3. Return state updates
    return {
        "field_to_update": result,
        "messages": state["messages"] + [new_message]
    }
```

### 2. Tool Invocation Pattern
```python
# Get tool
my_tool = next(t for t in tools if t.name == "tool_name")

# Create tool call
tool_call = {
    "name": "tool_name",
    "args": {"arg1": "value1"},
    "id": "unique_id",
    "type": "tool_call"
}

# Invoke
result = my_tool.invoke(tool_call)
```

### 3. LLM with Tools Pattern
```python
# Bind tool to LLM
llm_with_tool = llm.bind_tools([my_tool], tool_choice="any")

# Invoke
response = llm_with_tool.invoke(messages)

# Extract tool call
if response.tool_calls:
    tool_call = response.tool_calls[0]
    args = tool_call["args"]
```

## Common Queries to Test

```bash
# Basic count
python cli.py "How many MSAs are in the dataset?"

# Specific MSA query
python cli.py "What is the average wage in Austin in 2023?"

# Trend analysis
python cli.py "Show wage growth for Austin from 2010 to 2023"

# Comparison
python cli.py "Compare average wages between Austin and San Francisco in 2022"

# State-level
python cli.py "Which Texas MSAs have the highest average wages?"

# Employment
python cli.py "What is the employment level in New York City in 2023?"

# Multi-metric
python cli.py "Show employment and wages for Seattle from 2015 to 2023"
```

## Troubleshooting

### "No module named sql_agent"
```bash
# Make sure you're in project root
cd /home/fortu/GitHub/City-Growth-AI-Agent

# Install in editable mode
pip install -e .
```

### "Could not connect to database"
```bash
# Verify PostgreSQL is running
pg_isready -h localhost -p 5432

# Test connection manually
psql -h localhost -p 5432 -U city_growth_postgres -d postgres
```

### "Tool 'sql_db_query' not found"
```bash
# Check tool creation
python -c "from sql_agent.tools import tools; print([t.name for t in tools])"
```

### "LLM did not generate tool call"
- Check that system prompt is being used
- Verify tool is bound with `tool_choice="any"`
- Check API key is valid

## Performance Expectations

- **list_tables**: ~50ms (database query)
- **get_schema**: ~100ms (database query)
- **generate_query**: ~800-1500ms (LLM call)
- **check_query**: ~600-1000ms (LLM call)
- **run_query**: ~100-500ms (depends on query)
- **analyze_results**: ~800-1500ms (LLM call)

**Total**: ~2.5-4 seconds per query

## Next Steps After Basic Implementation

### Priority Enhancements

1. **Multi-Table Support** (High Priority)
   - Modify `call_get_schema` node to dynamically select tables based on user query
   - Update prompts to handle multiple table joins
   - Add table selection logic using LLM reasoning
   - Test with queries spanning multiple tables

2. **Retry Logic for Failed Queries** (High Priority)
   - Add `num_retries` counter to state tracking
   - Implement conditional edge to retry from `generate_query` on failure
   - Limit retries to 2-3 attempts
   - Include error context in retry messages

3. **Query Result Caching** (Medium Priority)
   - Install caching library: `diskcache` or `redis`
   - Hash SQL queries for cache keys
   - Cache results with TTL (time-to-live)
   - Add cache hit/miss metrics logging

4. **Chart Generation** (Medium Priority)
   - Install `matplotlib` or `plotly`
   - Add `should_visualize` routing logic
   - Create `generate_chart` node for trend queries
   - Save charts to disk or return as base64

5. **REST API with FastAPI** (Low Priority)
   - Install `fastapi` and `uvicorn`
   - Create `/query` POST endpoint
   - Add request validation with Pydantic
   - Implement async query execution
   - Add rate limiting and authentication

6. **Conversation History & Follow-ups** (Low Priority)
   - Add session management with UUIDs
   - Store conversation history in state
   - Enable follow-up questions referencing previous queries
   - Implement context-aware query refinement

## Files Reference

| File | Lines | Purpose |
|------|-------|---------|
| `state.py` | ~20 | State schema |
| `tools.py` | ~30 | Database tools setup |
| `prompts.py` | ~100 | System prompts |
| `nodes.py` | ~200 | Node implementations |
| `agent.py` | ~80 | Graph assembly |
| `cli.py` | ~40 | Command-line interface |
| **Total** | **~470** | Complete agent |

## Debug Tips

### Enable verbose logging
```python
# Add to agent.py
import logging
logging.basicConfig(level=logging.INFO)
```

### Print state at each node
```python
def debug_node(state: SQLAgentState) -> dict:
    print(f"Current state: {state}")
    return {}

builder.add_node("debug", debug_node)
builder.add_edge("generate_query", "debug")
builder.add_edge("debug", "check_query")
```

### Visualize graph
```python
# Requires graphviz
from IPython.display import Image
Image(agent.get_graph().draw_mermaid_png())
```

## Resources

- Full design: `SQL_AGENT_DESIGN.md`
- LangGraph docs: https://langchain-ai.github.io/langgraph/
- Example code: `express_workflow_hts.py` (similar pattern)

Good luck! Start with `state.py` and work through the checklist.
