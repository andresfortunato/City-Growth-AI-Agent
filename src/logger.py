"""
logger.py - Structured logging for visualization agent

All agent runs are logged to logs/agent_runs.jsonl
Each line is a JSON object with query, outcome, timing, and any errors.
"""

import json
import os
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_FILE = LOG_DIR / "agent_runs.jsonl"


def setup_logging():
    """Create logs directory if it doesn't exist."""
    LOG_DIR.mkdir(exist_ok=True)


def log_run(
    query: str,
    intent: str,
    success: bool,
    execution_time_seconds: float,
    error: str = None,
    warnings: list = None,
    metadata: dict = None
):
    """
    Log a single agent run to the JSONL file.

    Args:
        query: The user's original question
        intent: Classified intent (answer/visualize/multi_chart)
        success: Whether the run completed successfully
        execution_time_seconds: Total execution time
        error: Error message if failed
        warnings: List of non-fatal warnings
        metadata: Additional data (row_count, chart_type, etc.)
    """
    setup_logging()

    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "query": query,
        "intent": intent,
        "success": success,
        "execution_time_seconds": execution_time_seconds,
        "error": error,
        "warnings": warnings or [],
        "metadata": metadata or {}
    }

    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(log_entry) + "\n")


def log_warning(message: str) -> str:
    """
    Log a warning and return it (for collecting in state).
    Use this instead of silently ignoring errors.
    """
    print(f"WARNING: {message}")
    return message
