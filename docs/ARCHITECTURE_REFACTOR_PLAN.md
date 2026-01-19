# Architecture Refactor Plan: Hybrid Subagent System

**Status:** Planning Phase - Not Yet Approved
**Created:** 2026-01-18
**Motivation:** Current deterministic workflow failed on complex analytical requests (CAGR calculation)

---

## Current Architecture (Deterministic Workflow)

```
START
  │
  ▼
classify_intent ──► validate_request ──► generate_query ──► run_query
                                                               │
                    ┌──────────────────────────────────────────┘
                    ▼
              route_by_intent
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
  analyze_results         validate_columns
        │                       │
        ▼                       ▼
       END                generate_plotly ──► execute_code ──► analyze_artifact
                                                                     │
                                                                     ▼
                                                                    END
```

### Problems with Current Architecture

1. **Rigid Flow:** Each node executes exactly once, no iteration
2. **No Self-Correction:** If SQL is wrong, workflow proceeds anyway
3. **Complex Request Failure:** Cannot decompose multi-step analytical tasks
4. **Single LLM Call per Phase:** No reasoning or exploration

---

## Proposed Architecture: Hybrid Subagent System

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         ORCHESTRATOR                                     │
│                  (Deterministic high-level flow)                        │
│                                                                         │
│   ┌──────────────┐     ┌──────────────┐     ┌──────────────┐           │
│   │  classify    │────►│  validate    │────►│  SQL_AGENT   │           │
│   │  intent      │     │  request     │     │  (agentic)   │           │
│   └──────────────┘     └──────────────┘     └──────┬───────┘           │
│                                                     │                   │
│                                                     ▼                   │
│                                              ┌──────────────┐           │
│                                              │  VIZ_AGENT   │           │
│                                              │  (agentic)   │           │
│                                              └──────┬───────┘           │
│                                                     │                   │
│                                                     ▼                   │
│                                              ┌──────────────┐           │
│                                              │  analyze     │           │
│                                              │  artifact    │           │
│                                              └──────────────┘           │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## SQL_AGENT Design

### Goal
Transform user request into correct, validated SQL result data.

### Tools Available
| Tool | Description |
|------|-------------|
| `query_db` | Execute SQL query and return results |
| `check_schema` | Get table schema and column info |
| `sample_data` | Get sample rows from a table |
| `validate_result` | Check if result matches user intent |

### Agent Loop (ReAct Pattern)
```
1. THINK: What SQL do I need to answer this question?
2. ACT: Execute query using query_db tool
3. OBSERVE: Check results - do they answer the question?
4. THINK: Is this correct? Do I need to refine?
5. REPEAT until satisfied or max_turns (3-4)
```

### Example: CAGR Request
```
User: "CAGR of employment for Boston, NYC, LA between 2014 and 2024"

Agent Turn 1:
  THINK: I need 2014 and 2024 employment data for these cities
  ACT: query_db("SELECT area_title, year, annual_avg_emplvl
                 FROM msa_wages_employment_data
                 WHERE area_title ILIKE ANY(ARRAY['%Boston%', '%New York%', '%Los Angeles%'])
                 AND year IN (2014, 2024) AND qtr = 'A'")
  OBSERVE: Got 6 rows (3 cities × 2 years) ✓

Agent Turn 2:
  THINK: Now I need to calculate CAGR: ((end/start)^(1/10) - 1) * 100
  ACT: query_db("WITH city_data AS (
                   SELECT area_title,
                          MAX(CASE WHEN year = 2014 THEN annual_avg_emplvl END) as emp_2014,
                          MAX(CASE WHEN year = 2024 THEN annual_avg_emplvl END) as emp_2024
                   FROM msa_wages_employment_data
                   WHERE area_title ILIKE ANY(ARRAY['%Boston%', '%New York%', '%Los Angeles%'])
                   AND year IN (2014, 2024) AND qtr = 'A'
                   GROUP BY area_title
                 )
                 SELECT area_title,
                        ROUND((POWER(emp_2024::numeric / emp_2014, 0.1) - 1) * 100, 2) as cagr_pct
                 FROM city_data")
  OBSERVE: Got 3 rows with CAGR values ✓

Agent DONE: Data ready for visualization
```

