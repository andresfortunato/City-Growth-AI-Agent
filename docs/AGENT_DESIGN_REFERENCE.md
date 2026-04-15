# Agent Design Reference: From Workflow to Conversational Agent

**Purpose:** Synthesis of architecture patterns from Vanna, Bagofwords, eosho/langchain_data_agent, and Superset — focused on what matters when replacing a deterministic LangGraph workflow with a conversation-based agent that has tool access.

**Sources:** VANNA_VS_CITY_GROWTH_AI_ANALYSIS.md, DIAGNOSTIC_ANALYSIS.md, Implementation Plan - GEMINI.md, DIAGNOSTIC_REPORT GEMINI.md, DIAGNOSTIC_ANALYSIS EXTERNAL.md, BAGOFWORDS_AGENT_DESIGN.md

---

## 1. Why Move Away from Deterministic Workflows

The current City Growth AI uses a LangGraph StateGraph: a fixed sequence of nodes with conditional edges. This works for simple queries but breaks on complex analytical requests (e.g., CAGR calculations) because:

- **Fixed node order** — each node runs once in sequence; no iteration
- **No reasoning** — the graph dictates flow, not the LLM
- **No exploration** — the agent cannot inspect data, adjust, and retry
- **Brittle routing** — conditional edges are programmer-defined, not LLM-decided

The SQL review loop we added is a band-aid: it adds iteration but within a still-rigid graph.

**Core insight:** LangGraph supports BOTH patterns. The framework docs explicitly state: "Workflows have predetermined code paths... Agents are dynamic and define their own processes and tool usage." We don't need to abandon LangGraph — we need to use its agent pattern alongside the existing workflow pattern.

---

## 2. The ReAct Loop: Core Pattern

The ReAct (Reasoning + Acting) loop is the standard agent pattern. **LangGraph supports this natively** — it's not just for workflows. The LangGraph docs explicitly distinguish:

> "Workflows have predetermined code paths and are designed to operate in a certain order. Agents are dynamic and define their own processes and tool usage."

### LangGraph Agent Implementation (Graph API)

This is the canonical agent pattern in LangGraph — a loop where the LLM decides tools:

```python
from langgraph.graph import StateGraph, MessagesState, START, END

def llm_call(state: MessagesState):
    """LLM decides whether to call a tool or not"""
    return {
        "messages": [
            llm_with_tools.invoke(
                [SystemMessage(content=system_prompt)]
                + state["messages"]
            )
        ]
    }

def tool_node(state: MessagesState):
    """Executes whatever tools the LLM chose"""
    result = []
    for tool_call in state["messages"][-1].tool_calls:
        tool = tools_by_name[tool_call["name"]]
        observation = tool.invoke(tool_call["args"])
        result.append(ToolMessage(content=observation, tool_call_id=tool_call["id"]))
    return {"messages": result}

def should_continue(state: MessagesState):
    """Route: if LLM made tool calls, execute them; otherwise, done"""
    if state["messages"][-1].tool_calls:
        return "tool_node"
    return END

# Build the agent graph
builder = StateGraph(MessagesState)
builder.add_node("llm_call", llm_call)
builder.add_node("tool_node", tool_node)
builder.add_edge(START, "llm_call")
builder.add_conditional_edges("llm_call", should_continue, ["tool_node", END])
builder.add_edge("tool_node", "llm_call")  # Loop back!
agent = builder.compile()
```

**This is a loop, not a pipeline.** The `tool_node → llm_call` edge creates the cycle. The LLM decides when to stop (no more tool calls).

### LangGraph Functional API (Alternative)

```python
from langgraph.func import entrypoint, task

@task
def call_llm(messages: list):
    return llm_with_tools.invoke([SystemMessage(content=prompt)] + messages)

@task
def call_tool(tool_call):
    tool = tools_by_name[tool_call["name"]]
    return tool.invoke(tool_call)

@entrypoint()
def agent(messages: list):
    llm_response = call_llm(messages).result()

    while True:
        if not llm_response.tool_calls:
            break
        tool_results = [call_tool(tc).result() for tc in llm_response.tool_calls]
        messages = add_messages(messages, [llm_response, *tool_results])
        llm_response = call_llm(messages).result()

    return add_messages(messages, llm_response)
```

### LangChain v1 High-Level API (create_agent)

The newest API — `create_agent` replaces `create_react_agent` (deprecated in LangGraph v1):

