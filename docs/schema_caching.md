# Schema Caching Decision

## Context

SQL agents typically discover database schema dynamically by calling tools like `sql_db_list_tables` and `sql_db_schema` at the start of each query. This adds latency and token overhead.

## Decision

**We hardcode the schema in the system prompt** instead of discovering it dynamically.

See `sql_agent.py:97-163` for the cached schema.

## Tradeoffs

| Approach | Pros | Cons |
|----------|------|------|
| **Cached (current)** | Faster (~2s saved), fewer tokens, simpler graph | Must update prompt if schema changes |
| **Dynamic** | Adapts to schema changes, works with any database | Slower, more tokens, extra tool calls |

## When to Revisit

Switch to **dynamic schema discovery** if:

1. **Multiple tables** - Agent needs to query across many tables
2. **Schema changes frequently** - Tables/columns added regularly
3. **Generic agent** - Building a reusable agent for unknown databases
4. **Complex joins** - Need to discover foreign key relationships

## How to Re-enable Dynamic Discovery

Add back the schema discovery nodes in `sql_agent.py`:

```python
# 1. Get schema tool
get_schema_tool = next(tool for tool in tools if tool.name == "sql_db_schema")
get_schema_node = ToolNode([get_schema_tool], name="get_schema")

# 2. Add list_tables node
def list_tables(state: MessagesState):
    list_tables_tool = next(tool for tool in tools if tool.name == "sql_db_list_tables")
    # ... invoke tool and return messages

# 3. Add call_get_schema node
def call_get_schema(state: MessagesState):
    llm_with_tools = model.bind_tools([get_schema_tool], tool_choice="any")
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}

# 4. Update graph edges
builder.add_edge(START, "list_tables")
builder.add_edge("list_tables", "call_get_schema")
builder.add_edge("call_get_schema", "get_schema")
builder.add_edge("get_schema", "generate_query")
```

## Current Schema (for reference)

```
Table: msa_wages_employment_data
- area_fips: VARCHAR (MSA identifier)
- year: INTEGER (2000-2024)
- qtr: VARCHAR ('A' = Annual)
- size_code: INTEGER
- size_title: VARCHAR
- annual_avg_estabs_count: INTEGER
- annual_avg_emplvl: INTEGER
- total_annual_wages: BIGINT
- avg_annual_pay: NUMERIC
- annual_avg_wkly_wage: NUMERIC
- area_title: VARCHAR (MSA name)
- state: VARCHAR
```

Last updated: 2025-01-14
