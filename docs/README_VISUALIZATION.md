# Visualization Agent - User Guide

## Overview

The Visualization Agent extends the SQL Agent with powerful data visualization capabilities. It can:
- Generate SQL queries from natural language
- Create interactive Plotly visualizations
- Save HTML charts to the `/viz` directory
- Provide insightful text analysis
- Handle both simple answers and complex visualizations

## Quick Start

### Basic Usage

```bash
# Text-based query
uv run visualization_agent.py "What is the average wage in Austin in 2023?"

# Visualization query
uv run visualization_agent.py "Create a line chart showing wage trends for Austin from 2010 to 2024"

# Don't save HTML to /viz directory
uv run visualization_agent.py "Show me a bar chart of top 10 MSAs by wages" --no-save
```

### Example Output

```
Initializing Visualization Agent...
Question: Create a line chart showing wage trends for Austin from 2010 to 2024

================================================================================
ANALYSIS:
================================================================================
The chart displays the average annual pay over a 15-year period...

Key insights:
• There is generally an upward trend in average annual pay over the 15-year period
• The rate of salary increase appears to vary; some years show more significant jumps
• From 2020-2023, there was accelerated wage growth

================================================================================

✓ Visualization saved to: viz/abc123_output.html
Execution time: 5.53 seconds
```

## Architecture

### Data Flow

```
User Question
    ↓
Intent Classification (LLM) → ["answer", "visualize", "multi_chart"]
    ↓
SQL Query Generation
    ↓
Query Execution → Data saved to CSV (for visualizations)
    ↓
[If visualize/multi_chart]
    ↓
Plotly Code Generation (with structured output)
    ↓
Code Execution (with error recovery, max 3 attempts)
    ↓
Analysis Generation
    ↓
HTML saved to /viz/
```

### Key Components

1. **workspace.py** - Isolated job workspaces for each visualization
2. **tools.py** - Data handoff mechanism (CSV file passing)
3. **models.py** - Pydantic models for structured LLM output
4. **prompts.py** - System prompts for intent classification and code generation
5. **visualization_nodes.py** - LangGraph nodes for the workflow
6. **validator.py** - Code security validation
7. **runner.py** - Safe code execution with error recovery
8. **state.py** - Enhanced state definition with reducers
9. **visualization_agent.py** - Main agent implementation

### File Structure

```
City-Growth-AI-Agent/
├── sql_agent.py                    # Original SQL agent
├── visualization_agent.py          # Enhanced agent with viz
├── workspace.py                    # Job workspace management
├── tools.py                        # Data handoff tools
├── prompts.py                      # System prompts
├── models.py                       # Pydantic models
├── runner.py                       # Code execution
├── validator.py                    # Code validation
├── state.py                        # State definitions
├── visualization_nodes.py          # Workflow nodes
├── viz/                            # HTML visualizations output
│   └── {job_id}_output.html
├── tests/
│   ├── test_handoff.py            # Phase 1 tests
│   ├── test_code_generation.py   # Phase 2 tests
│   ├── test_runner.py             # Phase 3 tests
│   └── test_visualization_agent.py # Integration tests
└── test_performance.py            # Performance benchmarks
```

## Features

### 1. Intelligent Intent Classification

The agent automatically determines if you want:
- **Text answer**: "What is the average wage in Austin?"
- **Single visualization**: "Create a line chart of wage trends"
- **Multiple charts**: "Show wages AND employment trends"

### 2. Data Handoff (No Context Stuffing)

For large datasets, results are saved to CSV files instead of being stuffed into the LLM context:
- Small results (<50 rows): Returned in context
- Large results or visualizations: Saved to CSV
- Prevents token limit errors and reduces costs

### 3. Structured Output with Pydantic

All LLM outputs use Pydantic models:
- Intent classification
- Plotly code generation
- Analysis generation

This eliminates fragile string parsing and ensures consistency.

### 4. Error Recovery

If generated code fails, the system automatically:
1. Identifies the error
2. Asks the LLM to fix it
3. Retries execution (up to 3 attempts)

### 5. Security Validation

