# SQL Agent - Natural Language Database Interface

A LangGraph-based agent that translates natural language questions into SQL queries and provides intelligent analysis of QCEW employment and wage data.

## Overview

This agent uses Google Gemini 2.0 Flash to:
1. Understand natural language questions about MSA (Metropolitan Statistical Area) data
2. Generate correct PostgreSQL queries
3. Validate queries before execution
4. Execute queries safely against the database
5. Analyze results and provide natural language explanations

## Architecture

The agent follows a deterministic workflow graph:

```
START → list_tables → get_schema → generate_query → check_query → run_query → analyze_results → END
```

### Key Design Patterns

1. **Stateful Workflow**: Uses LangGraph for explicit state management
2. **Query Validation**: Second LLM call validates SQL before execution
3. **Error Recovery**: Tracks retries and provides context for corrections
4. **Security First**: Read-only database access, parameterized queries
5. **Modular Design**: Each node is independently testable

## Project Structure

```
City-Growth-AI-Agent/
├── sql_agent/              # Main agent package
│   ├── __init__.py
│   ├── agent.py           # Graph definition and main entry point
│   ├── nodes.py           # Node implementations
│   ├── state.py           # State schema
│   ├── tools.py           # Database tool configuration
│   └── prompts.py         # System prompts for LLM
├── tests/                 # Test suite
│   ├── __init__.py
│   ├── test_agent.py      # Integration tests
│   └── test_nodes.py      # Unit tests
├── cli.py                 # Command-line interface
├── SQL_AGENT_DESIGN.md    # Full design document
├── QUICK_START.md         # Implementation guide
└── README_SQL_AGENT.md    # This file
```

## Installation

### Prerequisites
- Python 3.12+
- PostgreSQL with `msa_wages_employment_data` table
- Google Gemini API key

### Setup

1. **Install dependencies** (already in pyproject.toml):
   ```bash
   uv sync
   # or: pip install -e .
   ```

2. **Configure environment** (already in .env file):
   ```bash
   # Verify these variables are set in .env:
   GEMINI_API_KEY=your_api_key_here
   DB_USER=city_growth_postgres
   DB_PASSWORD=CityGrowthDiagnostics2026
   DB_HOST=localhost
   DB_PORT=5432
   DB_NAME=postgres
   ```

3. **Verify setup**:
   ```bash
   python -c "from sql_agent.agent import run_agent; print('Setup OK')"
   ```

## Usage

### Command Line

```bash
# Basic query
python cli.py "How many rows are in the table?"

# MSA-specific query
python cli.py "What is the average wage in Austin in 2023?"

# Trend analysis
python cli.py "Show wage growth for Austin from 2010 to 2023"

# Comparison
python cli.py "Compare wages between Austin and San Francisco in 2022"

# Verbose mode (shows SQL and results)
python cli.py "What are the top 5 highest-wage MSAs in 2023?" --verbose
```

### Python API

```python
from sql_agent import run_agent

# Run a query
result = run_agent("What is the average wage in Austin in 2023?")

# Access results
print(result['analysis'])   # Natural language explanation
print(result['sql'])        # Generated SQL query
print(result['results'])    # Raw database results
print(result['error'])      # Error message if any
```

### Example Output

```
$ python cli.py "What is the average wage in Austin in 2023?"

======================================================================
SQL AGENT
======================================================================
Query: What is the average wage in Austin in 2023?

Analysis:
----------------------------------------------------------------------
In 2023, the average annual pay in the Austin-Round Rock, TX metro
area was $68,450. This represents the average compensation across all
establishment sizes in the region.

======================================================================
```

## Testing

The SQL agent includes comprehensive unit and integration tests.

### Run All Tests
```bash
pytest tests/ -v
```

### Run Specific Test Suite
```bash
# Integration tests (requires database connection and API key)
pytest tests/test_agent.py -v -m integration

# Unit tests (fast, mocked dependencies)
pytest tests/test_nodes.py -v -m unit
pytest tests/test_tools.py -v -m unit

# All unit tests
pytest tests/ -v -m unit

# Skip slow tests
pytest tests/ -v -m "not slow"
```

