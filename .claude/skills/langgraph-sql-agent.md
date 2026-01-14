# Building SQL Agents with LangGraph

This skill covers how to build SQL agents using the LangGraph framework. The agent can query databases, translate natural language to SQL, and perform data analysis (row counts, aggregations, summary statistics, etc.).

## Overview

A LangGraph SQL agent follows this workflow:
1. **List tables** - Discover available tables in the database
2. **Get schema** - Fetch schemas for relevant tables
3. **Generate query** - Create SQL from natural language
4. **Check query** - Validate SQL for common mistakes
5. **Run query** - Execute and return results
6. **Iterate** - Refine queries based on errors or follow-up questions

## Installation

```bash
pip install langgraph langchain langchain-community langchain-anthropic
# Or for OpenAI:
# pip install langchain-openai
```

For database drivers:
```bash
pip install sqlalchemy
# SQLite is built-in, for others:
# pip install psycopg2-binary  # PostgreSQL
# pip install pymysql          # MySQL
```

## Complete Implementation

### 1. Database Connection Setup

```python
from langchain_community.utilities import SQLDatabase

# SQLite
db = SQLDatabase.from_uri("sqlite:///your_database.db")

# PostgreSQL
# db = SQLDatabase.from_uri("postgresql://user:password@localhost:5432/dbname")

# MySQL
# db = SQLDatabase.from_uri("mysql+pymysql://user:password@localhost:3306/dbname")

# Verify connection
print(f"Dialect: {db.dialect}")
print(f"Tables: {db.get_usable_table_names()}")
```

### 2. Initialize LLM and SQL Toolkit

```python
from langchain.chat_models import init_chat_model
from langchain_community.agent_toolkits import SQLDatabaseToolkit

# Initialize LLM (choose your provider)
llm = init_chat_model("anthropic:claude-sonnet-4-20250514", temperature=0)
# Or: llm = init_chat_model("openai:gpt-4o", temperature=0)

# Create toolkit with database tools
toolkit = SQLDatabaseToolkit(db=db, llm=llm)
tools = toolkit.get_tools()

# Available tools:
# - sql_db_list_tables: List all tables
# - sql_db_schema: Get table schemas
# - sql_db_query: Execute SQL queries
# - sql_db_query_checker: Validate SQL syntax
for tool in tools:
    print(f"{tool.name}: {tool.description}\n")
```

### 3. Define System Prompts

```python
# Prompt for generating SQL queries
generate_query_system_prompt = """
You are an agent designed to interact with a SQL database.
Given an input question, create a syntactically correct {dialect} query to run,
then look at the results of the query and return the answer. Unless the user
specifies a specific number of examples they wish to obtain, always limit your
query to at most {top_k} results.

You can order the results by a relevant column to return the most interesting
examples in the database. Never query for all the columns from a specific table,
only ask for the relevant columns given the question.

DO NOT make any DML statements (INSERT, UPDATE, DELETE, DROP etc.) to the database.

For data analysis questions, use appropriate SQL functions:
- COUNT(*) for row counts
- SUM(), AVG(), MIN(), MAX() for aggregations
- GROUP BY for grouping data by columns
- ORDER BY for sorting results
- WHERE for filtering
- HAVING for filtering aggregated results
""".format(
    dialect=db.dialect,
    top_k=10,
)

# Prompt for validating SQL queries
check_query_system_prompt = """
You are a SQL expert with a strong attention to detail.
Double check the {dialect} query for common mistakes, including:
- Using NOT IN with NULL values
- Using UNION when UNION ALL should have been used
- Using BETWEEN for exclusive ranges
- Data type mismatch in predicates
- Properly quoting identifiers
- Using the correct number of arguments for functions
- Casting to the correct data type
- Using the proper columns for joins

If there are any of the above mistakes, rewrite the query. If there are no mistakes,
just reproduce the original query.

You will call the appropriate tool to execute the query after running this check.
""".format(dialect=db.dialect)
```

### 4. Create Graph Nodes

```python
from typing import Literal
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

# Extract individual tools
get_schema_tool = next(tool for tool in tools if tool.name == "sql_db_schema")
run_query_tool = next(tool for tool in tools if tool.name == "sql_db_query")
list_tables_tool = next(tool for tool in tools if tool.name == "sql_db_list_tables")

# Create tool nodes
get_schema_node = ToolNode([get_schema_tool], name="get_schema")
run_query_node = ToolNode([run_query_tool], name="run_query")


def list_tables(state: MessagesState):
    """List all available tables in the database."""
    tool_call = {
        "name": "sql_db_list_tables",
        "args": {},
        "id": "list_tables_call",
        "type": "tool_call",
    }
    tool_call_message = AIMessage(content="", tool_calls=[tool_call])
    tool_message = list_tables_tool.invoke(tool_call)
    response = AIMessage(f"Available tables: {tool_message.content}")
    return {"messages": [tool_call_message, tool_message, response]}


def call_get_schema(state: MessagesState):
    """Call the LLM to decide which table schemas to fetch."""
    llm_with_tools = llm.bind_tools([get_schema_tool], tool_choice="any")
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}


def generate_query(state: MessagesState):
    """Generate a SQL query based on the user's question."""
    system_message = {
        "role": "system",
        "content": generate_query_system_prompt,
    }
    # Allow model to respond naturally or generate a query
    llm_with_tools = llm.bind_tools([run_query_tool])
    response = llm_with_tools.invoke([system_message] + state["messages"])
    return {"messages": [response]}


def check_query(state: MessagesState):
    """Validate the generated SQL query for common mistakes."""
    system_message = {
        "role": "system",
        "content": check_query_system_prompt,
    }
    # Extract the query from the last tool call
    tool_call = state["messages"][-1].tool_calls[0]
    user_message = {"role": "user", "content": tool_call["args"]["query"]}

    llm_with_tools = llm.bind_tools([run_query_tool], tool_choice="any")
    response = llm_with_tools.invoke([system_message, user_message])
    response.id = state["messages"][-1].id
    return {"messages": [response]}
```

