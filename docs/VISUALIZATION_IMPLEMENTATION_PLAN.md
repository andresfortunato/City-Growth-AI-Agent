# Visualization Agent Implementation Plan

**For Junior Developers**
**Last Updated:** January 2026 (v2 - Enhanced with LangGraph best practices)

---

## Summary

We are developing an AI agent for data analysis and visualization of urban economic data in the US (starting with employment, wages, and number of establishments by MSA in 2000-2024). We'll develop a LangGraph workflow to test different agent versions, capabilities, and workflows. So far we have a `sql_agent.py` and want to expand the workflow's capabilities to produce data visualizations by adding nodes with the capacity to analyze data, run Python scripts, and create Plotly graphs. This will result in an LLM-powered **Data Analyst Agent application**.

### What's New in v2

This version incorporates:
- **LangGraph best practices** from official documentation
- **State reducers** for proper message accumulation
- **Structured output with Pydantic** (no string parsing)
- **Error recovery loops** for robust code execution
- **Connection pooling** for production-ready DB connections
- **Execution time tracking** for performance monitoring

---

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
- Recover gracefully from code execution errors

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

### High-Level Flow (v2 - With Error Recovery)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       ENHANCED VISUALIZATION AGENT                           │
│                                                                              │
│  START                                                                       │
│    ↓                                                                         │
│  classify_intent (LLM) ──→ ["answer", "visualize", "multi_chart"]           │
│    ↓                                                                         │
│  generate_query                                                              │
│    ↓                                                                         │
│  run_query_with_handoff ←── Saves to CSV if visualization                   │
│    ↓                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │ if intent == "answer":                                          │        │
│  │   → analyze_results → END                                       │        │
│  │                                                                  │        │
│  │ if intent == "visualize" or "multi_chart":                      │        │
│  │   → validate_columns ←── Anti-hallucination (optional)         │        │
│  │   → generate_plotly_code                                        │        │
│  │   → execute_code ─────────────────────────────────────┐         │        │
│  │        ↓ success                    ↓ failure         │         │        │
│  │   analyze_with_artifact → END    fix_code ────────────┘         │        │
│  │                                  (max 3 retries)                │        │
│  └─────────────────────────────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────────────────────────────┘
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
    └── meta.json         # Execution metadata + timing
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

### 3.4 State Reducers (Critical LangGraph Pattern)

LangGraph requires **reducers** for fields that accumulate values (like messages):

```python
from typing import Annotated
from langgraph.graph.message import add_messages

class VisualizationState(TypedDict):
    messages: Annotated[list, add_messages]  # ✅ Accumulates properly
    # NOT: messages: List[dict]  # ❌ Would overwrite each time
```

### 3.5 Multi-Chart Detection

The agent can detect when a user asks for multiple charts:
- "Show wages AND employment trends" → generates 2 charts
- "Compare Austin vs Seattle wages and show growth rates" → may need multiple visualizations

This is handled in intent classification by returning `multi_chart` intent.

---

## 4. Implementation Phases

| Phase | Goal | Duration | Deliverable |
|-------|------|----------|-------------|
| **Phase 1** | Data Handoff | 1-2 days | Modified SQL tool that saves to CSV |
| **Phase 2** | Code Generation | 2-3 days | New node that generates Plotly code with Pydantic |
| **Phase 3** | Code Execution | 1-2 days | Subprocess runner with error recovery loop |
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
import time
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, asdict, field

# Base directory for all job workspaces
WORKSPACE_BASE = Path("/tmp/viz_jobs")


@dataclass
class JobWorkspace:
    """Represents an isolated workspace for a visualization job."""
    job_id: str
    path: Path
    created_at: str
    timings: dict = field(default_factory=dict)

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

    def record_timing(self, phase: str, duration_ms: int) -> None:
        """Record timing for a phase (for performance monitoring)."""
        self.timings[phase] = duration_ms
        self._save_meta()

    def _save_meta(self) -> None:
        """Persist metadata to disk."""
        with open(self.meta_path, 'w') as f:
            json.dump({
                **asdict(self),
                "path": str(self.path)
            }, f, default=str, indent=2)


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

    workspace._save_meta()
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

Create a new file: `tools.py`

