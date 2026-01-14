# Visualization Agent Implementation Plan

**For Junior Developers**  
**Last Updated:** January 2026

---

## Summary

We are developing an ai agent for data analysis and visualization of urban economic data in the US (starting with employment, wages, and number of establishments by MSA in 2000-2024). We'll develop a langgraph workflow to test different agent's versions, capabilities, and workflows. So far we have a @sql_agent.py and want to expand the workflow's capabilities and role to be able to produce data visualizations from the data it's connected to, by adding one or more nodes to the script with the capacity to analyze the data, run python scripts, and create plotly graphs. This will result in an LLM-powered **Data Analyst Agent application**.


## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Architecture Overview](#2-architecture-overview)
3. [Key Concepts](#3-key-concepts)
4. [Implementation Phases](#4-implementation-phases)
5. [Phase 1: Data Handoff Mechanism](#5-phase-1-data-handoff-mechanism)
6. [Phase 2: Visualization Code Generation](#6-phase-2-visualization-code-generation)
7. [Phase 3: Code Execution (Runner)](#7-phase-3-code-execution-runner)
8. [Phase 4: Integration & Testing](#8-phase-4-integration--testing)
9. [File Structure](#9-file-structure)
10. [Common Pitfalls](#10-common-pitfalls)
11. [Testing Checklist](#11-testing-checklist)

---

## 1. Problem Statement

### What We Have

A working SQL agent (`sql_agent.py`) that:
- Takes natural language questions
- Generates SQL queries
- Executes them against Postgres
- Returns natural language analysis

### What We Need

Extend the agent to:
- Generate data visualizations (Plotly charts)
- Handle large datasets without crashing
- Return chart artifacts (HTML files) alongside text analysis

### The Critical Problem: Context Stuffing

**Current behavior (BROKEN for large data):**
```
User: "Show wage trends for all 400 MSAs from 2000-2024"
     ↓
SQL returns 10,000 rows as TEXT
     ↓
Agent tries to stuff 10K rows into LLM context
     ↓
💥 Token limit exceeded OR $20+ API cost OR hallucinated code
```

**Required behavior (FILE PASSING):**
```
User: "Show wage trends for all 400 MSAs from 2000-2024"
     ↓
SQL returns 10,000 rows → SAVED TO CSV FILE
     ↓
Agent receives: "Data saved to /tmp/job_123/data.csv with columns: [year, area_title, avg_annual_pay]"
     ↓
Agent generates: df = pd.read_csv('/tmp/job_123/data.csv')
     ↓
✅ Works regardless of data size
```

---

## 2. Architecture Overview

### High-Level Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         ENHANCED SQL AGENT                              │
│                                                                         │
│  START                                                                  │
│    ↓                                                                    │
│  classify_intent ──→ ["answer", "visualize"]                           │
│    ↓                                                                    │
│  generate_query                                                         │
│    ↓                                                                    │
│  check_query                                                            │
│    ↓                                                                    │
│  run_query_with_handoff ←── NEW: Saves to CSV if visualization         │
│    ↓                                                                    │
│  ┌─────────────────────────────────────────┐                           │
│  │ if intent == "answer":                  │                           │
│  │   → analyze_results → END               │                           │
│  │                                         │                           │
│  │ if intent == "visualize":               │                           │
│  │   → generate_plotly_code                │                           │
│  │   → execute_code (subprocess)           │                           │
│  │   → analyze_with_artifact → END         │                           │
│  └─────────────────────────────────────────┘                           │
└─────────────────────────────────────────────────────────────────────────┘
```

### Data Flow for Visualization

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Postgres   │────→│  CSV File    │────→│ Python Code  │────→│  HTML Chart  │
│  (10K rows)  │     │ (workspace)  │     │ (reads CSV)  │     │  (artifact)  │
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
        │                   │                    │                    │
        │                   │                    │                    │
   SQL Tool            File Path            LLM generates        Returned to
   executes            + Schema             pd.read_csv()        user/UI
```

---

## 3. Key Concepts

### 3.1 Job Workspace

Every visualization request gets an isolated directory:

```
/tmp/viz_jobs/
└── job_abc123/
    ├── data.csv          # SQL results
    ├── script.py         # Generated Plotly code
    ├── output.html       # Chart artifact
    └── meta.json         # Execution metadata
```

**Why?**
- Isolation: Jobs don't interfere with each other
- Debugging: Can inspect failed jobs
- Cleanup: Easy to delete old jobs

### 3.2 Data Handoff

The SQL tool returns DIFFERENT outputs based on intent:

| Intent | SQL Tool Returns | Token Cost |
|--------|------------------|------------|
| `answer` | Raw rows as text (for small results) | ~500 tokens |
| `visualize` | File path + column schema | ~50 tokens |

### 3.3 Artifacts

An artifact is any file generated by the agent:
- `output.html` - Plotly interactive chart
- `output.png` - Static image (optional)
- `summary.csv` - Processed data (optional)

Artifacts are **first-class citizens** — they're stored, tracked, and returned separately from text responses.

---

## 4. Implementation Phases

| Phase | Goal | Duration | Deliverable |
|-------|------|----------|-------------|
| **Phase 1** | Data Handoff | 1-2 days | Modified SQL tool that saves to CSV |
| **Phase 2** | Code Generation | 2-3 days | New node that generates Plotly code |
| **Phase 3** | Code Execution | 1-2 days | Subprocess runner with error handling |
| **Phase 4** | Integration | 1-2 days | End-to-end testing with 10+ questions |

**Total: ~1 week**

---

## 5. Phase 1: Data Handoff Mechanism

### Goal

Modify the SQL execution to save results to a file when visualization is needed.

### 5.1 Create the Workspace Manager

Create a new file: `workspace.py`

```python
"""
workspace.py - Job workspace management for visualization tasks

Each visualization job gets an isolated directory with:
- data.csv: SQL query results
- script.py: Generated Python code
- output.html: Plotly chart artifact
- meta.json: Job metadata and timing
"""

import os
import json
import uuid
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, asdict

# Base directory for all job workspaces
WORKSPACE_BASE = Path("/tmp/viz_jobs")


@dataclass
class JobWorkspace:
    """Represents an isolated workspace for a visualization job."""
    job_id: str
    path: Path
    created_at: str
    
    @property
    def data_path(self) -> Path:
        return self.path / "data.csv"
    
    @property
    def script_path(self) -> Path:
        return self.path / "script.py"
    
    @property
    def output_path(self) -> Path:
        return self.path / "output.html"
    
    @property
    def meta_path(self) -> Path:
        return self.path / "meta.json"


def create_workspace() -> JobWorkspace:
    """
    Create a new isolated workspace for a visualization job.
    
    Returns:
        JobWorkspace with unique ID and directory paths
    
    Example:
        workspace = create_workspace()
        # workspace.path = /tmp/viz_jobs/abc123/
        # workspace.data_path = /tmp/viz_jobs/abc123/data.csv
    """
    job_id = uuid.uuid4().hex[:8]
    job_path = WORKSPACE_BASE / job_id
    job_path.mkdir(parents=True, exist_ok=True)
    
    workspace = JobWorkspace(
        job_id=job_id,
        path=job_path,
        created_at=datetime.now().isoformat()
    )
    
    # Write initial metadata
    with open(workspace.meta_path, 'w') as f:
        json.dump(asdict(workspace), f, default=str, indent=2)
    
    return workspace


def cleanup_workspace(workspace: JobWorkspace) -> None:
    """Remove a workspace directory and all its contents."""
    if workspace.path.exists():
        shutil.rmtree(workspace.path)


def cleanup_old_workspaces(max_age_hours: int = 24) -> int:
    """
    Remove workspaces older than max_age_hours.
    
    Returns:
        Number of workspaces cleaned up
    """
    if not WORKSPACE_BASE.exists():
        return 0
    
    cleaned = 0
    cutoff = datetime.now().timestamp() - (max_age_hours * 3600)
    
    for job_dir in WORKSPACE_BASE.iterdir():
        if job_dir.is_dir():
            meta_file = job_dir / "meta.json"
            if meta_file.exists():
                try:
                    with open(meta_file) as f:
                        meta = json.load(f)
                    created = datetime.fromisoformat(meta["created_at"]).timestamp()
                    if created < cutoff:
                        shutil.rmtree(job_dir)
                        cleaned += 1
                except (json.JSONDecodeError, KeyError):
                    pass
    
    return cleaned
```

### 5.2 Create the Data Handoff Tool

Create a new file: `tools.py` (or add to existing)

```python
"""
tools.py - Enhanced SQL tool with data handoff capability

The key insight: LLMs should reason about SCHEMA, not DATA.
For visualization, we save results to CSV and return only the schema.
"""

import csv
from typing import Literal
from langchain_community.utilities import SQLDatabase
from workspace import create_workspace, JobWorkspace


def execute_query_with_handoff(
    db: SQLDatabase,
    query: str,
    intent: Literal["answer", "visualize"],
    max_rows_in_context: int = 50
) -> dict:
    """
    Execute SQL query with smart data handoff.
    
    For 'answer' intent: Returns rows in context (for small results)
    For 'visualize' intent: Saves to CSV, returns only schema
    
    Args:
        db: SQLDatabase instance
        query: SQL query to execute
        intent: "answer" for text response, "visualize" for charts
        max_rows_in_context: Max rows to return in context (answer mode)
    
    Returns:
        dict with keys:
        - success: bool
        - row_count: int
        - columns: list[str]
        - data_preview: str (first few rows, for LLM context)
        - workspace: JobWorkspace (only for visualize intent)
        - error: str (if failed)
    
    Example (answer intent):
        result = execute_query_with_handoff(db, "SELECT ...", "answer")
        # result["data_preview"] = "year,wage\\n2020,65000\\n2021,68000\\n..."
    
    Example (visualize intent):
        result = execute_query_with_handoff(db, "SELECT ...", "visualize")
        # result["workspace"].data_path = "/tmp/viz_jobs/abc123/data.csv"
        # result["columns"] = ["year", "area_title", "avg_annual_pay"]
    """
    try:
        # Execute query and get results
        raw_result = db.run(query)
        
        # Parse the result (SQLDatabase returns string representation)
        # This is a simplified parser - adjust based on actual db.run() output format
        rows = _parse_sql_result(raw_result)
        
        if not rows:
            return {
                "success": True,
                "row_count": 0,
                "columns": [],
                "data_preview": "No results returned",
                "workspace": None,
                "error": None
            }
        
        columns = list(rows[0].keys()) if rows else []
        row_count = len(rows)
        
        # For small results or answer intent, return in context
        if intent == "answer" or row_count <= max_rows_in_context:
            preview = _format_rows_for_context(rows[:max_rows_in_context])
            return {
                "success": True,
                "row_count": row_count,
                "columns": columns,
                "data_preview": preview,
                "workspace": None,
                "error": None
            }
        
        # For visualize intent with large data, save to file
        workspace = create_workspace()
        
        with open(workspace.data_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        
        # Return only schema + preview (NOT full data)
        preview = _format_rows_for_context(rows[:5])  # Just 5 rows for context
        
        return {
            "success": True,
            "row_count": row_count,
            "columns": columns,
            "data_preview": f"[{row_count} rows saved to {workspace.data_path}]\n\nPreview (first 5 rows):\n{preview}",
            "workspace": workspace,
            "error": None
        }
        
    except Exception as e:
        return {
            "success": False,
            "row_count": 0,
            "columns": [],
            "data_preview": "",
            "workspace": None,
            "error": str(e)
        }


def _parse_sql_result(raw_result: str) -> list[dict]:
    """
    Parse SQLDatabase.run() output into list of dicts.
    
    NOTE: SQLDatabase.run() returns different formats depending on configuration.
    Adjust this function based on your actual output format.
    """
    # If result is already a list of tuples/dicts, handle that
    if isinstance(raw_result, list):
        if raw_result and isinstance(raw_result[0], dict):
            return raw_result
        # Handle list of tuples - would need column names
        return []
    
    # If result is a string representation, parse it
    # This is a placeholder - actual parsing depends on db.run() format
    import ast
    try:
        parsed = ast.literal_eval(raw_result)
        if isinstance(parsed, list):
            return parsed
    except (ValueError, SyntaxError):
        pass
    
    return []


def _format_rows_for_context(rows: list[dict], max_chars: int = 2000) -> str:
    """Format rows as readable text for LLM context."""
    if not rows:
        return "No data"
    
    # CSV-like format
    columns = list(rows[0].keys())
    lines = [",".join(columns)]
    
    for row in rows:
        line = ",".join(str(row.get(col, "")) for col in columns)
        lines.append(line)
        
        # Stop if we're getting too long
        if sum(len(l) for l in lines) > max_chars:
            lines.append(f"... ({len(rows) - len(lines) + 1} more rows)")
            break
    
    return "\n".join(lines)
```

### 5.3 Testing Phase 1

Create `test_handoff.py`:

```python
"""Test the data handoff mechanism."""
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from langchain_community.utilities import SQLDatabase
from tools import execute_query_with_handoff
from workspace import create_workspace, cleanup_workspace

load_dotenv()

def get_test_db():
    """Create test database connection."""
    db_uri = f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    engine = create_engine(db_uri)
    return SQLDatabase(engine)

def test_small_result_answer_mode():
    """Small results should return data in context."""
    db = get_test_db()
    result = execute_query_with_handoff(
        db,
        "SELECT year, avg_annual_pay FROM msa_wages_employment_data WHERE area_title ILIKE '%Austin%' AND qtr = 'A' LIMIT 5",
        intent="answer"
    )
    
    assert result["success"]
    assert result["row_count"] == 5
    assert result["workspace"] is None  # No file needed
    assert "2020" in result["data_preview"] or "2021" in result["data_preview"]
    print("✓ Small result answer mode works")

def test_large_result_visualize_mode():
    """Large results should save to CSV."""
    db = get_test_db()
    result = execute_query_with_handoff(
        db,
        "SELECT year, area_title, avg_annual_pay FROM msa_wages_employment_data WHERE qtr = 'A'",
        intent="visualize"
    )
    
    assert result["success"]
    assert result["row_count"] > 100
    assert result["workspace"] is not None
    assert result["workspace"].data_path.exists()
    
    # Verify CSV has correct columns
    import csv
    with open(result["workspace"].data_path) as f:
        reader = csv.DictReader(f)
        row = next(reader)
        assert "year" in row
        assert "area_title" in row
        assert "avg_annual_pay" in row
    
    # Cleanup
    cleanup_workspace(result["workspace"])
    print(f"✓ Large result visualize mode works ({result['row_count']} rows saved)")

def test_workspace_lifecycle():
    """Test workspace creation and cleanup."""
    workspace = create_workspace()
    
    assert workspace.path.exists()
    assert workspace.job_id is not None
    
    # Write a test file
    with open(workspace.data_path, 'w') as f:
        f.write("test,data\n1,2")
    
    assert workspace.data_path.exists()
    
    # Cleanup
    cleanup_workspace(workspace)
    assert not workspace.path.exists()
    print("✓ Workspace lifecycle works")

if __name__ == "__main__":
    test_workspace_lifecycle()
    test_small_result_answer_mode()
    test_large_result_visualize_mode()
    print("\n✅ All Phase 1 tests passed!")
```

Run with:
```bash
uv run python test_handoff.py
```

---

## 6. Phase 2: Visualization Code Generation

### Goal

Create a node that generates Plotly code based on:
- User's visualization request
- Column schema (NOT raw data)
- File path to CSV

### 6.1 Plotly Code Generation Prompt

Create `prompts.py` (add to existing or create new):

```python
"""
prompts.py - System prompts for visualization agent

Key principle: The LLM sees SCHEMA, not DATA.
It generates code that reads from the CSV file.
"""

GENERATE_PLOTLY_PROMPT = """
You are an expert data visualization developer using Plotly and pandas.

TASK: Generate Python code to create a Plotly visualization.

CRITICAL RULES:
1. ALWAYS start with: df = pd.read_csv('{data_path}')
2. NEVER hardcode data values - always read from the CSV
3. ALWAYS save the figure: fig.write_html('{output_path}')
4. Use plotly.express (px) for simple charts, plotly.graph_objects (go) for complex ones
5. Add clear titles, axis labels, and legends
6. Use appropriate chart types for the data

AVAILABLE COLUMNS: {columns}
ROW COUNT: {row_count}
DATA PREVIEW:
{data_preview}

USER REQUEST: {user_request}

CHART TYPE GUIDELINES:
- Time series (year on x-axis): Use px.line()
- Comparisons (categories): Use px.bar()
- Distributions: Use px.histogram() or px.box()
- Correlations: Use px.scatter()
- Rankings: Use px.bar() with horizontal orientation
- Geographic: Use px.choropleth() (if state data available)

EXAMPLE OUTPUT FORMAT:
```python
import pandas as pd
import plotly.express as px

# Load data from CSV (NEVER hardcode values)
df = pd.read_csv('{data_path}')

# Create visualization
fig = px.line(
    df, 
    x='year', 
    y='avg_annual_pay',
    title='Average Annual Pay Over Time'
)

# Customize layout
fig.update_layout(
    xaxis_title='Year',
    yaxis_title='Average Annual Pay ($)',
    template='plotly_white'
)

# Save to HTML (REQUIRED)
fig.write_html('{output_path}')
```

Generate ONLY the Python code, no explanations. The code must be complete and runnable.
"""


ANALYZE_WITH_ARTIFACT_PROMPT = """
You are a data analyst providing insights about a visualization.

The user asked: {user_request}

A chart has been generated and saved to: {artifact_path}

Based on the data (columns: {columns}, {row_count} rows), provide:
1. A brief description of what the chart shows
2. 2-3 key insights or trends visible in the data
3. Any notable outliers or patterns

Keep the response concise (3-5 sentences). The user will see the chart alongside your text.
"""
```

### 6.2 Code Generation Node

Add to `sql_agent.py` or create `visualization_nodes.py`:

```python
"""
visualization_nodes.py - Nodes for visualization workflow

These nodes handle:
1. Classifying user intent (answer vs visualize)
2. Generating Plotly code from schema
3. Executing code safely
4. Analyzing results with artifact
"""

from typing import Literal
from langchain_core.messages import AIMessage
from prompts import GENERATE_PLOTLY_PROMPT, ANALYZE_WITH_ARTIFACT_PROMPT


def classify_intent(state: dict) -> dict:
    """
    Determine if user wants a text answer or visualization.
    
    This runs BEFORE SQL generation to set the data handoff mode.
    
    Visualization keywords: chart, plot, graph, visualize, show me, trend line,
                           bar chart, scatter, histogram, map
    """
    user_query = state["messages"][0].content.lower()
    
    viz_keywords = [
        "chart", "plot", "graph", "visualize", "visualization",
        "show me", "display", "trend line", "bar chart", "line chart",
        "scatter", "histogram", "heatmap", "map", "dashboard"
    ]
    
    intent = "visualize" if any(kw in user_query for kw in viz_keywords) else "answer"
    
    return {"intent": intent}


def generate_plotly_code(state: dict, model) -> dict:
    """
    Generate Plotly code based on schema (NOT raw data).
    
    Args:
        state: Must contain:
            - messages: conversation history
            - workspace: JobWorkspace with data_path
            - columns: list of column names
            - row_count: number of rows
            - data_preview: sample rows for context
    
    Returns:
        dict with "plotly_code" key
    """
    workspace = state["workspace"]
    user_query = state["messages"][0].content
    
    # Format the prompt with file paths and schema
    prompt = GENERATE_PLOTLY_PROMPT.format(
        data_path=str(workspace.data_path),
        output_path=str(workspace.output_path),
        columns=", ".join(state["columns"]),
        row_count=state["row_count"],
        data_preview=state["data_preview"],
        user_request=user_query
    )
    
    # Generate code
    response = model.invoke([
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"Generate Plotly code for: {user_query}"}
    ])
    
    # Extract code from response (handle markdown code blocks)
    code = response.content
    if "```python" in code:
        code = code.split("```python")[1].split("```")[0]
    elif "```" in code:
        code = code.split("```")[1].split("```")[0]
    
    return {"plotly_code": code.strip()}


def analyze_with_artifact(state: dict, model) -> dict:
    """
    Generate analysis text that accompanies the visualization.
    
    This is the final response to the user, combining:
    - Text insights about the data
    - Reference to the generated chart artifact
    """
    workspace = state["workspace"]
    user_query = state["messages"][0].content
    
    prompt = ANALYZE_WITH_ARTIFACT_PROMPT.format(
        user_request=user_query,
        artifact_path=str(workspace.output_path),
        columns=", ".join(state["columns"]),
        row_count=state["row_count"]
    )
    
    response = model.invoke([
        {"role": "system", "content": prompt},
        {"role": "user", "content": "Provide analysis for the generated chart."}
    ])
    
    # Combine analysis with artifact reference
    analysis = response.content
    artifact_html = None
    
    if workspace.output_path.exists():
        with open(workspace.output_path, 'r') as f:
            artifact_html = f.read()
    
    return {
        "analysis": analysis,
        "artifact_html": artifact_html,
        "artifact_path": str(workspace.output_path),
        "messages": state["messages"] + [AIMessage(content=analysis)]
    }
```

### 6.3 Testing Phase 2

```python
"""test_code_generation.py - Test Plotly code generation."""
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from visualization_nodes import generate_plotly_code
from workspace import create_workspace

load_dotenv()

def test_line_chart_generation():
    """Test generating a line chart."""
    model = init_chat_model("google_genai:gemini-2.0-flash")
    workspace = create_workspace()
    
    # Create mock data file
    with open(workspace.data_path, 'w') as f:
        f.write("year,avg_annual_pay\n2020,65000\n2021,68000\n2022,71000\n2023,74000\n")
    
    state = {
        "messages": [{"content": "Create a line chart of wage trends"}],
        "workspace": workspace,
        "columns": ["year", "avg_annual_pay"],
        "row_count": 4,
        "data_preview": "year,avg_annual_pay\n2020,65000\n2021,68000"
    }
    
    result = generate_plotly_code(state, model)
    
    assert "plotly_code" in result
    assert "pd.read_csv" in result["plotly_code"]
    assert "write_html" in result["plotly_code"]
    assert str(workspace.data_path) in result["plotly_code"]
    
    print("Generated code:")
    print(result["plotly_code"])
    print("\n✓ Line chart code generation works")

if __name__ == "__main__":
    test_line_chart_generation()
```

---

## 7. Phase 3: Code Execution (Runner)

### Goal

Execute the generated Plotly code safely in a subprocess.

### 7.1 Code Executor

Create `runner.py`:

```python
"""
runner.py - Safe code execution for visualization

Key safety features:
1. Subprocess isolation (not exec() in-process)
2. Timeout enforcement
3. Ephemeral environment via uv
4. Working directory isolation
"""

import subprocess
import json
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from workspace import JobWorkspace


@dataclass
class ExecutionResult:
    """Result of code execution."""
    success: bool
    stdout: str
    stderr: str
    exit_code: int
    execution_time_ms: int
    artifact_exists: bool
    error_message: Optional[str] = None


def execute_plotly_code(
    workspace: JobWorkspace,
    code: str,
    timeout_seconds: int = 30
) -> ExecutionResult:
    """
    Execute Plotly code in an isolated subprocess.
    
    Uses `uv run` to ensure correct dependencies without managing
    separate virtual environments.
    
    Args:
        workspace: JobWorkspace with data file and output paths
        code: Python code to execute
        timeout_seconds: Maximum execution time
    
    Returns:
        ExecutionResult with success status and output
    
    Example:
        result = execute_plotly_code(workspace, code)
        if result.success:
            # workspace.output_path now contains HTML chart
    """
    import time
    start_time = time.time()
    
    # Write code to script file
    with open(workspace.script_path, 'w') as f:
        f.write(code)
    
    try:
        # Execute with uv for dependency management
        # This ensures pandas and plotly are available
        result = subprocess.run(
            [
                "uv", "run",
                "--with", "pandas",
                "--with", "plotly",
                "python", str(workspace.script_path)
            ],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=str(workspace.path)  # Run in workspace directory
        )
        
        execution_time = int((time.time() - start_time) * 1000)
        artifact_exists = workspace.output_path.exists()
        
        return ExecutionResult(
            success=(result.returncode == 0 and artifact_exists),
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.returncode,
            execution_time_ms=execution_time,
            artifact_exists=artifact_exists,
            error_message=result.stderr if result.returncode != 0 else None
        )
        
    except subprocess.TimeoutExpired:
        return ExecutionResult(
            success=False,
            stdout="",
            stderr="",
            exit_code=-1,
            execution_time_ms=timeout_seconds * 1000,
            artifact_exists=False,
            error_message=f"Execution timed out after {timeout_seconds} seconds"
        )
    except Exception as e:
        return ExecutionResult(
            success=False,
            stdout="",
            stderr=str(e),
            exit_code=-1,
            execution_time_ms=int((time.time() - start_time) * 1000),
            artifact_exists=False,
            error_message=str(e)
        )


def execute_code_node(state: dict) -> dict:
    """
    LangGraph node wrapper for code execution.
    
    Expects state to contain:
    - workspace: JobWorkspace
    - plotly_code: str
    
    Returns:
    - execution_result: ExecutionResult
    - artifact_html: str (if successful)
    """
    workspace = state["workspace"]
    code = state["plotly_code"]
    
    result = execute_plotly_code(workspace, code)
    
    output = {
        "execution_result": result,
        "execution_success": result.success,
    }
    
    if result.success and workspace.output_path.exists():
        with open(workspace.output_path, 'r') as f:
            output["artifact_html"] = f.read()
    
    if not result.success:
        output["execution_error"] = result.error_message or result.stderr
    
    return output
```

### 7.2 Error Recovery (Optional Enhancement)

Add to `runner.py`:

```python
def execute_with_retry(
    workspace: JobWorkspace,
    code: str,
    model,
    max_retries: int = 2
) -> ExecutionResult:
    """
    Execute code with automatic error correction.
    
    If execution fails, shows the error to the LLM and asks for a fix.
    """
    for attempt in range(max_retries + 1):
        result = execute_plotly_code(workspace, code)
        
        if result.success:
            return result
        
        if attempt < max_retries:
            # Ask LLM to fix the code
            fix_prompt = f"""
The following Python code failed with this error:

CODE:
```python
{code}
```

ERROR:
{result.stderr}

Please fix the code. Return ONLY the corrected Python code, no explanations.
"""
            response = model.invoke([
                {"role": "user", "content": fix_prompt}
            ])
            
            # Extract fixed code
            fixed_code = response.content
            if "```python" in fixed_code:
                fixed_code = fixed_code.split("```python")[1].split("```")[0]
            
            code = fixed_code.strip()
            
            # Update script for debugging
            with open(workspace.script_path, 'w') as f:
                f.write(f"# Attempt {attempt + 2}\n{code}")
    
    return result
```

### 7.3 Testing Phase 3

```python
"""test_runner.py - Test code execution."""
from workspace import create_workspace, cleanup_workspace
from runner import execute_plotly_code

def test_successful_execution():
    """Test that valid code executes correctly."""
    workspace = create_workspace()
    
    # Create test data
    with open(workspace.data_path, 'w') as f:
        f.write("year,value\n2020,100\n2021,150\n2022,200\n")
    
    code = f"""
import pandas as pd
import plotly.express as px

df = pd.read_csv('{workspace.data_path}')
fig = px.line(df, x='year', y='value', title='Test Chart')
fig.write_html('{workspace.output_path}')
"""
    
    result = execute_plotly_code(workspace, code)
    
    assert result.success, f"Execution failed: {result.error_message}"
    assert result.artifact_exists
    assert workspace.output_path.exists()
    
    # Verify HTML is valid
    with open(workspace.output_path) as f:
        html = f.read()
    assert "<html>" in html.lower() or "plotly" in html.lower()
    
    cleanup_workspace(workspace)
    print(f"✓ Successful execution ({result.execution_time_ms}ms)")

def test_timeout():
    """Test that infinite loops are killed."""
    workspace = create_workspace()
    
    code = """
while True:
    pass
"""
    
    result = execute_plotly_code(workspace, code, timeout_seconds=2)
    
    assert not result.success
    assert "timeout" in result.error_message.lower()
    
    cleanup_workspace(workspace)
    print("✓ Timeout handling works")

def test_syntax_error():
    """Test that syntax errors are caught."""
    workspace = create_workspace()
    
    code = """
def broken(
    print("missing parenthesis"
"""
    
    result = execute_plotly_code(workspace, code)
    
    assert not result.success
    assert result.stderr  # Should have error message
    
    cleanup_workspace(workspace)
    print("✓ Syntax error handling works")

if __name__ == "__main__":
    test_successful_execution()
    test_timeout()
    test_syntax_error()
    print("\n✅ All Phase 3 tests passed!")
```

---

## 8. Phase 4: Integration & Testing

### Goal

Wire all components together into the enhanced agent.

### 8.1 Enhanced State Definition

Update the state to include visualization fields:

```python
"""
state.py - Enhanced state for visualization agent
"""
from typing import TypedDict, Optional, List, Literal
from workspace import JobWorkspace


class VisualizationState(TypedDict):
    """
    State for the enhanced SQL + Visualization agent.
    
    Flow:
    1. User query comes in via messages
    2. intent is classified (answer/visualize)
    3. SQL is generated and executed
    4. For visualize: workspace is created, data saved to CSV
    5. plotly_code is generated from schema
    6. Code is executed, artifact created
    7. analysis is generated alongside artifact
    """
    # Input
    messages: List[dict]
    
    # Intent classification
    intent: Literal["answer", "visualize"]
    
    # SQL phase
    generated_sql: Optional[str]
    sql_valid: bool
    columns: List[str]
    row_count: int
    data_preview: str
    
    # Visualization phase (only if intent == "visualize")
    workspace: Optional[JobWorkspace]
    plotly_code: Optional[str]
    execution_success: bool
    execution_error: Optional[str]
    
    # Output
    analysis: str
    artifact_html: Optional[str]
    artifact_path: Optional[str]
```

### 8.2 Enhanced Graph Definition

Create `visualization_agent.py`:

```python
"""
visualization_agent.py - Enhanced agent with visualization capability

This extends sql_agent.py with:
1. Intent classification (answer vs visualize)
2. Data handoff (CSV file passing)
3. Plotly code generation
4. Safe code execution
"""

import os
from typing import Literal
from dotenv import load_dotenv
from sqlalchemy import create_engine
from langchain.chat_models import init_chat_model
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from state import VisualizationState
from workspace import create_workspace, cleanup_workspace
from tools import execute_query_with_handoff
from visualization_nodes import classify_intent, generate_plotly_code, analyze_with_artifact
from runner import execute_code_node

load_dotenv()


def setup_model():
    """Initialize the chat model."""
    return init_chat_model("google_genai:gemini-2.0-flash")


def setup_database():
    """Create database connection."""
    db_uri = f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    engine = create_engine(db_uri)
    return SQLDatabase(engine)


def build_visualization_agent(db, model):
    """
    Build the enhanced LangGraph agent with visualization.
    
    Graph structure:
    
    START
      ↓
    classify_intent
      ↓
    generate_query
      ↓
    check_query
      ↓
    run_query_with_handoff
      ↓
    route_by_intent ─── "answer" ───→ analyze_results → END
      │
      └── "visualize" ──→ generate_plotly_code
                              ↓
                         execute_code
                              ↓
                         analyze_with_artifact → END
    """
    
    toolkit = SQLDatabaseToolkit(db=db, llm=model)
    tools = toolkit.get_tools()
    run_query_tool = next(tool for tool in tools if tool.name == "sql_db_query")
    
    # System prompt for SQL generation (same as before, but enhanced)
    generate_query_system_prompt = f"""
You are an expert {db.dialect} query writer for QCEW employment and wage data.

DATABASE SCHEMA:
Table: msa_wages_employment_data
- area_fips: MSA identifier code (VARCHAR)
- year: Year (INTEGER, 2000-2024)
- qtr: Quarter (VARCHAR, 'A' = Annual average)
- annual_avg_estabs_count: Number of establishments (INTEGER)
- annual_avg_emplvl: Employment level (INTEGER)
- total_annual_wages: Total wages (BIGINT)
- avg_annual_pay: Average annual pay (NUMERIC)
- annual_avg_wkly_wage: Average weekly wage (NUMERIC)
- area_title: MSA name, e.g., "Austin-Round Rock, TX" (VARCHAR)
- state: State abbreviation (VARCHAR)

IMPORTANT RULES:
1. ALWAYS use qtr = 'A' for annual data
2. For MSA names, use ILIKE for case-insensitive matching
3. For trend analysis, ORDER BY year ASC
4. For visualizations, include all necessary columns (don't over-aggregate)
5. NEVER use DELETE, UPDATE, INSERT, DROP statements
"""
    
    # Node: Classify intent
    def classify_intent_node(state: VisualizationState):
        return classify_intent(state)
    
    # Node: Generate query
    def generate_query(state: VisualizationState):
        system_message = {"role": "system", "content": generate_query_system_prompt}
        llm_with_tools = model.bind_tools([run_query_tool])
        response = llm_with_tools.invoke([system_message] + state["messages"])
        return {"messages": state["messages"] + [response]}
    
    # Node: Check query (same as before)
    def check_query(state: VisualizationState):
        # ... same implementation as sql_agent.py
        pass
    
    # Node: Run query with handoff
    def run_query_with_handoff_node(state: VisualizationState):
        """Execute SQL and save to file if visualizing."""
        messages = state["messages"]
        last_message = messages[-1]
        
        if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
            return {"sql_valid": False}
        
        query = last_message.tool_calls[0]["args"]["query"]
        
        result = execute_query_with_handoff(
            db, 
            query, 
            intent=state.get("intent", "answer")
        )
        
        return {
            "generated_sql": query,
            "sql_valid": result["success"],
            "columns": result["columns"],
            "row_count": result["row_count"],
            "data_preview": result["data_preview"],
            "workspace": result["workspace"]
        }
    
    # Node: Analyze results (text only)
    def analyze_results(state: VisualizationState):
        # ... same as sql_agent.py
        pass
    
    # Node: Generate Plotly code
    def generate_plotly_node(state: VisualizationState):
        return generate_plotly_code(state, model)
    
    # Node: Execute code
    def execute_code(state: VisualizationState):
        return execute_code_node(state)
    
    # Node: Analyze with artifact
    def analyze_with_artifact_node(state: VisualizationState):
        return analyze_with_artifact(state, model)
    
    # Routing function
    def route_by_intent(state: VisualizationState) -> Literal["analyze_results", "generate_plotly"]:
        if state.get("intent") == "visualize" and state.get("workspace"):
            return "generate_plotly"
        return "analyze_results"
    
    def should_continue(state: VisualizationState) -> Literal[END, "check_query"]:
        messages = state["messages"]
        last_message = messages[-1]
        if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
            return END
        return "check_query"
    
    # Build the graph
    builder = StateGraph(VisualizationState)
    
    # Add nodes
    builder.add_node("classify_intent", classify_intent_node)
    builder.add_node("generate_query", generate_query)
    builder.add_node("check_query", check_query)
    builder.add_node("run_query_with_handoff", run_query_with_handoff_node)
    builder.add_node("analyze_results", analyze_results)
    builder.add_node("generate_plotly", generate_plotly_node)
    builder.add_node("execute_code", execute_code)
    builder.add_node("analyze_with_artifact", analyze_with_artifact_node)
    
    # Add edges
    builder.add_edge(START, "classify_intent")
    builder.add_edge("classify_intent", "generate_query")
    builder.add_conditional_edges("generate_query", should_continue)
    builder.add_edge("check_query", "run_query_with_handoff")
    builder.add_conditional_edges("run_query_with_handoff", route_by_intent)
    builder.add_edge("analyze_results", END)
    builder.add_edge("generate_plotly", "execute_code")
    builder.add_edge("execute_code", "analyze_with_artifact")
    builder.add_edge("analyze_with_artifact", END)
    
    return builder.compile()


# CLI interface
def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Visualization Agent")
    parser.add_argument("question", type=str, help="Your question")
    parser.add_argument("--output", type=str, help="Save HTML artifact to this path")
    args = parser.parse_args()
    
    print("Initializing Visualization Agent...")
    model = setup_model()
    db = setup_database()
    agent = build_visualization_agent(db, model)
    
    print(f"\nQuestion: {args.question}\n")
    print("=" * 80)
    
    result = agent.invoke({
        "messages": [{"role": "user", "content": args.question}],
        "intent": "answer",  # Will be overwritten by classify_intent
    })
    
    # Print analysis
    print("\nAnalysis:")
    print(result.get("analysis", "No analysis generated"))
    
    # Handle artifact
    if result.get("artifact_html"):
        if args.output:
            with open(args.output, 'w') as f:
                f.write(result["artifact_html"])
            print(f"\n✓ Chart saved to: {args.output}")
        else:
            print(f"\n✓ Chart generated at: {result.get('artifact_path')}")
    
    print("=" * 80)


if __name__ == "__main__":
    main()
```

### 8.3 End-to-End Test Suite

Create `test_visualization_agent.py`:

```python
"""
test_visualization_agent.py - End-to-end tests for visualization agent

Run with: uv run pytest test_visualization_agent.py -v
"""
import pytest
from visualization_agent import setup_model, setup_database, build_visualization_agent
from workspace import cleanup_old_workspaces


@pytest.fixture(scope="module")
def agent():
    """Create agent once for all tests."""
    model = setup_model()
    db = setup_database()
    return build_visualization_agent(db, model)


def test_simple_text_answer(agent):
    """Text-only questions should work as before."""
    result = agent.invoke({
        "messages": [{"role": "user", "content": "What is the average wage in Austin in 2023?"}],
        "intent": "answer"
    })
    
    assert result.get("analysis")
    assert "Austin" in result["analysis"] or "austin" in result["analysis"].lower()
    assert result.get("artifact_html") is None  # No chart for text questions


def test_line_chart_visualization(agent):
    """Test line chart generation."""
    result = agent.invoke({
        "messages": [{"role": "user", "content": "Create a line chart showing average annual pay trends for Austin from 2010 to 2024"}],
        "intent": "answer"
    })
    
    assert result.get("intent") == "visualize"
    assert result.get("artifact_html")
    assert "plotly" in result["artifact_html"].lower()


def test_bar_chart_visualization(agent):
    """Test bar chart generation."""
    result = agent.invoke({
        "messages": [{"role": "user", "content": "Show me a bar chart comparing average wages in Austin, Seattle, and Denver in 2023"}],
        "intent": "answer"
    })
    
    assert result.get("artifact_html")


def test_large_data_file_handoff(agent):
    """Test that large data uses file handoff (doesn't crash)."""
    result = agent.invoke({
        "messages": [{"role": "user", "content": "Visualize average annual pay trends for all MSAs from 2000 to 2024"}],
        "intent": "answer"
    })
    
    # Should succeed even with ~10K rows
    assert result.get("artifact_html") or result.get("analysis")
    # Should have used workspace
    assert result.get("workspace") is not None


def test_cleanup():
    """Clean up old workspaces after tests."""
    cleaned = cleanup_old_workspaces(max_age_hours=0)  # Clean all
    print(f"Cleaned {cleaned} workspaces")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

---

## 9. File Structure

After implementation, your project should look like:

```
City-Growth-AI-Agent/
├── sql_agent.py              # Original agent (keep for reference)
├── visualization_agent.py    # NEW: Enhanced agent with visualization
├── workspace.py              # NEW: Job workspace management
├── tools.py                  # NEW: Data handoff tools
├── prompts.py                # NEW: System prompts
├── runner.py                 # NEW: Code execution
├── state.py                  # NEW: State definitions
├── tests/
│   ├── test_handoff.py       # Phase 1 tests
│   ├── test_code_generation.py # Phase 2 tests
│   ├── test_runner.py        # Phase 3 tests
│   └── test_visualization_agent.py # Phase 4 tests
├── docs/
│   ├── SQL_AGENT_DESIGN.md
│   └── VISUALIZATION_IMPLEMENTATION_PLAN.md  # This document
└── .env
```

---

## 10. Common Pitfalls

### Pitfall 1: Forgetting to Handle Empty Results

**Problem:** SQL returns 0 rows, code generation crashes.

**Solution:** Check row count before visualization:
```python
if result["row_count"] == 0:
    return {"analysis": "No data found matching your query.", "artifact_html": None}
```

### Pitfall 2: LLM Generates Invalid Column Names

**Problem:** LLM writes `df['Annual Pay']` but column is `avg_annual_pay`.

**Solution:** Include exact column names in prompt and use preview data.

### Pitfall 3: Workspace Not Cleaned Up

**Problem:** `/tmp/viz_jobs/` fills up with old jobs.

**Solution:** Run `cleanup_old_workspaces()` periodically or in a cron job.

### Pitfall 4: subprocess Inherits Environment

**Problem:** Subprocess has access to API keys in environment.

**Solution:** Use `env={}` parameter in subprocess.run() to clear environment (optional for MVP).

### Pitfall 5: HTML Too Large for Response

**Problem:** Plotly HTML can be 2MB+ for complex charts.

**Solution:** For API responses, return file path and serve HTML separately. For CLI, save to file.

---

## 11. Testing Checklist

Before considering each phase complete, verify:

### Phase 1 Checklist
- [ ] `create_workspace()` creates unique directories
- [ ] `cleanup_workspace()` removes all files
- [ ] Small queries return data in context
- [ ] Large queries save to CSV
- [ ] CSV has correct headers and data

### Phase 2 Checklist
- [ ] Intent classification detects "chart", "visualize", etc.
- [ ] Generated code includes `pd.read_csv()` with correct path
- [ ] Generated code includes `fig.write_html()` with correct path
- [ ] Code handles different chart types (line, bar, scatter)

### Phase 3 Checklist
- [ ] Valid code executes successfully
- [ ] Output HTML file is created
- [ ] Timeout kills long-running code
- [ ] Syntax errors return helpful messages
- [ ] `uv run --with` installs dependencies correctly

### Phase 4 Checklist
- [ ] Text questions work as before (regression test)
- [ ] Visualization questions produce HTML artifacts
- [ ] Large data queries don't crash
- [ ] End-to-end flow completes in < 30 seconds
- [ ] At least 5 different visualization types work

---

## Summary

This plan addresses the critical "context stuffing" problem by implementing file-based data handoff. The key architectural changes are:

1. **Intent Classification** — Detect visualization requests early
2. **Data Handoff** — Save SQL results to CSV, pass only schema to LLM
3. **Code Generation** — LLM generates code that reads from CSV
4. **Safe Execution** — Subprocess with timeout, using `uv run`
5. **Artifact Management** — HTML charts as first-class outputs

The implementation is split into 4 phases of ~2 days each, with clear tests for each phase. Start with Phase 1 (data handoff) as it's the foundation for everything else.

**Key insight to remember:** The LLM reasons about SCHEMA, not DATA. It never sees 10,000 rows — it sees `columns: [year, area_title, avg_annual_pay], row_count: 10000`.
