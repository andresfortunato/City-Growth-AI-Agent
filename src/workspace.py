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
    def json_path(self) -> Path:
        """Path to Plotly JSON spec (for web embedding)."""
        return self.path / "output.json"

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