```python
"""
tools.py - Enhanced SQL tool with data handoff capability

The key insight: LLMs should reason about SCHEMA, not DATA.
For visualization, we save results to CSV and return only the schema.
"""

import csv
import time
from typing import Literal
from langchain_community.utilities import SQLDatabase
from workspace import create_workspace, JobWorkspace


def execute_query_with_handoff(
    db: SQLDatabase,
    query: str,
    intent: Literal["answer", "visualize", "multi_chart"],
    max_rows_in_context: int = 50
) -> dict:
    """
    Execute SQL query with smart data handoff.

    For 'answer' intent: Returns rows in context (for small results)
    For 'visualize'/'multi_chart' intent: Saves to CSV, returns only schema

    Args:
        db: SQLDatabase instance
        query: SQL query to execute
        intent: "answer" for text response, "visualize"/"multi_chart" for charts
        max_rows_in_context: Max rows to return in context (answer mode)

    Returns:
        dict with keys:
        - success: bool
        - row_count: int
        - columns: list[str]
        - data_preview: str (first few rows, for LLM context)
        - workspace: JobWorkspace (only for visualize intent)
        - error: str (if failed)
        - execution_time_ms: int
    """
    start_time = time.time()

    try:
        # Execute query and get results
        raw_result = db.run(query)

        # Parse the result
        rows = _parse_sql_result(raw_result)

        execution_time_ms = int((time.time() - start_time) * 1000)

        if not rows:
            return {
                "success": True,
                "row_count": 0,
                "columns": [],
                "data_preview": "No results returned",
                "workspace": None,
                "error": None,
                "execution_time_ms": execution_time_ms
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
                "error": None,
                "execution_time_ms": execution_time_ms
            }

        # For visualize/multi_chart intent with large data, save to file
        workspace = create_workspace()

        with open(workspace.data_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)

        workspace.record_timing("sql_execution", execution_time_ms)

        # Return only schema + preview (NOT full data)
        preview = _format_rows_for_context(rows[:5])

        return {
            "success": True,
            "row_count": row_count,
            "columns": columns,
            "data_preview": f"[{row_count} rows saved to {workspace.data_path}]\n\nPreview (first 5 rows):\n{preview}",
            "workspace": workspace,
            "error": None,
            "execution_time_ms": execution_time_ms
        }

    except Exception as e:
        return {
            "success": False,
            "row_count": 0,
            "columns": [],
            "data_preview": "",
            "workspace": None,
            "error": str(e),
            "execution_time_ms": int((time.time() - start_time) * 1000)
        }


def _parse_sql_result(raw_result) -> list[dict]:
    """Parse SQLDatabase.run() output into list of dicts."""
    if isinstance(raw_result, list):
        if raw_result and isinstance(raw_result[0], dict):
            return raw_result
        return []

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

    columns = list(rows[0].keys())
    lines = [",".join(columns)]

    for row in rows:
        line = ",".join(str(row.get(col, "")) for col in columns)
        lines.append(line)

        if sum(len(l) for l in lines) > max_chars:
            lines.append(f"... ({len(rows) - len(lines) + 1} more rows)")
            break

    return "\n".join(lines)
```

### 5.3 Testing Phase 1

Create `tests/test_handoff.py`:

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
    assert result["workspace"] is None
    assert "execution_time_ms" in result
    print(f"✓ Small result answer mode works ({result['execution_time_ms']}ms)")

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

    import csv
    with open(result["workspace"].data_path) as f:
        reader = csv.DictReader(f)
        row = next(reader)
        assert "year" in row
        assert "area_title" in row

    cleanup_workspace(result["workspace"])
    print(f"✓ Large result visualize mode works ({result['row_count']} rows in {result['execution_time_ms']}ms)")

def test_workspace_lifecycle():
    """Test workspace creation and cleanup."""
    workspace = create_workspace()

    assert workspace.path.exists()
    assert workspace.job_id is not None

    with open(workspace.data_path, 'w') as f:
        f.write("test,data\n1,2")

    assert workspace.data_path.exists()

    workspace.record_timing("test_phase", 100)
    assert workspace.timings["test_phase"] == 100

    cleanup_workspace(workspace)
    assert not workspace.path.exists()
    print("✓ Workspace lifecycle works")

if __name__ == "__main__":
    test_workspace_lifecycle()
    test_small_result_answer_mode()
    test_large_result_visualize_mode()
    print("\n✅ All Phase 1 tests passed!")
```

---

## 6. Phase 2: Visualization Code Generation

### Goal

Create a node that generates Plotly code using:
- **LLM-driven intent classification** (not keyword matching)
- **Structured output with Pydantic** (no string parsing)
- **Multi-chart detection** for complex queries

### 6.1 Pydantic Models for Structured Output

Create `models.py`:

```python
"""
models.py - Pydantic models for structured LLM output

Using structured output eliminates fragile string parsing and guarantees schema.
"""

from typing import Literal, Optional, List
from pydantic import BaseModel, Field


class IntentClassification(BaseModel):
    """Result of classifying user intent."""
    intent: Literal["answer", "visualize", "multi_chart"] = Field(
        description="'answer' for text, 'visualize' for single chart, 'multi_chart' for multiple charts"
    )
    chart_types: List[str] = Field(
        default_factory=list,
        description="Suggested chart types: line, bar, scatter, histogram, etc."
    )
    num_charts: int = Field(
        default=1,
        description="Number of distinct charts needed"
    )
    reasoning: str = Field(
        description="Brief explanation of classification decision"
    )


class PlotlyCodeOutput(BaseModel):
    """Structured output for Plotly code generation."""
    code: str = Field(description="Complete Python code for the visualization")
    chart_type: str = Field(description="The chart type used")
    columns_used: List[str] = Field(description="Columns from the CSV used in the chart")


class AnalysisOutput(BaseModel):
    """Structured output for chart analysis."""
    summary: str = Field(description="Brief description of what the chart shows")
    insights: List[str] = Field(description="2-3 key insights or trends", max_length=4)
```

### 6.2 Plotly Code Generation Prompt

Create `prompts.py`:

```python
"""
prompts.py - System prompts for visualization agent

Key principle: The LLM sees SCHEMA, not DATA.
It generates code that reads from the CSV file.
"""