Generated code is validated to prevent:
- Dangerous imports (os, sys, subprocess, etc.)
- Missing required functions (pd.read_csv, write_html)
- Syntax errors

### 6. Performance Monitoring

Each job tracks timing for:
- SQL execution
- Code generation
- Code execution
- Analysis generation

## Supported Chart Types

### Time Series
- Line charts: `px.line()`
- Area charts: `px.area()`

### Comparisons
- Bar charts (horizontal recommended): `px.bar(orientation='h')`
- Grouped bar charts

### Distributions
- Histograms: `px.histogram()`
- Box plots: `px.box()`
- Violin plots: `px.violin()`

### Correlations
- Scatter plots: `px.scatter()`
- Bubble charts

### Rankings
- Horizontal bar charts (preferred for readability)

## Testing

### Run All Tests

```bash
./run_all_tests.sh
```

### Run Specific Test Suites

```bash
# Phase 1: Data handoff
uv run python tests/test_handoff.py

# Phase 2: Code generation
uv run python tests/test_code_generation.py

# Phase 3: Code execution
uv run python tests/test_runner.py

# Integration tests
uv run python tests/test_visualization_agent.py

# Performance tests
uv run python test_performance.py
```

## Performance Metrics

Typical execution times:
- Text queries: **3-4 seconds**
- Simple visualizations: **5-6 seconds**
- Complex visualizations: **7-10 seconds**

Breakdown:
- SQL execution: 10-50ms
- Intent classification: 500-1000ms
- Code generation: 1-2 seconds
- Code execution: 1-2 seconds
- Analysis: 1-2 seconds

## Configuration

### Environment Variables

```bash
# Database (required)
DB_USER=city_growth_postgres
DB_PASSWORD=YourPassword
DB_HOST=localhost
DB_PORT=5432
DB_NAME=postgres

# API Keys (required)
GEMINI_API_KEY=your_key_here

# Optional
MODEL_OVERRIDE=google_genai:gemini-2.0-flash
SKIP_COLUMN_VALIDATION=false  # Set to true to disable validation
```

### Customization

You can customize visualization rules by editing:
- `prompts.py` - System prompts for code generation
- `validator.py` - Security rules and blocked imports
- `runner.py` - Execution timeout and retry limits

## Troubleshooting

### No visualization generated

Check:
1. Intent classification: Is it "visualize" or "multi_chart"?
2. SQL results: Are there rows returned?
3. Code execution: Check for errors in workspace meta.json

### Code execution fails

- Check `/tmp/viz_jobs/{job_id}/script.py` for generated code
- Check `/tmp/viz_jobs/{job_id}/meta.json` for errors
- Error recovery attempts up to 3 times

### Performance issues

- Enable column validation skip: `SKIP_COLUMN_VALIDATION=true`
- Use faster model: `MODEL_OVERRIDE=google_genai:gemini-2.0-flash`
- Cleanup old workspaces: `cleanup_old_workspaces()`

## Advanced Usage

### Programmatic Use

```python
from visualization_agent import classify_single

# Get result with visualization
result = classify_single(
    "Create a line chart of Austin wages 2010-2024",
    save_viz=True
)

print(f"Intent: {result['intent']}")
print(f"Chart type: {result['chart_type']}")
print(f"HTML path: {result['artifact_path']}")
print(f"Analysis: {result['analysis']}")
```

### Workspace Cleanup

```python
from workspace import cleanup_old_workspaces

# Remove workspaces older than 24 hours
cleaned = cleanup_old_workspaces(max_age_hours=24)
print(f"Cleaned {cleaned} workspaces")
```

## Next Steps

1. **Add custom visualization rules** in `prompts.py` (e.g., color schemes, chart formatting)
2. **Extend chart types** by updating `GENERATE_PLOTLY_PROMPT`
3. **Add caching** for frequently requested visualizations
4. **Implement batch processing** for multiple questions
5. **Add export formats** (PNG, PDF) alongside HTML

## Support

For issues or questions:
- Check logs in `/tmp/viz_jobs/{job_id}/meta.json`
- Review test files for examples
- Consult `thinking/VISUALIZATION_IMPLEMENTATION_PLAN.md` for architecture details
