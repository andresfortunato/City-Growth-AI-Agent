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