### 5. Define Routing Logic

```python
def should_continue(state: MessagesState) -> Literal["check_query", "__end__"]:
    """Determine whether to check query or end the conversation."""
    messages = state["messages"]
    last_message = messages[-1]

    # If no tool calls, the model is responding to the user
    if not last_message.tool_calls:
        return END
    else:
        return "check_query"
```

### 6. Assemble the Graph

```python
# Build the state graph
builder = StateGraph(MessagesState)

# Add nodes
builder.add_node(list_tables)
builder.add_node(call_get_schema)
builder.add_node(get_schema_node, "get_schema")
builder.add_node(generate_query)
builder.add_node(check_query)
builder.add_node(run_query_node, "run_query")

# Add edges
builder.add_edge(START, "list_tables")
builder.add_edge("list_tables", "call_get_schema")
builder.add_edge("call_get_schema", "get_schema")
builder.add_edge("get_schema", "generate_query")
builder.add_conditional_edges("generate_query", should_continue)
builder.add_edge("check_query", "run_query")
builder.add_edge("run_query", "generate_query")

# Compile the agent
agent = builder.compile()
```

### 7. Run the Agent

```python
def query_database(question: str) -> str:
    """Query the database with a natural language question."""
    result = agent.invoke({"messages": [{"role": "user", "content": question}]})
    return result["messages"][-1].content


# Example queries for data analysis
print(query_database("How many rows are in the employees table?"))
print(query_database("What is the total sales per year?"))
print(query_database("Show me summary statistics for the salary column"))
print(query_database("What are the top 5 products by quantity sold?"))
```

### 8. Streaming Output (Optional)

```python
def stream_query(question: str):
    """Stream the agent's response for better UX."""
    for chunk in agent.stream(
        {"messages": [{"role": "user", "content": question}]},
        stream_mode="values"
    ):
        if "messages" in chunk:
            last_msg = chunk["messages"][-1]
            if hasattr(last_msg, "content") and last_msg.content:
                print(last_msg.content)
```

## Alternative: Simple ReAct Agent

For simpler use cases, use the prebuilt ReAct agent:

```python
from langgraph.prebuilt import create_react_agent

system_prompt = """
You are an agent designed to interact with a SQL database.
Given an input question, create a syntactically correct {dialect} query to run,
then look at the results of the query and return the answer.

Always:
1. First list the available tables
2. Get the schema of relevant tables
3. Generate and validate your query
4. Execute and explain the results

DO NOT make any DML statements (INSERT, UPDATE, DELETE, DROP etc.).
""".format(dialect=db.dialect)

simple_agent = create_react_agent(
    llm,
    tools,
    prompt=system_prompt,
)

# Use it
result = simple_agent.invoke({
    "messages": [{"role": "user", "content": "How many customers do we have?"}]
})
print(result["messages"][-1].content)
```

## Common Data Analysis Queries

The agent can handle various analytical questions:

| Question Type | Example |
|--------------|---------|
| Row counts | "How many rows are in the orders table?" |
| Aggregations | "What is the average order value?" |
| Grouping | "Show sales by region" |
| Time series | "What are monthly sales for 2024?" |
| Top N | "Top 10 customers by revenue" |
| Filtering | "Orders over $1000 from California" |
| Joins | "List customers with their total orders" |
| Statistics | "Min, max, avg salary by department" |

## Security Best Practices

1. **Use read-only database connections** when possible
2. **Limit table access** with `include_tables` parameter:
   ```python
   db = SQLDatabase.from_uri(uri, include_tables=["safe_table1", "safe_table2"])
   ```
3. **Set row limits** to prevent large result sets
4. **Never allow DML** - the system prompt explicitly forbids this
5. **Validate user input** before passing to the agent

## Troubleshooting

### Common Issues

1. **"Unknown column" errors**: The agent should automatically use `sql_db_schema` to check columns
2. **Slow queries**: Add indexes to your database or limit result sets
3. **Connection errors**: Verify your database URI and credentials
4. **Timeout errors**: Increase timeout or optimize queries

### Debugging

```python
# Visualize the graph
from IPython.display import Image, display
display(Image(agent.get_graph().draw_mermaid_png()))

# Verbose streaming to see each step
for step in agent.stream(
    {"messages": [{"role": "user", "content": "your question"}]},
    stream_mode="updates"
):
    print(step)
    print("---")
```

## References

- [LangGraph SQL Agent Tutorial](https://langchain-ai.github.io/langgraph/tutorials/sql-agent/)
- [LangChain SQL Agent Docs](https://python.langchain.com/docs/tutorials/sql_qa/)
- [SQLDatabase API Reference](https://python.langchain.com/api_reference/community/utilities/langchain_community.utilities.sql_database.SQLDatabase.html)