```python
from langchain.agents import create_agent

agent = create_agent(
    model="gemini-2.0-flash",
    tools=[query_db, check_schema, sample_data, generate_chart],
    system_prompt="You are a data analyst with access to QCEW employment data..."
)

result = agent.invoke({
    "messages": [{"role": "user", "content": user_question}]
})
```

Benefits of `create_agent`:
- Built on LangGraph (same runtime, tracing, persistence)
- **Middleware system** for customization (PII redaction, summarization, human-in-the-loop)
- Automatic streaming, checkpointing, time travel

### Comparison: Workflow vs Agent (Both in LangGraph)

| Aspect | LangGraph Workflow (current) | LangGraph Agent (proposed) |
|--------|------------------------------|---------------------------|
| Flow control | Fixed graph edges | LLM decides next step |
| Iteration | Explicit loop edges needed | Built into `tool_node → llm_call` cycle |
| Tool selection | Fixed per node | LLM chooses dynamically |
| Termination | Reaches END node | LLM decides "done" (no tool calls) |
| Error handling | Per-node try/catch | Agent reasons about errors |
| Runtime | LangGraph | LangGraph (same!) |
| Tracing | LangSmith | LangSmith (same!) |

### Reference Implementations from Other Systems

**Bagofwords** (custom loop, no framework):
```python
for loop_index in range(step_limit):
    context = context_hub.build()
    plan = planner.think(context)
    if plan.is_final_answer:
        return plan.answer
    result = tool_runner.execute(plan.tool_call)
    context_hub.add_observation(result)
```

**Vanna** (custom loop, no framework):
```python
messages = [system_prompt, user_message]
while True:
    response = llm.chat(messages, tools=tool_schemas)
    if not response.tool_calls:
        return response.content
    for tool_call in response.tool_calls:
        result = execute_tool(tool_call)
        messages.append(tool_result_message(result))
```

Both achieve the same pattern as LangGraph's agent, but without the runtime benefits (persistence, streaming, tracing).

### LangGraph SQL Agent (Official Tutorial)

LangGraph has a **dedicated SQL agent tutorial** that implements exactly what we need:
- `list_tables` node → `get_schema` node → `generate_query` node → `check_query` node → `run_query` node
- Uses `MessagesState` with tool call routing
- Supports human-in-the-loop via `interrupt()` before query execution
- Streams intermediate results

---

## 3. Tool System Design

### Tool Registry with Auto-Discovery (Bagofwords)

Tools are Python classes that self-register. The agent discovers them at startup:

```python
class Tool(ABC):
    name: str
    description: str          # LLM reads this to decide when to use
    input_schema: dict        # JSON Schema for tool arguments
    output_schema: dict       # Structured output format
    retry_policy: RetryPolicy # How to handle failures
    timeout: int              # Per-tool timeout
    access_groups: list       # Permission control
```

Benefits:
- **Add tools without modifying agent code** — just create a new Tool subclass
- **Schema-driven validation** — inputs/outputs validated before/after execution
- **Policy-based execution** — each tool declares its own retry/timeout behavior

### Tool Categories for Data Analytics Agent

From the reference docs, the essential tools are:

| Tool | Purpose | Notes |
|------|---------|-------|
| `query_db` | Execute SQL and return results | Core tool — most used |
| `check_schema` | Get table/column metadata | Prevents hallucinated columns |
| `sample_data` | Get N sample rows from a table | Helps LLM understand data shape |
| `list_tables` | Show available tables | Orientation for multi-table DBs |
| `generate_chart` | Create Plotly visualization | Takes data + chart spec |
| `execute_code` | Run Python in sandbox | For complex calculations |
| `save_artifact` | Persist output (HTML, CSV) | Workspace management |

### Tool-as-Subagent Pattern (Bagofwords)

Complex tools can invoke their own LLM:

```
Agent calls "generate_chart" tool
  └── Tool internally creates a Coder subagent
        └── Coder generates Plotly code (own LLM call)
        └── Coder executes code
        └── Coder fixes errors (own retry loop)
        └── Returns chart HTML to parent agent
```

This keeps the main agent loop clean while allowing deep tool specialization.

---

## 4. Context Management

### Two-Tier Caching (Bagofwords ContextHub)

Context is expensive to build and critical for quality. Bagofwords splits it:

**Static Cache** (built once at startup, reused across all requests):
- Database schema (tables, columns, types, relationships)
- System instructions and prompt templates
- Example queries and patterns

**Warm Cache** (rebuilt per iteration):
- Conversation messages
- Tool observations from current session
- Current workspace state