INTENT_CLASSIFICATION_PROMPT = """You are an expert at understanding data analysis requests.

TASK: Classify the user's request into one of three categories:
- "answer": User wants a text-based answer (specific values, counts, lists)
- "visualize": User wants a single chart or graph
- "multi_chart": User wants multiple different charts (e.g., "show wages AND employment trends")

Also identify appropriate chart types:
- Time series (year/date on x-axis): line
- Category comparisons: bar
- Distributions: histogram or box
- Correlations: scatter
- Rankings: horizontal bar
- Geographic: choropleth

MULTI-CHART DETECTION:
- "Show wages AND employment trends" → multi_chart (2 charts)
- "Compare Austin vs Seattle wages and show growth rates" → may need 2 charts
- "Create a dashboard with..." → multi_chart

Be precise. "Show me" usually means visualize. "What is" usually means answer."""


GENERATE_PLOTLY_PROMPT = """You are an expert data visualization developer using Plotly and pandas.

TASK: Generate Python code to create a Plotly visualization.

CRITICAL RULES:
1. ALWAYS start with: df = pd.read_csv('{data_path}')
2. NEVER hardcode data values - always read from the CSV
3. ALWAYS save the figure: fig.write_html('{output_path}')
4. Use plotly.express (px) for simple charts, plotly.graph_objects (go) for complex ones
5. Add clear titles, axis labels, and legends
6. ONLY use columns that exist in the data: {columns}

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
- Multi-city comparison over time: Use px.line() with color= parameter

Generate complete, runnable Python code."""


ANALYZE_WITH_ARTIFACT_PROMPT = """You are a data analyst providing insights about a visualization.

The user asked: {user_request}

A chart has been generated showing data with:
- Columns: {columns}
- Row count: {row_count}

Provide:
1. A brief description of what the chart shows (1-2 sentences)
2. 2-3 key insights or trends visible in the data

Keep the response concise. The user will see the chart alongside your text."""


FIX_CODE_PROMPT = """The following Python code failed with an error. Fix it.

ORIGINAL CODE:
```python
{code}
```

ERROR:
{error}

RULES:
1. Return ONLY the corrected Python code
2. The code MUST read from: {data_path}
3. The code MUST save to: {output_path}
4. ONLY use these columns: {columns}
5. Do NOT add explanations, just the code

Return the complete fixed Python code."""
```

### 6.3 Code Generation Nodes with Structured Output

Create `visualization_nodes.py`:

```python
"""
visualization_nodes.py - Nodes for visualization workflow

These nodes handle:
1. Classifying user intent (LLM-driven with multi-chart detection)
2. Validating columns exist (anti-hallucination, optional)
3. Generating Plotly code with structured output
4. Analyzing results with artifact
"""

import time
from typing import Optional
from langchain_core.messages import AIMessage

from models import IntentClassification, PlotlyCodeOutput, AnalysisOutput
from prompts import (
    INTENT_CLASSIFICATION_PROMPT,
    GENERATE_PLOTLY_PROMPT,
    ANALYZE_WITH_ARTIFACT_PROMPT
)


def classify_intent(state: dict, model) -> dict:
    """
    Determine if user wants a text answer, single chart, or multiple charts.

    Uses LLM classification (not keyword matching) to handle nuanced queries like:
    - "How has Austin's economy grown?" → visualize (implies trend)
    - "Show wages AND employment" → multi_chart (two metrics)
    """
    start_time = time.time()
    user_query = state["messages"][-1].content if hasattr(state["messages"][-1], 'content') else state["messages"][-1]["content"]

    structured_model = model.with_structured_output(IntentClassification)

    try:
        response = structured_model.invoke([
            {"role": "system", "content": INTENT_CLASSIFICATION_PROMPT},
            {"role": "user", "content": f"Classify this request: {user_query}"}
        ])

        elapsed = int((time.time() - start_time) * 1000)

        return {
            "intent": response.intent,
            "suggested_chart_types": response.chart_types,
            "num_charts": response.num_charts,
            "intent_reasoning": response.reasoning,
            "classify_time_ms": elapsed
        }
    except Exception as e:
        # Graceful degradation: default to answer intent
        return {
            "intent": "answer",
            "suggested_chart_types": [],
            "num_charts": 0,
            "intent_reasoning": f"Classification failed, defaulting to answer: {e}"
        }


def validate_columns(state: dict) -> dict:
    """
    Anti-hallucination: Verify that columns exist in the CSV.

    NOTE: This adds ~100-200ms latency. Consider removing if it becomes a bottleneck.
    Can be disabled by setting SKIP_COLUMN_VALIDATION=true environment variable.

    This prevents generating code that references non-existent columns.
    """
    import os
    if os.getenv("SKIP_COLUMN_VALIDATION", "false").lower() == "true":
        return {}

    workspace = state.get("workspace")
    if not workspace or not workspace.data_path.exists():
        return {}

    try:
        import csv
        with open(workspace.data_path, 'r') as f:
            reader = csv.reader(f)
            actual_columns = next(reader)

        return {"columns": actual_columns, "columns_validated": True}
    except Exception:
        # Graceful degradation: pass through unchanged
        return {}