### Test Structure
- **`tests/test_nodes.py`** (465 lines) - Unit tests for all nodes
  - `TestGenerateQuery` - SQL generation logic
  - `TestCheckQuery` - Query validation
  - `TestRunQuery` - Query execution and result parsing
  - `TestAnalyzeResults` - Natural language analysis
  - `TestShouldContinue` - Routing logic

- **`tests/test_tools.py`** (235 lines) - Database tool tests
  - `TestDatabaseConnection` - URI construction
  - `TestToolCreation` - Tool initialization
  - `TestDatabaseIntegration` - Real database tests (requires DB)

- **`tests/test_agent.py`** (75 lines) - End-to-end integration tests
  - Basic queries, MSA filtering, trends, comparisons

- **`tests/conftest.py`** - Shared fixtures and mocks

### Test Configuration
See `pytest.ini` for markers and configuration:
- `@pytest.mark.unit` - Fast tests with mocked dependencies
- `@pytest.mark.integration` - Tests requiring database/API
- `@pytest.mark.slow` - Long-running tests

### Coverage Report
```bash
pytest --cov=sql_agent --cov-report=html tests/
open htmlcov/index.html
```

## Database Schema

The agent queries the `msa_wages_employment_data` table:

| Column | Type | Description |
|--------|------|-------------|
| `area_fips` | TEXT | MSA identifier code |
| `year` | INTEGER | Year (2000+) |
| `qtr` | TEXT | Quarter ('A' = Annual average) |
| `area_title` | TEXT | MSA name (e.g., "Austin-Round Rock, TX") |
| `state` | TEXT | State abbreviation |
| `annual_avg_emplvl` | INTEGER | Employment level |
| `avg_annual_pay` | INTEGER | Average annual pay |
| `annual_avg_wkly_wage` | INTEGER | Average weekly wage |
| `total_annual_wages` | BIGINT | Total wages |
| `annual_avg_estabs_count` | INTEGER | Number of establishments |
| `size_code` | TEXT | Establishment size code |
| `size_title` | TEXT | Size category description |

## Query Examples

### Basic Queries
```
"How many MSAs are in the dataset?"
"What is the average wage in Austin in 2023?"
"Show employment levels in New York City in 2022"
```

### Trend Analysis
```
"Show wage trends for Austin from 2010 to 2023"
"How has employment changed in Seattle from 2015 to 2023?"
"What is the wage growth rate for San Francisco?"
```

### Comparisons
```
"Compare wages between Austin and San Francisco in 2022"
"Which has higher employment: Austin or Seattle?"
"Compare Texas MSAs by average wage in 2023"
```

### State-Level Analysis
```
"Which Texas MSAs have the highest wages?"
"Show all California metro areas with over 100k average wage"
"List top 5 MSAs in New York state by employment"
```

## Performance

Typical query execution time: **2.5-4 seconds**

Breakdown:
- `list_tables`: ~50ms (database query)
- `get_schema`: ~100ms (database query)
- `generate_query`: ~1000ms (LLM call)
- `check_query`: ~800ms (LLM call)
- `run_query`: ~200ms (database query)
- `analyze_results`: ~1000ms (LLM call)

### Optimization Tips

1. **Cache schema**: Schema rarely changes, can be cached
2. **Parallel operations**: Some nodes could run in parallel
3. **Skip validation**: For trusted environments, skip `check_query`
4. **Result caching**: Cache common query results

## Error Handling

The agent handles errors gracefully:

### SQL Errors
- Syntax errors → Retry with error context
- Missing columns → Fetch schema again
- Timeout → Suggest narrower query

### Database Errors
- Connection failures → Clear error message
- Permission denied → Suggest credential check
- Query too slow → Add timeout limit

### LLM Errors
- No tool call → End with explanation
- Invalid output → Retry with stricter prompt
- Rate limit → Exponential backoff

## Security

