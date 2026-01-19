#!/usr/bin/env python3
"""
Utility script to access LangSmith traces via API.

Usage:
    python langsmith_trace.py                    # List recent runs
    python langsmith_trace.py <run_id>          # Get details for specific run
    python langsmith_trace.py --project <name>   # Filter by project
    python langsmith_trace.py --limit 10         # Limit number of results
"""

import argparse
import os
import json
import re
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from langsmith import Client

# Load environment variables
load_dotenv()


def format_trace_summary(run):
    """Format a trace run for display."""
    start_time = _coerce_datetime(run.start_time)
    end_time = _coerce_datetime(run.end_time)
    
    duration = None
    if start_time and end_time:
        duration = (end_time - start_time).total_seconds()
    
    return {
        "run_id": run.id,
        "name": run.name or "N/A",
        "status": run.status,
        "start_time": start_time.isoformat() if start_time else None,
        "duration_seconds": duration,
        "error": run.error if hasattr(run, 'error') else None,
        "inputs": run.inputs if hasattr(run, 'inputs') else {},
        "outputs": run.outputs if hasattr(run, 'outputs') else {},
    }

def _coerce_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        timestamp = value / 1000 if value > 1_000_000_000_000 else value
        return datetime.fromtimestamp(timestamp)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None

def _read_run(client, run_id):
    if hasattr(client, "read_run"):
        try:
            return client.read_run(run_id, load_child_runs=True)
        except TypeError:
            return client.read_run(run_id)
    if hasattr(client, "get_run"):
        return client.get_run(run_id)
    raise AttributeError("LangSmith Client missing read_run/get_run")

def _flatten_runs(runs, depth=0):
    for run in runs or []:
        yield depth, run
        child_runs = getattr(run, "child_runs", None) or []
        yield from _flatten_runs(child_runs, depth + 1)

NOISY_KEYS = {
    "__gemini_function_call_thought_signatures__",
}

THOUGHT_KEYS = {
    "analysis",
    "reasoning",
    "thoughts",
    "scratchpad",
}

SQL_PATTERN = re.compile(r"\b(select|insert|update|delete|with)\b", re.IGNORECASE)

def _sanitize_value(value, max_field_chars):
    if isinstance(value, dict):
        return {
            key: _sanitize_value(val, max_field_chars)
            for key, val in value.items()
            if key not in NOISY_KEYS
        }
    if isinstance(value, list):
        return [_sanitize_value(item, max_field_chars) for item in value]
    if (
        isinstance(value, str)
        and max_field_chars
        and max_field_chars > 0
        and len(value) > max_field_chars
    ):
        return f"{value[:max_field_chars]}...(truncated, {len(value)} chars)"
    return value

def _parse_tool_call(call):
    if not isinstance(call, dict):
        return None
    name = call.get("name")
    args = call.get("args") if "args" in call else call.get("arguments")
    if name is None and isinstance(call.get("function"), dict):
        name = call["function"].get("name")
        args = call["function"].get("arguments", args)
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            pass
    tool_call = {
        "name": name,
        "args": args,
    }
    if call.get("id") is not None:
        tool_call["id"] = call.get("id")
    return tool_call

def _extract_tool_calls(value):
    tool_calls = []

    def walk(obj):
        if isinstance(obj, dict):
            if "tool_calls" in obj and isinstance(obj["tool_calls"], list):
                for call in obj["tool_calls"]:
                    parsed = _parse_tool_call(call)
                    if parsed and parsed.get("name"):
                        tool_calls.append(parsed)
            if "function_call" in obj and isinstance(obj["function_call"], dict):
                parsed = _parse_tool_call(obj["function_call"])
                if parsed and parsed.get("name"):
                    tool_calls.append(parsed)
            for val in obj.values():
                walk(val)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(value)
    return tool_calls