def generate_plotly_code(state: dict, model) -> dict:
    """
    Generate Plotly code using structured output (no string parsing).

    Uses Pydantic model to guarantee clean code output.
    """
    start_time = time.time()
    workspace = state["workspace"]
    user_query = state["messages"][-1].content if hasattr(state["messages"][-1], 'content') else state["messages"][-1]["content"]

    prompt = GENERATE_PLOTLY_PROMPT.format(
        data_path=str(workspace.data_path),
        output_path=str(workspace.output_path),
        columns=", ".join(state["columns"]),
        row_count=state["row_count"],
        data_preview=state["data_preview"],
        user_request=user_query
    )

    structured_model = model.with_structured_output(PlotlyCodeOutput)

    try:
        response = structured_model.invoke([
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Generate Plotly code for: {user_query}"}
        ])

        elapsed = int((time.time() - start_time) * 1000)
        workspace.record_timing("code_generation", elapsed)

        return {
            "plotly_code": response.code,
            "chart_type": response.chart_type,
            "columns_used": response.columns_used,
            "retry_count": 0
        }
    except Exception as e:
        # Graceful degradation
        return {
            "plotly_code": None,
            "chart_type": None,
            "columns_used": [],
            "code_generation_error": str(e)
        }


def analyze_with_artifact(state: dict, model) -> dict:
    """
    Generate analysis text that accompanies the visualization.

    Uses structured output for consistent format.
    """
    start_time = time.time()
    workspace = state["workspace"]
    user_query = state["messages"][-1].content if hasattr(state["messages"][-1], 'content') else state["messages"][-1]["content"]

    prompt = ANALYZE_WITH_ARTIFACT_PROMPT.format(
        user_request=user_query,
        columns=", ".join(state["columns"]),
        row_count=state["row_count"]
    )

    structured_model = model.with_structured_output(AnalysisOutput)

    try:
        response = structured_model.invoke([
            {"role": "system", "content": prompt},
            {"role": "user", "content": "Provide analysis for the generated chart."}
        ])

        # Format as text for user
        analysis_text = response.summary + "\n\n"
        analysis_text += "Key insights:\n"
        for insight in response.insights:
            analysis_text += f"• {insight}\n"

        # Read artifact HTML
        artifact_html = None
        if workspace.output_path.exists():
            with open(workspace.output_path, 'r') as f:
                artifact_html = f.read()

        elapsed = int((time.time() - start_time) * 1000)
        workspace.record_timing("analysis", elapsed)

        return {
            "analysis": analysis_text,
            "artifact_html": artifact_html,
            "artifact_path": str(workspace.output_path),
            "messages": state["messages"] + [AIMessage(content=analysis_text)]
        }
    except Exception as e:
        # Graceful degradation
        return {
            "analysis": f"Chart generated but analysis failed: {e}",
            "artifact_html": None,
            "artifact_path": str(workspace.output_path) if workspace else None
        }
```

### 6.4 Testing Phase 2

Create `tests/test_code_generation.py`:

```python
"""test_code_generation.py - Test Plotly code generation with structured output."""
import os
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from visualization_nodes import classify_intent, generate_plotly_code
from workspace import create_workspace, cleanup_workspace

load_dotenv()

def test_intent_classification():
    """Test LLM-based intent classification with multi-chart detection."""
    model = init_chat_model("google_genai:gemini-2.0-flash")

    test_cases = [
        ("Create a line chart of wage trends", "visualize", 1),
        ("What is the average wage in Austin?", "answer", 0),
        ("Show wages AND employment trends over time", "multi_chart", 2),
        ("Compare Seattle and Austin wages", "visualize", 1),
    ]

    for query, expected_intent, expected_charts in test_cases:
        state = {"messages": [{"content": query}]}
        result = classify_intent(state, model)

        assert result["intent"] == expected_intent, \
            f"Query '{query}' expected {expected_intent}, got {result['intent']}"
        print(f"✓ '{query[:40]}...' → {result['intent']} ({result['num_charts']} charts)")

    print("\n✓ Intent classification works")


def test_structured_code_generation():
    """Test generating a chart with structured output."""
    model = init_chat_model("google_genai:gemini-2.0-flash")
    workspace = create_workspace()

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
    assert "chart_type" in result
    assert "columns_used" in result
    assert "pd.read_csv" in result["plotly_code"]
    assert "write_html" in result["plotly_code"]

    print(f"Generated {result['chart_type']} chart using columns: {result['columns_used']}")

    cleanup_workspace(workspace)
    print("\n✓ Structured code generation works")


if __name__ == "__main__":
    test_intent_classification()
    test_structured_code_generation()
    print("\n✅ All Phase 2 tests passed!")
```

---

## 7. Phase 3: Code Execution (Runner)

### Goal

Execute the generated Plotly code safely with:
- Subprocess isolation
- Code validation before execution
- Error recovery loop (max 3 retries)

### 7.1 Code Validator

Create `validator.py`:

```python
"""
validator.py - Code validation before execution
"""

import ast
from typing import Tuple

BLOCKED_IMPORTS = [
    "os", "sys", "subprocess", "shutil", "socket",
    "requests", "urllib", "http", "ftplib", "smtplib",
    "pickle", "marshal", "shelve"
]


