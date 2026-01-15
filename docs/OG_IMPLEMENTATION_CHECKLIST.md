# SQL Agent Implementation Checklist

A step-by-step checklist for the junior developer to implement the SQL agent.

## Pre-Implementation Setup

- [ ] Read `QUICK_START.md` (10 minutes)
- [ ] Skim `SQL_AGENT_DESIGN.md` (20 minutes)
- [ ] Review `ARCHITECTURE_DECISIONS.md` (optional, 15 minutes)

**Estimated time**: 30-45 minutes

---

## Phase 1: Environment Setup (30 minutes)

### Database Setup
- [ ] Verify PostgreSQL is running: `pg_isready -h localhost -p 5432`
- [ ] Test database connection:
  ```bash
  psql -h localhost -p 5432 -U city_growth_postgres -d postgres
  ```
- [ ] Verify table exists:
  ```sql
  \dt msa_wages_employment_data
  SELECT COUNT(*) FROM msa_wages_employment_data;
  ```

### API Key Setup
- [ ] Get Anthropic API key from https://console.anthropic.com/
- [ ] Add to `.env` file:
  ```bash
  echo "ANTHROPIC_API_KEY=your_key_here" >> .env
  ```
- [ ] Verify key works:
  ```bash
  python -c "import anthropic; print('OK')"
  ```

### Dependencies
- [ ] Verify dependencies are installed:
  ```bash
  uv sync
  # or: pip install langgraph langchain langchain-community langchain-anthropic sqlalchemy psycopg2-binary python-dotenv
  ```

---

## Phase 2: Core Implementation (2.5 hours)

### Step 1: State Definition (15 minutes)
- [ ] File: `sql_agent/state.py` ✅ (already created)
- [ ] Review the `SQLAgentState` TypedDict
- [ ] Understand each field's purpose
- [ ] No code changes needed (template is complete)

**Verification**:
```bash
python -c "from sql_agent.state import SQLAgentState; print('State OK')"
```

---

### Step 2: Tools Setup (20 minutes)
- [ ] File: `sql_agent/tools.py` ✅ (already created)
- [ ] Review database connection setup
- [ ] Test tool creation:
  ```bash
  python -c "from sql_agent.tools import tools; print([t.name for t in tools])"
  ```
- [ ] Expected output: `['sql_db_list_tables', 'sql_db_schema', 'sql_db_query']`

**Troubleshooting**:
- If connection fails, check `.env` credentials
- If tools don't load, verify SQLAlchemy is installed

---

### Step 3: Prompts Configuration (15 minutes)
- [ ] File: `sql_agent/prompts.py` ✅ (already created)
- [ ] Review `SYSTEM_PROMPT` for SQL generation
- [ ] Review `CHECK_QUERY_PROMPT` for validation
- [ ] Review `ANALYSIS_PROMPT` for result interpretation
- [ ] Optionally customize prompts for your use case

**No verification needed** (prompts are just strings)

---

### Step 4: Node Implementation (60 minutes)

All nodes are already implemented in `sql_agent/nodes.py` ✅

Review each node:

#### Node 1: list_tables (5 min)
- [ ] Read the implementation
- [ ] Understand programmatic tool invocation
- [ ] Note: No LLM call, just direct tool use

#### Node 2: call_get_schema (5 min)
- [ ] Read the implementation
- [ ] See how it fetches table schema
- [ ] Note: Hardcoded to `msa_wages_employment_data`

#### Node 3: generate_query (15 min)
- [ ] Read the implementation
- [ ] Understand LLM invocation with tools
- [ ] See how retry context is added
- [ ] Note: Uses `tool_choice="any"` to force tool call

#### Node 4: check_query (15 min)
- [ ] Read the implementation
- [ ] Understand validation logic
- [ ] See how query is rewritten if needed
- [ ] Note: Second LLM call for safety

#### Node 5: analyze_results (10 min)
- [ ] Read the implementation
- [ ] See how results are formatted for LLM
- [ ] Understand analysis generation
- [ ] Note: Handles empty results gracefully

#### Routing Logic: should_continue (5 min)
- [ ] Read the conditional routing function
- [ ] Understand when to validate vs end
- [ ] See type hints for Literal return type