```
ContextHub
├── Static Builders (run once)
│   ├── SchemaBuilder      → table/column metadata
│   ├── InstructionBuilder → system prompts
│   └── ExampleBuilder     → few-shot examples
│
└── Warm Builders (run per iteration)
    ├── MessageBuilder     → conversation history
    ├── ObservationBuilder → tool results
    └── WorkspaceBuilder   → current artifacts
```

### Parallel Context Construction

Bagofwords runs all 12 context builders in parallel (async), reducing context assembly from sequential to concurrent. This is a significant latency optimization.

### Memory-Guided Decision Making (Vanna)

Vanna stores successful query patterns:
```
User asked: "wage trends for Austin" → SQL: "SELECT year, avg_annual_pay FROM ... WHERE area_title ILIKE '%Austin%'"
```

On new similar requests, retrieve past successful patterns as few-shot examples. This creates a learning feedback loop without fine-tuning.

---

## 5. Error Handling and Recovery

### Error Classification (Bagofwords)

Not all errors are equal. Classify them to choose the right recovery strategy:

| Error Type | Strategy | Example |
|------------|----------|---------|
| `transient` | Retry with backoff | Network timeout, rate limit |
| `validation` | Fix input and retry | Invalid SQL syntax |
| `permanent` | Abort and explain | Table doesn't exist |
| `rate_limit` | Wait and retry | API quota exceeded |

### Retry Policies

```python
class RetryPolicy:
    max_retries: int = 3
    base_delay: float = 1.0
    backoff_factor: float = 2.0    # exponential backoff
    jitter: bool = True            # prevent thundering herd
    retryable_errors: list         # which error types to retry
```

### Timeout Tiers

Three-level timeout prevents stalled operations:
1. **Start timeout** — tool must begin producing output within N seconds
2. **Idle timeout** — no new output for N seconds → kill
3. **Hard timeout** — absolute maximum execution time

### Circuit Breakers

Prevent infinite loops:
- **Step limit** — max N iterations of the main loop
- **Failed tool count** — abort after N consecutive tool failures
- **Repeated action detection** — if agent calls the same tool with same args, force different approach

---

## 6. Streaming and User Feedback

### Why Streaming Matters

Current City Growth AI: user waits 20-40s with no feedback ("blind waiting"). All reference systems implement streaming.

### Streaming Architecture (Bagofwords)

```
Agent Loop
  ├── Planner streams tokens as LLM generates them
  │     └── SSE events: {"type": "thinking", "content": "I need to..."}
  ├── Tool execution emits progress events
  │     └── SSE events: {"type": "tool_start", "tool": "query_db"}
  │     └── SSE events: {"type": "tool_result", "rows": 7}
  └── Final answer streams
        └── SSE events: {"type": "answer", "content": "The CAGR..."}
```

### Partial JSON Parsing

Bagofwords' planner parses incomplete JSON from the LLM stream progressively:
- As the LLM generates `{"tool": "query_db", "args": {"q` ...
- The parser extracts what's available so far
- UI shows "Planning: query_db..." before the full response arrives

### Console Streaming (Practical First Step)

Before full SSE, a simpler approach (from Implementation Plan - GEMINI.md):
```python
print("[1/5] Classifying intent...")
print("[2/5] Generating SQL query...")
print("[3/5] Executing query... (7 rows)")
print("[4/5] Generating visualization...")
print("[5/5] Analyzing results...")
```

---

## 7. Semantic Layer

### Why a Semantic Layer (from DIAGNOSTIC_ANALYSIS EXTERNAL.md)

The LLM should not need to know raw SQL column names. A semantic layer maps human concepts to database columns:

```yaml
datasets:
  - name: msa_wages_employment
    table: msa_wages_employment_data
    metrics:
      employment:
        column: annual_avg_emplvl
        description: "Total employment level (annual average)"
      wages:
        column: avg_annual_pay
        description: "Average annual pay per employee"
      weekly_wage:
        column: annual_avg_wkly_wage
        description: "Average weekly wage"
    dimensions:
      city:
        column: area_title
        description: "Metropolitan Statistical Area name"
      year:
        column: year
        type: temporal
    constraints:
      - "Always filter qtr = 'A' for annual data"
      - "Use ILIKE with wildcards for area_title"
```

Benefits:
- LLM asks for "employment" not "annual_avg_emplvl"
- Constraints are enforced automatically (qtr = 'A')
- Adding new datasets doesn't require prompt changes
- Multi-dataset expansion becomes possible

### Entity Resolution (Deterministic, Not LLM)

City name matching should NOT depend on the LLM:

