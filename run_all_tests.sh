#!/bin/bash
# Run all visualization agent tests

echo "========================================="
echo "Running All Visualization Agent Tests"
echo "========================================="
echo

source .venv/bin/activate

echo "Phase 1 Tests: Data Handoff..."
python tests/test_handoff.py
echo

echo "Phase 2 Tests: Code Generation..."
python tests/test_code_generation.py
echo

echo "Phase 3 Tests: Code Runner..."
python tests/test_runner.py
echo

echo "Integration Tests..."
python tests/test_visualization_agent.py
echo

echo "========================================="
echo "All Tests Complete!"
echo "========================================="