**Verification**:
```bash
python -c "from sql_agent.nodes import list_tables, generate_query; print('Nodes OK')"
```

---

### Step 5: Graph Assembly (30 minutes)
- [ ] File: `sql_agent/agent.py` ✅ (already created)
- [ ] Review graph construction in `build_graph()`
- [ ] Understand node order:
  ```
  START → list_tables → call_get_schema → get_schema →
  generate_query → [conditional] → check_query → run_query →
  analyze_results → END
  ```
- [ ] Review the `run_agent()` wrapper function
- [ ] Understand initial state setup

**Verification**:
```bash
python -c "from sql_agent.agent import agent; print('Graph OK')"
```

---

### Step 6: CLI Interface (15 minutes)
- [ ] File: `cli.py` ✅ (already created)
- [ ] Make executable: `chmod +x cli.py`
- [ ] Review argparse setup
- [ ] Understand verbose mode flag
- [ ] Review output formatting

**Verification**:
```bash
python cli.py --help
```

Expected output: Usage instructions

---

## Phase 3: Testing (45 minutes)

### Unit Tests (15 minutes)
- [ ] File: `tests/test_nodes.py` ✅ (already created)
- [ ] Review test structure
- [ ] Run unit tests:
  ```bash
  pytest tests/test_nodes.py -v
  ```
- [ ] Some tests are skipped (require API calls)

### Integration Tests (30 minutes)
- [ ] File: `tests/test_agent.py` ✅ (already created)
- [ ] Review test cases:
  - [ ] Basic count query
  - [ ] MSA-specific query
  - [ ] Trend analysis
  - [ ] Comparison query
  - [ ] Employment query
  - [ ] State-level query

- [ ] Run all tests:
  ```bash
  pytest tests/ -v
  ```

**Expected**: 6 tests pass (or 5 if one is skipped)

---

## Phase 4: End-to-End Validation (30 minutes)

### Test Query 1: Simple Count
```bash
python cli.py "How many rows are in the table?"
```
- [ ] Query completes successfully
- [ ] SQL is generated
- [ ] Analysis makes sense
- [ ] No errors

### Test Query 2: MSA Filter
```bash
python cli.py "What is the average wage in Austin in 2023?"
```
- [ ] Filters by Austin correctly (uses ILIKE)
- [ ] Filters by year 2023
- [ ] Adds qtr = 'A' automatically
- [ ] Returns reasonable wage number

### Test Query 3: Trend Analysis
```bash
python cli.py "Show wage trends for Austin from 2010 to 2023" --verbose
```
- [ ] Returns multiple years
- [ ] Ordered by year ASC
- [ ] Shows SQL query in verbose mode
- [ ] Analysis describes the trend

### Test Query 4: Comparison
```bash
python cli.py "Compare wages between Austin and San Francisco in 2022"
```
- [ ] Includes both MSAs
- [ ] Uses OR condition
- [ ] Groups by area_title
- [ ] Analysis compares the two

### Test Query 5: Error Handling
```bash
python cli.py "asdfasdf nonsense query"
```
- [ ] Doesn't crash
- [ ] Provides helpful error message
- [ ] OR generates best-effort query

---

## Phase 5: Documentation Review (15 minutes)

- [ ] Read `README_SQL_AGENT.md` for usage examples
- [ ] Bookmark `SQL_AGENT_DESIGN.md` for detailed reference
- [ ] Review `ARCHITECTURE_DECISIONS.md` to understand tradeoffs

---

## Phase 6: Optional Enhancements (1-2 hours)

Pick one or more:

### Enhancement 1: Add Retry Logic
- [ ] Add retry counter to state
- [ ] Implement retry routing in graph
- [ ] Test with intentionally bad queries
- [ ] Document retry behavior

### Enhancement 2: Add Result Caching
- [ ] Install caching library (e.g., diskcache)
- [ ] Hash queries for cache keys
- [ ] Cache query results
- [ ] Add cache hit/miss logging

### Enhancement 3: Add Chart Generation
- [ ] Install matplotlib
- [ ] Add `create_chart` node
- [ ] Generate charts for trend queries
- [ ] Save to file or display