def validate_code(code: str) -> Tuple[bool, str]:
    """
    Validate generated Python code before execution.

    Returns:
        (is_valid, error_message)
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"Syntax error on line {e.lineno}: {e.msg}"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_name = alias.name.split('.')[0]
                if module_name in BLOCKED_IMPORTS:
                    return False, f"Blocked import: {alias.name}"

        if isinstance(node, ast.ImportFrom):
            if node.module:
                module_name = node.module.split('.')[0]
                if module_name in BLOCKED_IMPORTS:
                    return False, f"Blocked import: {node.module}"

    if "pd.read_csv" not in code:
        return False, "Code must use pd.read_csv() to load data"

    if "write_html" not in code:
        return False, "Code must use fig.write_html() to save output"

    return True, ""
```

### 7.2 Code Executor with Error Recovery

Create `runner.py`:

```python
"""
runner.py - Safe code execution for visualization with error recovery

Key features:
1. Subprocess isolation
2. Timeout enforcement
3. Error recovery loop (max 3 retries)
4. Execution time tracking
"""

import subprocess
import time
from dataclasses import dataclass
from typing import Optional

from workspace import JobWorkspace
from validator import validate_code
from prompts import FIX_CODE_PROMPT
from models import PlotlyCodeOutput


@dataclass
class ExecutionResult:
    """Result of code execution."""
    success: bool
    stdout: str
    stderr: str
    exit_code: int
    execution_time_ms: int
    artifact_exists: bool
    attempt: int
    error_message: Optional[str] = None


def execute_plotly_code(
    workspace: JobWorkspace,
    code: str,
    timeout_seconds: int = 30,
    validate: bool = True
) -> ExecutionResult:
    """
    Execute Plotly code in an isolated subprocess.
    """
    start_time = time.time()

    if validate:
        is_valid, error = validate_code(code)
        if not is_valid:
            return ExecutionResult(
                success=False, stdout="", stderr=error, exit_code=-1,
                execution_time_ms=0, artifact_exists=False, attempt=1,
                error_message=f"Code validation failed: {error}"
            )

    with open(workspace.script_path, 'w') as f:
        f.write(code)

    try:
        result = subprocess.run(
            ["uv", "run", "--with", "pandas", "--with", "plotly",
             "python", str(workspace.script_path)],
            capture_output=True, text=True, timeout=timeout_seconds,
            cwd=str(workspace.path)
        )

        execution_time = int((time.time() - start_time) * 1000)
        artifact_exists = workspace.output_path.exists()

        return ExecutionResult(
            success=(result.returncode == 0 and artifact_exists),
            stdout=result.stdout, stderr=result.stderr,
            exit_code=result.returncode, execution_time_ms=execution_time,
            artifact_exists=artifact_exists, attempt=1,
            error_message=result.stderr if result.returncode != 0 else None
        )

    except subprocess.TimeoutExpired:
        return ExecutionResult(
            success=False, stdout="", stderr="", exit_code=-1,
            execution_time_ms=timeout_seconds * 1000, artifact_exists=False,
            attempt=1, error_message=f"Execution timed out after {timeout_seconds}s"
        )
    except Exception as e:
        return ExecutionResult(
            success=False, stdout="", stderr=str(e), exit_code=-1,
            execution_time_ms=int((time.time() - start_time) * 1000),
            artifact_exists=False, attempt=1, error_message=str(e)
        )


def fix_code(code: str, error: str, workspace: JobWorkspace, columns: list[str], model) -> str:
    """Ask LLM to fix broken code."""
    prompt = FIX_CODE_PROMPT.format(
        code=code, error=error,
        data_path=str(workspace.data_path),
        output_path=str(workspace.output_path),
        columns=", ".join(columns)
    )

    try:
        structured_model = model.with_structured_output(PlotlyCodeOutput)
        response = structured_model.invoke([{"role": "user", "content": prompt}])
        return response.code
    except Exception:
        # Graceful degradation: return original code
        return code


def execute_with_recovery(
    workspace: JobWorkspace, code: str, columns: list[str], model, max_retries: int = 3
) -> ExecutionResult:
    """
    Execute code with automatic error recovery (up to max_retries attempts).
    """
    current_code = code

    for attempt in range(1, max_retries + 1):
        result = execute_plotly_code(workspace, current_code)
        result.attempt = attempt

        if result.success:
            return result

        if attempt < max_retries:
            current_code = fix_code(
                current_code, result.error_message or result.stderr,
                workspace, columns, model
            )

    return result


def execute_code_node(state: dict, model) -> dict:
    """LangGraph node wrapper for code execution with recovery."""
    workspace = state["workspace"]
    code = state["plotly_code"]
    columns = state.get("columns", [])

    if not code:
        return {
            "execution_success": False,
            "execution_error": "No code to execute"
        }

    result = execute_with_recovery(workspace, code, columns, model, max_retries=3)
    workspace.record_timing("execution", result.execution_time_ms)

    output = {
        "execution_success": result.success,
        "execution_attempts": result.attempt,
    }

    if result.success and workspace.output_path.exists():
        with open(workspace.output_path, 'r') as f:
            output["artifact_html"] = f.read()

    if not result.success:
        output["execution_error"] = result.error_message or result.stderr

    return output
```

### 7.3 Testing Phase 3

Create `tests/test_runner.py`:

```python
"""test_runner.py - Test code execution with error recovery."""
import os
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from workspace import create_workspace, cleanup_workspace
from runner import execute_plotly_code, execute_with_recovery
from validator import validate_code

load_dotenv()


def test_validation():
    """Test code validation catches problems."""
    # Valid code
    valid_code = """