```python
# Deterministic entity resolver
resolve("NYC")       → "New York-Newark-Jersey City, NY-NJ-PA"
resolve("LA")        → "Los Angeles-Long Beach-Anaheim, CA"
resolve("DC")        → "Washington-Arlington-Alexandria, DC-VA-MD-WV"
```

Build a lookup table from the database. LLM handles intent; deterministic code handles entity resolution. This prevents the fuzzy ILIKE failures.

---

## 8. Hybrid Architecture: Workflow + Agent

### The Core Insight

Not every request needs an agent. Simple, predictable queries should use the fast deterministic workflow. Complex, multi-step requests should use the agent loop. Both paths share the same tools and infrastructure.

```
User Request
     │
     ▼
┌────────────────────┐
│  COMPLEXITY ROUTER  │  (part of intent classification)
│  simple | complex   │
└────┬──────────┬─────┘
     │          │
     ▼          ▼
┌─────────┐  ┌──────────────────────────────────┐
│ WORKFLOW │  │         AGENT (ReAct loop)        │
│ (fast)   │  │  plan → execute → observe → loop  │
│          │  │                                    │
│ Fixed    │  │  LLM decides tools, iteration,     │
│ nodes    │  │  termination                        │
└────┬─────┘  └──────────────┬───────────────────┘
     │                       │
     │   ┌───────────────┐   │
     └──►│ SHARED TOOLS  │◄──┘
         │ query_db      │
         │ generate_chart│
         │ execute_code  │
         │ save_artifact │
         └───────────────┘
```

### When to Use Each Path

| Signal | Workflow (fast) | Agent (flexible) |
|--------|----------------|-----------------|
| Single metric, single city | Yes | |
| Time series trend | Yes | |
| Top-N ranking | Yes | |
| Calculations (CAGR, growth) | | Yes |
| Multi-step comparisons | | Yes |
| Derived metrics | | Yes |
| Ambiguous requests | | Yes |
| "Explore" or "analyze" language | | Yes |

### Complexity Classification

Add a `complexity` field to the intent classifier:

```python
class IntentClassification(BaseModel):
    intent: Literal["answer", "visualize", "multi_chart"]
    complexity: Literal["simple", "complex"]  # NEW
    complexity_reasoning: str                  # NEW
    chart_types: list[str]
    num_charts: int
    reasoning: str
```

**Simple indicators:** single metric, single or few cities, direct column lookup, standard chart
**Complex indicators:** calculations (growth, CAGR, ratio), many entities, multi-step logic, derived metrics, exploration language

### Graceful Escalation

If the workflow path fails (SQL review rejects after max attempts), escalate to the agent:

```
Workflow attempt → SQL review FAIL (3x) → escalate to Agent loop
```

This means the workflow path is never a dead end — it falls back to the more capable agent path. The user gets fast results for simple queries and correct results for complex ones.

### Shared Infrastructure

Both paths use the same:
- **Database connection** and query execution
- **Tool implementations** (query_db, generate_chart, etc.)
- **Workspace management** (data.csv, output.html)
- **Logging and tracing** (LangSmith, JSONL logs)
- **Error classification** and retry policies

The only difference is **who decides what to do next** — the graph edges (workflow) or the LLM (agent).

---

## 9. Full Agent Architecture (for Complex Path)

Based on all reference docs, the agent architecture for the complex path:

```
┌─────────────────────────────────────────────────────────────────┐
│                    CONVERSATIONAL AGENT                         │
│                                                                 │
│  User Message                                                   │
│       │                                                         │
│       ▼                                                         │
│  ┌─────────────────────┐                                        │
│  │    CONTEXT HUB      │  Static: schema, instructions, examples│
│  │  (two-tier cache)   │  Warm: messages, observations          │
│  └─────────┬───────────┘                                        │
│            │                                                     │
│            ▼                                                     │
│  ┌─────────────────────┐      ┌──────────────────┐             │
│  │   PLANNER (LLM)     │◄────►│  TOOL REGISTRY   │             │
│  │  ReAct reasoning    │      │  - query_db      │             │
│  │  Streaming output   │      │  - check_schema  │             │
│  └─────────┬───────────┘      │  - sample_data   │             │
│            │                   │  - generate_chart│             │
│            ▼                   │  - execute_code  │             │
│  ┌─────────────────────┐      │  - save_artifact │             │
│  │   TOOL RUNNER       │◄────►│                  │             │
│  │  Policy-based exec  │      └──────────────────┘             │
│  │  Error classification│                                       │
│  │  Retry with backoff │                                        │
│  └─────────┬───────────┘                                        │
│            │                                                     │
│            ▼                                                     │
│  ┌─────────────────────┐                                        │
│  │   OBSERVATION       │  Tool results feed back into context   │
│  │   (loop back)       │  LLM decides: iterate or finish        │
│  └─────────────────────┘                                        │
│                                                                  │
│  Guards: step_limit=10, failed_tool_limit=3, timeout=120s       │
└─────────────────────────────────────────────────────────────────┘
```