### Enhancement 4: Create REST API
- [ ] Install FastAPI
- [ ] Create `/query` endpoint
- [ ] Add request validation
- [ ] Add response formatting
- [ ] Test with curl or Postman

---

## Success Criteria

You've successfully completed the implementation when:

- [x] All test files are created
- [ ] All tests pass (`pytest tests/ -v`)
- [ ] CLI runs successfully with sample queries
- [ ] No database connection errors
- [ ] SQL queries are valid and execute
- [ ] Analysis is helpful and accurate
- [ ] Documentation is clear and complete

---

## Common Issues and Solutions

### Issue 1: "No module named sql_agent"
**Solution**:
```bash
pip install -e .
# or add to PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:/home/fortu/GitHub/City-Growth-AI-Agent"
```

### Issue 2: "Could not connect to database"
**Solution**:
```bash
# Check PostgreSQL is running
pg_isready -h localhost -p 5432

# Test connection manually
psql -h localhost -p 5432 -U city_growth_postgres -d postgres

# Verify credentials in .env
cat .env | grep DATABASE
```

### Issue 3: "ANTHROPIC_API_KEY not found"
**Solution**:
```bash
# Check .env file
cat .env | grep ANTHROPIC

# Or export directly
export ANTHROPIC_API_KEY=your_key_here

# Verify it's set
echo $ANTHROPIC_API_KEY
```

### Issue 4: "LLM did not generate tool call"
**Solution**:
- Verify API key has credits
- Check model name is correct: `claude-sonnet-4-5-20250929`
- Review system prompt is being passed
- Check temperature is 0

### Issue 5: Tests fail with database errors
**Solution**:
- Verify table exists: `\dt msa_wages_employment_data`
- Check user has SELECT permission
- Verify data exists: `SELECT COUNT(*) FROM msa_wages_employment_data;`

### Issue 6: Slow query performance
**Solution**:
- Add indexes on frequently queried columns
- Reduce result limit
- Add more specific WHERE clauses
- Check query plan with EXPLAIN

---

## Timeline Estimate

| Phase | Time | Cumulative |
|-------|------|------------|
| Pre-reading | 45 min | 45 min |
| Environment setup | 30 min | 1h 15min |
| Core implementation | 2.5 hours | 3h 45min |
| Testing | 45 min | 4h 30min |
| E2E validation | 30 min | 5h |
| Documentation | 15 min | 5h 15min |
| **Total** | **5h 15min** | |

Add 1-2 hours if implementing optional enhancements.

---

## Next Steps After Completion

1. **Commit your work**:
   ```bash
   git add sql_agent/ tests/ cli.py
   git commit -m "feat: Implement LangGraph SQL agent"
   ```

2. **Share with team**:
   - Demo the CLI to stakeholders
   - Document any custom prompts or configurations
   - Share common query examples

3. **Production readiness**:
   - Add monitoring/logging
   - Set up error alerting
   - Configure rate limits
   - Add authentication if exposing as API

4. **Iterate**:
   - Collect user feedback
   - Identify common query patterns
   - Optimize prompts based on usage
   - Add caching for frequent queries

---

## Resources

- Full design: `/home/fortu/GitHub/City-Growth-AI-Agent/SQL_AGENT_DESIGN.md`
- Quick reference: `/home/fortu/GitHub/City-Growth-AI-Agent/QUICK_START.md`
- Architecture decisions: `/home/fortu/GitHub/City-Growth-AI-Agent/ARCHITECTURE_DECISIONS.md`
- Usage guide: `/home/fortu/GitHub/City-Growth-AI-Agent/README_SQL_AGENT.md`
- LangGraph docs: https://langchain-ai.github.io/langgraph/

---

## Completion Checklist

- [ ] Environment is set up
- [ ] All files are created
- [ ] Tests pass
- [ ] CLI works
- [ ] Documentation is read
- [ ] At least 3 different query types tested successfully
- [ ] Error handling verified
- [ ] Code is committed to git

**Congratulations!** You've successfully implemented a production-ready LangGraph SQL agent.

---

**Created**: 2026-01-12
**Version**: 1.0.0
**Estimated Completion Time**: 5-6 hours for complete implementation