import pandas as pd
import plotly.express as px
df = pd.read_csv('/tmp/data.csv')
fig = px.line(df, x='year', y='value')
fig.write_html('/tmp/output.html')
"""
    is_valid, error = validate_code(valid_code)
    assert is_valid, f"Valid code rejected: {error}"
    print("✓ Valid code passes validation")

    # Dangerous import
    dangerous_code = "import os\nimport pandas as pd"
    is_valid, error = validate_code(dangerous_code)
    assert not is_valid
    assert "Blocked import" in error
    print("✓ Dangerous imports blocked")


def test_successful_execution():
    """Test that valid code executes correctly."""
    workspace = create_workspace()

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

    cleanup_workspace(workspace)
    print(f"✓ Successful execution ({result.execution_time_ms}ms)")


def test_error_recovery():
    """Test that error recovery fixes broken code."""
    model = init_chat_model("google_genai:gemini-2.0-flash")
    workspace = create_workspace()

    with open(workspace.data_path, 'w') as f:
        f.write("year,value\n2020,100\n2021,150\n2022,200\n")

    # Intentionally broken code
    broken_code = f"""
import pandas as pd
import plotly.express as px
df = pd.read_csv('{workspace.data_path}')
fig = px.line(df, x='year', y='wrong_column')
fig.write_html('{workspace.output_path}')
"""

    result = execute_with_recovery(
        workspace, broken_code, columns=["year", "value"], model=model, max_retries=3
    )

    assert result.success, f"Recovery failed: {result.error_message}"
    assert result.attempt > 1, "Should have required at least one retry"

    cleanup_workspace(workspace)
    print(f"✓ Error recovery worked (fixed on attempt {result.attempt})")


if __name__ == "__main__":
    test_validation()
    test_successful_execution()
    test_error_recovery()
    print("\n✅ All Phase 3 tests passed!")
```

---

## 8. Phase 4: Integration & Testing

### Goal

Wire all components together with proper state management and connection pooling.

### 8.1 Enhanced State Definition (with Reducers)

Create `state.py`:

```python
"""
state.py - Enhanced state for visualization agent

CRITICAL: Uses Annotated types with reducers for proper message accumulation.
"""

from typing import TypedDict, Optional, List, Literal, Annotated
from langgraph.graph.message import add_messages
from workspace import JobWorkspace


class VisualizationState(TypedDict):
    """State for the enhanced SQL + Visualization agent."""

    # Input - MUST use add_messages reducer
    messages: Annotated[list, add_messages]

    # Intent classification (LLM-driven with multi-chart support)
    intent: Literal["answer", "visualize", "multi_chart"]
    suggested_chart_types: List[str]
    num_charts: int

    # SQL phase
    generated_sql: Optional[str]
    sql_valid: bool
    columns: List[str]
    columns_validated: bool
    row_count: int
    data_preview: str

    # Visualization phase
    workspace: Optional[JobWorkspace]
    plotly_code: Optional[str]
    chart_type: Optional[str]
    columns_used: List[str]

    # Execution phase
    execution_success: bool
    execution_error: Optional[str]
    execution_attempts: int
    retry_count: int

    # Output
    analysis: str
    artifact_html: Optional[str]
    artifact_path: Optional[str]

    # Timing
    execution_time_seconds: float
```

### 8.2 Enhanced Graph Definition

Create `visualization_agent.py`:

```python
"""
visualization_agent.py - Enhanced agent with visualization capability

Features:
1. LLM-driven intent classification with multi-chart detection
2. Data handoff (CSV file passing)
3. Structured output with Pydantic
4. Error recovery loop for code execution
5. Connection pooling for production
6. Execution timing
"""

import os
import time
from typing import Literal
from dotenv import load_dotenv
from sqlalchemy import create_engine, pool
from langchain.chat_models import init_chat_model
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langgraph.graph import END, START, StateGraph

from state import VisualizationState
from workspace import create_workspace
from tools import execute_query_with_handoff
from visualization_nodes import classify_intent, validate_columns, generate_plotly_code, analyze_with_artifact
from runner import execute_code_node

load_dotenv()

MODEL_ID = os.getenv("MODEL_OVERRIDE", "google_genai:gemini-2.0-flash")


def setup_model():
    """Initialize the chat model."""
    return init_chat_model(MODEL_ID)


def setup_database():
    """Create database connection with connection pooling."""
    db_uri = f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"

    engine = create_engine(
        db_uri,
        poolclass=pool.QueuePool,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=3600,
        pool_pre_ping=True,
    )
    return SQLDatabase(engine)


def build_visualization_agent(db, model):
    """Build the enhanced LangGraph agent with visualization."""

    toolkit = SQLDatabaseToolkit(db=db, llm=model)
    tools = toolkit.get_tools()
    run_query_tool = next(tool for tool in tools if tool.name == "sql_db_query")

    generate_query_system_prompt = f"""