### Database Security
- Uses **read-only** database credentials
- **No DML/DDL** operations (no INSERT, UPDATE, DELETE, DROP)
- **Query timeout** protection (30 seconds)
- **Result size limits** (max 100 rows by default)

### SQL Injection Prevention
- Uses **SQLAlchemy parameterized queries**
- Tool descriptions forbid dangerous operations
- LLM prompted to avoid malicious patterns

### API Key Security
- Never commit `.env` file
- Use environment variables
- Rotate keys regularly

## Troubleshooting

### "No module named sql_agent"
```bash
# Install package in editable mode
pip install -e .
```

### "Could not connect to database"
```bash
# Verify PostgreSQL is running
pg_isready -h localhost -p 5432

# Test connection
psql -h localhost -p 5432 -U city_growth_postgres -d postgres
```

### "ANTHROPIC_API_KEY not set"
```bash
# Check environment
echo $ANTHROPIC_API_KEY

# Or add to .env file
echo "ANTHROPIC_API_KEY=your_key_here" >> .env
```

### "LLM did not generate tool call"
- Verify API key is valid and has credits
- Check that prompts are being passed correctly
- Review LLM temperature (should be 0)

### Slow queries
- Add WHERE clause to filter data
- Reduce date range
- Add LIMIT clause
- Index frequently queried columns

## Extension Ideas

### 1. Multi-Turn Conversations
Enable follow-up questions:
```python
result = run_agent("What is Austin's wage?")
# User: "How about San Francisco?"
# Agent remembers context from previous query
```

### 2. Chart Generation
Add visualization node:
```python
def create_chart(state):
    import matplotlib.pyplot as plt
    # Generate chart from results
```

### 3. Export Results
Add export capabilities:
```python
def export_csv(results, filename):
    import pandas as pd
    df = pd.DataFrame(results)
    df.to_csv(filename)
```

### 4. REST API
Wrap in FastAPI:
```python
from fastapi import FastAPI
app = FastAPI()

@app.post("/query")
async def query(question: str):
    return run_agent(question)
```

## Advanced Usage

### Custom Tools
Add new tools for specialized queries:
```python
from langchain.tools import tool

@tool
def calculate_growth_rate(start_year: int, end_year: int, msa: str) -> float:
    """Calculate wage growth rate between years."""
    # Custom logic here
    return growth_rate
```

### Streaming Results
Stream intermediate results:
```python
for event in agent.stream({"user_query": query}):
    print(f"Node: {event}")
```

### Graph Visualization
Visualize workflow:
```python
from IPython.display import Image
Image(agent.get_graph().draw_mermaid_png())
```

## Documentation

- **Full Design**: See `SQL_AGENT_DESIGN.md` for complete architecture
- **Quick Start**: See `QUICK_START.md` for implementation guide
- **LangGraph Docs**: https://langchain-ai.github.io/langgraph/
- **SQL Tutorial**: https://github.com/langchain-ai/langgraph/blob/main/docs/docs/tutorials/sql/sql-agent.md

## Contributing

### Code Style
- Follow PEP 8
- Add type hints
- Document functions with docstrings
- Keep functions focused (single responsibility)

### Testing
- Write tests for new features
- Maintain >80% code coverage
- Test error cases

### Commit Messages
```
feat: Add multi-turn conversation support
fix: Handle NULL values in wage calculations
docs: Update API examples
test: Add integration tests for comparisons
```

## License

MIT License - see LICENSE file

## Support

For issues or questions:
1. Check `QUICK_START.md` for common setup issues
2. Review `SQL_AGENT_DESIGN.md` for architecture details
3. Run tests to verify installation: `pytest tests/ -v`
4. Check database connection: `python -c "from sql_agent.tools import tools; print(tools)"`

## Acknowledgments

- Built with [LangGraph](https://github.com/langchain-ai/langgraph)
- Uses [Claude Sonnet 4.5](https://www.anthropic.com/claude) by Anthropic
- Data from [BLS QCEW](https://www.bls.gov/cew/)

---

**Status**: Production-ready implementation template
**Version**: 1.0.0
**Last Updated**: 2026-01-12