def _extract_sql_queries(tool_calls, value):
    queries = []
    for call in tool_calls:
        name = (call.get("name") or "").lower()
        if "sql" in name or "query" in name:
            args = call.get("args")
            if isinstance(args, dict):
                for key in ("query", "sql", "statement"):
                    if isinstance(args.get(key), str):
                        queries.append(args[key])

    if queries:
        return list(dict.fromkeys(queries))

    def walk(obj):
        if isinstance(obj, dict):
            for val in obj.values():
                walk(val)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)
        elif isinstance(obj, str):
            if SQL_PATTERN.search(obj):
                queries.append(obj)

    walk(value)
    return list(dict.fromkeys(queries))

def _extract_thoughts(value):
    thoughts = []

    def walk(obj):
        if isinstance(obj, dict):
            for key, val in obj.items():
                if key in THOUGHT_KEYS and isinstance(val, str):
                    thoughts.append(val)
                else:
                    walk(val)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(value)
    return list(dict.fromkeys(thoughts))

def _extract_artifacts(value):
    artifacts = []

    def walk(obj):
        if isinstance(obj, dict):
            for key, val in obj.items():
                if key in ("artifact_path", "artifact_paths"):
                    if isinstance(val, str):
                        artifacts.append(val)
                    elif isinstance(val, list):
                        artifacts.extend([item for item in val if isinstance(item, str)])
                walk(val)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(value)
    return list(dict.fromkeys(artifacts))

def _run_to_dict(run, max_field_chars=None):
    start_time = _coerce_datetime(run.start_time)
    end_time = _coerce_datetime(run.end_time)
    duration = (end_time - start_time).total_seconds() if start_time and end_time else None
    inputs = _sanitize_value(getattr(run, "inputs", None), max_field_chars)
    outputs = _sanitize_value(getattr(run, "outputs", None), max_field_chars)
    extra = _sanitize_value(getattr(run, "extra", None), max_field_chars)
    metadata = _sanitize_value(getattr(run, "metadata", None), max_field_chars)
    events = _sanitize_value(getattr(run, "events", None), max_field_chars)

    run_data = {
        "run_id": str(run.id),
        "name": run.name,
        "run_type": run.run_type,
        "status": run.status,
        "start_time": start_time.isoformat() if start_time else None,
        "end_time": end_time.isoformat() if end_time else None,
        "duration_seconds": duration,
        "error": run.error,
        "tags": run.tags,
        "inputs": inputs,
        "outputs": outputs,
        "metadata": metadata,
        "extra": extra,
        "events": events,
    }

    tool_calls = _extract_tool_calls({"inputs": inputs, "outputs": outputs, "events": events})
    run_data["tool_calls"] = tool_calls
    run_data["sql_queries"] = _extract_sql_queries(tool_calls, {"inputs": inputs, "outputs": outputs})
    run_data["artifacts"] = _extract_artifacts({"outputs": outputs})
    run_data["logged_thoughts"] = _extract_thoughts({"inputs": inputs, "outputs": outputs})

    child_runs = getattr(run, "child_runs", None)
    if child_runs:
        run_data["child_runs"] = [_run_to_dict(child, max_field_chars) for child in child_runs]
    return run_data

