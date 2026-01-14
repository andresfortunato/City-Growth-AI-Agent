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
from datetime import datetime
from dotenv import load_dotenv
from langsmith import Client

# Load environment variables
load_dotenv()


def format_trace_summary(run):
    """Format a trace run for display."""
    start_time = datetime.fromtimestamp(run.start_time / 1000) if run.start_time else None
    end_time = datetime.fromtimestamp(run.end_time / 1000) if run.end_time else None
    
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


def list_runs(client, project_name=None, limit=20):
    """List recent runs from LangSmith."""
    print(f"\n{'='*70}")
    print("LANGSMITH TRACES")
    print(f"{'='*70}\n")
    
    try:
        runs = client.list_runs(
            project_name=project_name or os.getenv("LANGSMITH_PROJECT", "city-growth-ai"),
            limit=limit,
        )
        
        if not runs:
            print("No runs found.")
            return
        
        print(f"Found {len(runs)} recent runs:\n")
        
        for i, run in enumerate(runs, 1):
            summary = format_trace_summary(run)
            print(f"{i}. Run ID: {summary['run_id']}")
            print(f"   Name: {summary['name']}")
            print(f"   Status: {summary['status']}")
            if summary['start_time']:
                print(f"   Time: {summary['start_time']}")
            if summary['duration_seconds']:
                print(f"   Duration: {summary['duration_seconds']:.2f}s")
            if summary['error']:
                print(f"   Error: {summary['error']}")
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
        run = client.get_run(run_id)
        summary = format_trace_summary(run)
        
        print("Run Summary:")
        print(json.dumps(summary, indent=2, default=str))
        print()
        
        # Get child runs (sub-steps)
        child_runs = list(client.list_runs(run_id=run_id))
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
    
    args = parser.parse_args()
    
    # Check API key
    api_key = os.getenv("LANGSMITH_API_KEY")
    if not api_key:
        print("Error: LANGSMITH_API_KEY not set in environment")
        print("Add it to .env file or export it:")
        print("  export LANGSMITH_API_KEY=your_key_here")
        return 1
    
    # Initialize client
    client = Client(api_key=api_key)
    
    if args.run_id:
        get_run_details(client, args.run_id)
    else:
        list_runs(client, project_name=args.project, limit=args.limit)
    
    return 0


if __name__ == "__main__":
    exit(main())