### Key Design Decisions

1. **LangGraph for both paths** — workflow graph for simple requests, agent graph for complex ones; same runtime, tracing, and persistence
2. **LLM decides flow (agent path)** — planner chooses tools; no hard-coded routing
3. **Tools are self-contained** — each tool has schema, validation, retry policy
4. **Subagents for complex tools** — chart generation delegates to a Coder subagent (can be LangGraph subgraph)
5. **Semantic layer** — LLM talks in concepts, resolver maps to SQL
6. **Deterministic entity resolution** — city/state lookup is code, not LLM
7. **Streaming throughout** — LangGraph provides built-in streaming support
8. **Memory** — store successful patterns, retrieve as few-shot examples
9. **Middleware** — use `create_agent` middleware for summarization, guardrails, context management

### Migration Path

| Phase | Focus | Key Changes |
|-------|-------|-------------|
| **0** | Complexity router + semantic layer | Add complexity classification, YAML config, entity lookup |
| **1** | ReAct agent loop (complex path) | Custom agent loop with tool calling alongside existing workflow |
| **2** | Tool system | Shared registry, policies, subagents used by both paths |
| **3** | Context hub | Two-tier caching, parallel builders |
| **4** | Streaming | SSE events at every stage |
| **5** | Memory | Pattern storage and retrieval |
| **6** | Graceful escalation | Workflow → Agent fallback on failure |
| **7** | Production hardening | Circuit breakers, monitoring, eval suite |

---

## 10. Key Patterns to Adopt

### From Vanna
- **Tool iteration with LLM control** — LLM decides when to stop, not the graph
- **Memory-guided tool args** — retrieve past successful queries for similar requests
- **Provider-agnostic LLM interface** — swap models without code changes
- **7 extensibility points** — lifecycle hooks, middleware, error recovery, context enrichers

### From Bagofwords
- **5-step ReAct loop** — observe, think, check, act, observe
- **ContextHub with 12 builders** — parallel context assembly
- **ToolRunner with policies** — retry, timeout, error classification per tool
- **Streaming at every level** — planner tokens, tool progress, final answer
- **Subagent pattern** — Coder, Judge, Answer as specialized sub-agents

### From eosho/langchain_data_agent
- **SQL validation chain** — validate query before execution
- **Intent routing** — different handling for different query types

### From Superset
- **Semantic layer** — datasets, metrics, dimensions, constraints in YAML
- **Async job execution** — long queries run in background with polling
- **Role-based access** — tools gated by user permissions

---

## 11. Anti-Patterns to Avoid

1. **LLM for entity resolution** — Use deterministic lookup, not ILIKE guessing
2. **Full data in context** — Schema only; save data to files (current approach is correct)
3. **Single-shot SQL** — Always allow iteration; complex queries rarely work first try
4. **Silent failures** — Classify errors, log them, surface to user
5. **Batch-only output** — Stream progress; 20s blind waiting kills UX
6. **Monolithic prompts** — Separate concerns: planning prompt, tool prompts, analysis prompt
7. **Workflow for everything** — Use workflow for simple paths, agent for complex ones; LangGraph supports both
8. **No memory** — Same mistakes repeated; store and retrieve successful patterns

---

## 12. Numerical Correctness Framework

From DIAGNOSTIC_ANALYSIS EXTERNAL.md — critical for a data analytics agent:

1. **SQL generates the number** — all calculations happen in SQL, not Python
2. **Agent quotes verbatim** — the narrative must use exact numbers from query results
3. **Post-check assertion** — compare numbers in the narrative against the raw data
4. **Fail loudly** — if numbers don't match, flag it rather than silently proceeding

```
SQL returns: Austin CAGR = 3.95%
Agent narrative says: "Austin grew at 3.95% CAGR"
Post-check: 3.95 == 3.95 ✓
```

---

*This document synthesizes patterns from 6 reference analyses. It should be used as a blueprint when implementing the conversational agent architecture described in docs/ARCHITECTURE_REFACTOR_PLAN.md.*