You are an expert {db.dialect} query writer for QCEW employment and wage data.

DATABASE SCHEMA:
Table: msa_wages_employment_data
- area_fips, year, qtr, annual_avg_estabs_count, annual_avg_emplvl
- total_annual_wages, avg_annual_pay, annual_avg_wkly_wage
- area_title, state

RULES:
1. ALWAYS use qtr = 'A' for annual data
2. Use ILIKE for MSA names
3. ORDER BY year ASC for trends
4. NEVER use DELETE, UPDATE, INSERT, DROP
"""

    def classify_intent_node(state):
        return classify_intent(state, model)

    def generate_query_node(state):
        llm_with_tools = model.bind_tools([run_query_tool])
        response = llm_with_tools.invoke(
            [{"role": "system", "content": generate_query_system_prompt}] + list(state["messages"])
        )
        return {"messages": [response]}

    def run_query_node(state):
        messages = list(state["messages"])
        last_message = messages[-1]

        if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
            return {"sql_valid": False}

        query = last_message.tool_calls[0]["args"]["query"]
        result = execute_query_with_handoff(db, query, intent=state.get("intent", "answer"))

        return {
            "generated_sql": query,
            "sql_valid": result["success"],
            "columns": result["columns"],
            "row_count": result["row_count"],
            "data_preview": result["data_preview"],
            "workspace": result["workspace"]
        }

    def validate_columns_node(state):
        return validate_columns(state)

    def analyze_results_node(state):
        from langchain_core.messages import AIMessage
        user_q = state["messages"][-2].content if len(state["messages"]) > 1 else "Unknown"
        prompt = f"Analyze this data for: {user_q}\n\nData:\n{state.get('data_preview', 'No data')}"
        response = model.invoke([{"role": "user", "content": prompt}])
        return {"analysis": response.content, "messages": [AIMessage(content=response.content)]}

    def generate_plotly_node(state):
        return generate_plotly_code(state, model)

    def execute_code_node_wrapper(state):
        return execute_code_node(state, model)

    def analyze_artifact_node(state):
        return analyze_with_artifact(state, model)

    # Routing functions
    def route_by_intent(state) -> Literal["analyze_results", "validate_columns"]:
        if state.get("intent") in ["visualize", "multi_chart"] and state.get("workspace"):
            return "validate_columns"
        return "analyze_results"

    def route_after_execution(state) -> Literal["analyze_artifact", "generate_plotly", END]:
        if state.get("execution_success"):
            return "analyze_artifact"
        retry = state.get("retry_count", 0)
        if retry < 3:
            return "generate_plotly"
        return END

    def should_continue(state) -> Literal[END, "run_query"]:
        last = list(state["messages"])[-1]
        if not hasattr(last, 'tool_calls') or not last.tool_calls:
            return END
        return "run_query"

    # Build graph
    builder = StateGraph(VisualizationState)

    builder.add_node("classify_intent", classify_intent_node)
    builder.add_node("generate_query", generate_query_node)
    builder.add_node("run_query", run_query_node)
    builder.add_node("validate_columns", validate_columns_node)
    builder.add_node("analyze_results", analyze_results_node)
    builder.add_node("generate_plotly", generate_plotly_node)
    builder.add_node("execute_code", execute_code_node_wrapper)
    builder.add_node("analyze_artifact", analyze_artifact_node)

    builder.add_edge(START, "classify_intent")
    builder.add_edge("classify_intent", "generate_query")
    builder.add_conditional_edges("generate_query", should_continue)
    builder.add_conditional_edges("run_query", route_by_intent)
    builder.add_edge("validate_columns", "generate_plotly")
    builder.add_edge("generate_plotly", "execute_code")
    builder.add_conditional_edges("execute_code", route_after_execution)
    builder.add_edge("analyze_results", END)
    builder.add_edge("analyze_artifact", END)

    return builder.compile()


def classify_single(question: str, output_path: str = None) -> dict:
    """Classify a single question using the visualization agent."""
    start_time = time.time()

    model = setup_model()
    db = setup_database()
    agent = build_visualization_agent(db, model)

    initial_state = {
        "messages": [{"role": "user", "content": question}],
        "intent": "answer",
        "sql_valid": False,
        "columns": [],
        "row_count": 0,
        "workspace": None,
        "execution_success": False,
        "retry_count": 0,
    }

    result = agent.invoke(initial_state)
    execution_time = time.time() - start_time

    if output_path and result.get("artifact_html"):
        with open(output_path, 'w') as f:
            f.write(result["artifact_html"])

    return {
        "analysis": result.get("analysis", ""),
        "intent": result.get("intent", "answer"),
        "num_charts": result.get("num_charts", 0),
        "artifact_html": result.get("artifact_html"),
        "artifact_path": result.get("artifact_path"),
        "chart_type": result.get("chart_type"),
        "execution_success": result.get("execution_success"),
        "execution_attempts": result.get("execution_attempts", 1),
        "row_count": result.get("row_count", 0),
        "execution_time_seconds": round(execution_time, 2)
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Visualization Agent")
    parser.add_argument("question", type=str, help="Your question")
    parser.add_argument("--output", type=str, help="Save HTML artifact to path")
    args = parser.parse_args()

    result = classify_single(args.question, args.output)

    print(f"\nIntent: {result['intent']}")
    print(f"Time: {result['execution_time_seconds']}s")
    if result.get("chart_type"):
        print(f"Chart: {result['chart_type']} (attempts: {result['execution_attempts']})")
    print(f"\nAnalysis:\n{result['analysis']}")
    if result.get("artifact_path"):
        print(f"\n✓ Chart: {result['artifact_path']}")
```

### 8.3 End-to-End Tests

Create `tests/test_visualization_agent.py`:

```python
"""End-to-end tests for visualization agent."""
import pytest
from visualization_agent import classify_single
from workspace import cleanup_old_workspaces


def test_simple_text_answer():
    """Text-only questions should work."""
    result = classify_single("What is the average wage in Austin in 2023?")
    assert result.get("analysis")
    assert result["intent"] == "answer"
    print(f"✓ Text answer in {result['execution_time_seconds']}s")


def test_line_chart():
    """Test line chart generation."""
    result = classify_single("Create a line chart showing wage trends for Austin from 2010 to 2024")
    assert result["intent"] == "visualize"
    assert result.get("artifact_html")
    print(f"✓ Line chart in {result['execution_time_seconds']}s")


def test_multi_chart_detection():
    """Test multi-chart detection."""
    result = classify_single("Show wages AND employment trends for Texas cities")
    assert result["intent"] in ["visualize", "multi_chart"]
    print(f"✓ Multi-chart detection: {result['intent']} ({result.get('num_charts', 1)} charts)")


def test_cleanup():
    """Clean up old workspaces."""
    cleaned = cleanup_old_workspaces(max_age_hours=0)
    print(f"✓ Cleaned {cleaned} workspaces")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

---

## 9. File Structure

```
City-Growth-AI-Agent/
├── sql_agent.py              # Original agent
├── visualization_agent.py    # Enhanced agent
├── workspace.py              # Job workspace management
├── tools.py                  # Data handoff tools
├── prompts.py                # System prompts
├── models.py                 # Pydantic models
├── runner.py                 # Code execution with recovery
├── validator.py              # Code validation
├── state.py                  # State definitions
├── tests/
│   ├── test_handoff.py
│   ├── test_code_generation.py
│   ├── test_runner.py
│   └── test_visualization_agent.py
└── docs/
    └── VISUALIZATION_IMPLEMENTATION_PLAN.md
```

---

## 10. Common Pitfalls

### Pitfall 1: Missing State Reducers

**Problem:** Messages overwrite instead of accumulate.

**Solution:** Use `Annotated[list, add_messages]`:
```python
messages: Annotated[list, add_messages]  # ✅
```

### Pitfall 2: String Parsing for LLM Output

**Problem:** Fragile parsing of markdown code blocks.

**Solution:** Use `model.with_structured_output(PydanticModel)`.

### Pitfall 3: No Error Recovery

**Problem:** First code execution failure ends the workflow.

**Solution:** Implement retry loop with LLM code fixing (max 3 attempts).

### Pitfall 4: LLM Generates Invalid Column Names

**Problem:** LLM writes `df['Annual Pay']` but column is `avg_annual_pay`.

**Solution:** Optional `validate_columns` node (can disable if latency is too high).

### Pitfall 5: Workspace Not Cleaned Up

**Problem:** `/tmp/viz_jobs/` fills up.

**Solution:** Run `cleanup_old_workspaces()` periodically.

---

## 11. Testing Checklist

### Phase 1
- [ ] Workspace creation and cleanup
- [ ] Small queries return data in context
- [ ] Large queries save to CSV
- [ ] Execution timing tracked

### Phase 2
- [ ] LLM intent classification works
- [ ] Multi-chart detection works
- [ ] Structured output returns Pydantic models
- [ ] Code includes read_csv and write_html

### Phase 3
- [ ] Code validation catches dangerous imports
- [ ] Valid code executes successfully
- [ ] Error recovery fixes broken code
- [ ] Timeout kills long-running code

### Phase 4
- [ ] State uses `add_messages` reducer
- [ ] Text questions work
- [ ] Visualization questions produce HTML
- [ ] Error recovery works end-to-end
- [ ] Timing and attempts tracked

---

## Summary

This plan addresses the "context stuffing" problem with file-based data handoff, enhanced with LangGraph best practices:

1. **LLM Intent Classification** — Detects single charts and multi-chart requests
2. **Data Handoff** — CSV file passing for large datasets
3. **Structured Output** — Pydantic models everywhere (no string parsing)
4. **Error Recovery Loop** — Max 3 retries with LLM code fixing
5. **State Reducers** — Proper message accumulation with `add_messages`
6. **Connection Pooling** — Production-ready DB connections
7. **Execution Timing** — Performance monitoring built-in
8. **Graceful Degradation** — Each node fails safely

**Key insight:** The LLM reasons about **SCHEMA**, not **DATA**. It sees `columns: [year, area_title, avg_annual_pay], row_count: 10000`, not 10,000 rows.
