#!/bin/bash
# start_server.sh - Start the City Growth AI backend server

cd "$(dirname "$0")/.."

echo "Starting City Growth AI API server..."
echo "API will be available at http://localhost:8001"
echo "Press Ctrl+C to stop"
echo ""

uv run uvicorn api.app:app --host 0.0.0.0 --port 8001 --reload