def _render_md_run(run_data):
    lines = []
    lines.append(f"# Trace {run_data.get('run_id')}")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- Name: {run_data.get('name')}")
    lines.append(f"- Type: {run_data.get('run_type')}")
    lines.append(f"- Status: {run_data.get('status')}")
    lines.append(f"- Start: {run_data.get('start_time')}")
    lines.append(f"- End: {run_data.get('end_time')}")
    lines.append(f"- Duration seconds: {run_data.get('duration_seconds')}")
    lines.append(f"- Error: {run_data.get('error')}")
    lines.append("")

    def add_block(title, payload):
        lines.append(f"## {title}")
        lines.append("```json")
        lines.append(json.dumps(payload, indent=2, default=str))
        lines.append("```")
        lines.append("")

    add_block("Inputs", run_data.get("inputs"))
    add_block("Outputs", run_data.get("outputs"))
    add_block("Metadata", run_data.get("metadata"))

    lines.append("## Important")
    lines.append("```json")
    lines.append(json.dumps({
        "tool_calls": run_data.get("tool_calls"),
        "sql_queries": run_data.get("sql_queries"),
        "artifacts": run_data.get("artifacts"),
        "logged_thoughts": run_data.get("logged_thoughts"),
    }, indent=2, default=str))
    lines.append("```")
    lines.append("")

    if run_data.get("child_runs"):
        lines.append("## Child Runs")
        def add_child(child, depth=0):
            indent = "  " * depth
            lines.append(f"{indent}- {child.get('name')} ({child.get('status')}) [{child.get('run_id')}]")
            for nested in child.get("child_runs", []) or []:
                add_child(nested, depth + 1)
        for child in run_data["child_runs"]:
            add_child(child)
        lines.append("")

    return "\n".join(lines)

def _write_output(content, output_path):
    if output_path:
        Path(output_path).write_text(content, encoding="utf-8")
    else:
        print(content)

def list_runs_data(client, project_name=None, limit=20, max_field_chars=None):
    runs = list(client.list_runs(
        project_name=project_name or os.getenv("LANGSMITH_PROJECT", "city-growth-ai"),
        limit=limit,
    ))
    summaries = []
    for run in runs:
        summaries.append(format_trace_summary(run))
    return {
        "project_name": project_name or os.getenv("LANGSMITH_PROJECT", "city-growth-ai"),
        "count": len(summaries),
        "runs": _sanitize_value(summaries, max_field_chars),
    }

def get_run_details_data(client, run_id, max_field_chars=None):
    run = _read_run(client, run_id)
    return _run_to_dict(run, max_field_chars=max_field_chars)


def list_runs(client, project_name=None, limit=20):
    """List recent runs from LangSmith."""
    print(f"\n{'='*70}")
    print("LANGSMITH TRACES")
    print(f"{'='*70}\n")
    
    try:
        data = list_runs_data(client, project_name=project_name, limit=limit)
        runs = data["runs"]
        if not runs:
            print("No runs found.")
            return
        
        print(f"Found {len(runs)} recent runs:\n")
        
        for i, run in enumerate(runs, 1):
            print(f"{i}. Run ID: {run['run_id']}")
            print(f"   Name: {run['name']}")
            print(f"   Status: {run['status']}")
            if run['start_time']:
                print(f"   Time: {run['start_time']}")
            if run['duration_seconds']:
                print(f"   Duration: {run['duration_seconds']:.2f}s")
            if run['error']:
                print(f"   Error: {run['error']}")
            print()
        
    except Exception as e:
        print(f"Error listing runs: {e}")
        return