---

## VIZ_AGENT Design

### Goal
Generate working Plotly visualization from the data.

### Tools Available
| Tool | Description |
|------|-------------|
| `generate_code` | Generate Plotly Python code |
| `execute_code` | Run the code in sandbox |
| `fix_code` | Fix code based on error message |
| `read_output` | Check if HTML output exists and is valid |

### Agent Loop
```
1. THINK: What chart type fits this data?
2. ACT: generate_code for bar/line/scatter
3. ACT: execute_code
4. OBSERVE: Did it succeed?
5. If error: fix_code and retry
6. REPEAT until success or max_turns (3)
```

---

## State Changes

```python
# Current state (simplified)
class VisualizationState(TypedDict):
    messages: Annotated[list, add_messages]
    intent: str
    generated_sql: str
    # ... single values

# Proposed state (subagent-aware)
class VisualizationState(TypedDict):
    messages: Annotated[list, add_messages]
    intent: str

    # SQL Agent state
    sql_agent_turns: List[AgentTurn]  # Full reasoning trace
    sql_agent_status: Literal["running", "success", "failed"]
    validated_data: Optional[DataFrame]

    # Viz Agent state
    viz_agent_turns: List[AgentTurn]
    viz_agent_status: Literal["running", "success", "failed"]

    # Shared
    workspace: JobWorkspace
```

---

## Implementation Options

### Option 1: LangGraph Subgraphs
- Use LangGraph's native subgraph feature
- Each agent is a compiled subgraph with its own state
- Orchestrator invokes subgraphs as nodes

### Option 2: LangChain AgentExecutor
- Use `create_react_agent` for each subagent
- Wrap in LangGraph nodes
- More flexible tool calling

### Option 3: Custom Agent Loop
- Implement ReAct loop manually in Python
- Full control over reasoning and tool calls
- Most work but most flexible

**Recommendation:** Start with Option 1 (LangGraph Subgraphs) for cleaner integration.

---

## Cost Analysis

| Metric | Current | Subagent |
|--------|---------|----------|
| LLM Calls per request | 4-6 | 8-15 |
| Avg latency | 15-25s | 30-60s |
| Token usage | ~2000 | ~5000 |
| Complex request success | Low | High |

---

## Migration Path

1. **Phase 1 (Quick Fix - Current):** Add SQL review node + iterative loop
2. **Phase 2:** Extract SQL logic into SQL_AGENT subgraph
3. **Phase 3:** Extract Viz logic into VIZ_AGENT subgraph
4. **Phase 4:** Add tool library and agent memory

---

## Open Questions

1. Should agents share a common tool library or have separate tools?
2. How to handle agent timeouts? (user waiting for 60s+ is bad UX)
3. Should we add streaming for real-time progress updates?
4. How to persist agent reasoning traces for debugging?

---

## Files to Modify (When Implementing)

| File | Changes |
|------|---------|
| `state.py` | Add agent turn tracking, status fields |
| `visualization_agent.py` | Replace single nodes with subgraph calls |
| `sql_agent.py` (new) | SQL agent with tools and loop |
| `viz_agent.py` (new) | Visualization agent with tools and loop |
| `agent_tools.py` (new) | Shared tool definitions |

---

## Decision Required

Before implementing Phase 2+, we need to decide:

1. **Subagent implementation approach** (LangGraph subgraphs vs AgentExecutor vs custom)
2. **Acceptable latency increase** (is 45-60s OK for complex requests?)
3. **Streaming requirement** (should we show progress as agents work?)

---

*This document will be updated after the quick fix is implemented and tested.*