def get_run_details(client, run_id):
    """Get detailed information about a specific run."""
    print(f"\n{'='*70}")
    print(f"TRACE DETAILS: {run_id}")
    print(f"{'='*70}\n")
    
    try:
        run = _read_run(client, run_id)
        summary = format_trace_summary(run)
        
        print("Run Summary:")
        print(json.dumps(summary, indent=2, default=str))
        print()
        
        # Get child runs (sub-steps)
        child_runs = getattr(run, "child_runs", None)
        if child_runs:
            flat_children = list(_flatten_runs(child_runs))
            print(f"\nChild Runs ({len(flat_children)}):")
            for depth, child in flat_children:
                child_summary = format_trace_summary(child)
                indent = "  " * (depth + 1)
                print(f"\n{indent}- {child_summary['name']} ({child_summary['status']})")
                if child_summary['duration_seconds']:
                    print(f"{indent}  Duration: {child_summary['duration_seconds']:.2f}s")
                if child_summary.get('inputs'):
                    print(f"{indent}  Inputs: {json.dumps(child_summary['inputs'], indent=6, default=str)}")
                if child_summary.get('outputs'):
                    print(f"{indent}  Outputs: {json.dumps(child_summary['outputs'], indent=6, default=str)}")
        else:
            child_runs = list(client.list_runs(parent_run_id=run_id))
            if child_runs:
                print(f"\nChild Runs ({len(child_runs)}):")
                for child in child_runs:
                    child_summary = format_trace_summary(child)
                    print(f"\n  - {child_summary['name']} ({child_summary['status']})")
                    if child_summary['duration_seconds']:
                        print(f"    Duration: {child_summary['duration_seconds']:.2f}s")
                    if child_summary.get('inputs'):
                        print(f"    Inputs: {json.dumps(child_summary['inputs'], indent=6, default=str)}")
                    if child_summary.get('outputs'):
                        print(f"    Outputs: {json.dumps(child_summary['outputs'], indent=6, default=str)}")
        
    except Exception as e:
        print(f"Error getting run details: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Access LangSmith traces via API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument(
        "run_id",
        nargs="?",
        help="Run ID to get details for (optional, lists recent runs if not provided)",
    )
    
    parser.add_argument(
        "--project",
        "-p",
        help="Project name to filter by (default: from LANGSMITH_PROJECT env var)",
    )
    
    parser.add_argument(
        "--limit",
        "-l",
        type=int,
        default=20,
        help="Number of runs to list (default: 20)",
    )
    
    parser.add_argument(
        "--json",
        "-j",
        action="store_true",
        help="Output as JSON",
    )

    parser.add_argument(
        "--format",
        choices=["text", "json", "md"],
        default="text",
        help="Output format for trace details (default: text)",
    )

    parser.add_argument(
        "--output",
        "-o",
        help="Write output to a file (default: stdout).",
    )

    parser.add_argument(
        "--max-field-chars",
        type=int,
        default=10000,
        help="Truncate long strings in structured output (0 disables).",
    )
    
    args = parser.parse_args()
    if args.json:
        args.format = "json"
    
    # Check API key
    api_key = os.getenv("LANGSMITH_API_KEY")
    if not api_key:
        print("Error: LANGSMITH_API_KEY not set in environment")
        print("Add it to .env file or export it:")
        print("  export LANGSMITH_API_KEY=your_key_here")
        return 1
    
    # Initialize client
    client = Client(api_key=api_key, auto_batch_tracing=False)
    
    if args.run_id:
        if args.format == "text" and not args.output:
            get_run_details(client, args.run_id)
        else:
            data = get_run_details_data(
                client,
                args.run_id,
                max_field_chars=args.max_field_chars,
            )
            if args.format == "json":
                content = json.dumps(data, indent=2, default=str)
            elif args.format == "md":
                content = _render_md_run(data)
            else:
                content = json.dumps(data, indent=2, default=str)
            output_path = args.output
            if output_path is None:
                output_path = f"trace_{args.run_id}.{args.format}"
            _write_output(content, output_path)
    else:
        if args.format == "text" and not args.output:
            list_runs(client, project_name=args.project, limit=args.limit)
        else:
            data = list_runs_data(
                client,
                project_name=args.project,
                limit=args.limit,
                max_field_chars=args.max_field_chars,
            )
            if args.format == "json":
                content = json.dumps(data, indent=2, default=str)
            elif args.format == "md":
                content = _render_md_run({
                    "run_id": "run_list",
                    "name": "run_list",
                    "run_type": "list",
                    "status": None,
                    "start_time": None,
                    "end_time": None,
                    "duration_seconds": None,
                    "error": None,
                    "inputs": None,
                    "outputs": data,
                    "metadata": None,
                    "tool_calls": None,
                    "sql_queries": None,
                    "artifacts": None,
                    "logged_thoughts": None,
                })
            else:
                content = json.dumps(data, indent=2, default=str)
            _write_output(content, args.output)
    
    return 0


if __name__ == "__main__":
    exit(main())
