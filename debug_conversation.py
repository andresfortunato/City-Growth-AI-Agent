#!/usr/bin/env python3
"""Debug script to reproduce the conversation duplication bug."""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from conversation import chat


async def test_conversation():
    """Test a simple two-turn conversation."""

    print("=" * 80)
    print("TURN 1: Initial question")
    print("=" * 80)

    result1 = await chat("What cities are available in Texas?")
    thread_id = result1["thread_id"]

    print(f"Thread ID: {thread_id}")
    print(f"Response: {result1['response'][:200]}...")
    print(f"Tool calls: {result1['tool_calls']}")

    print("\n" + "=" * 80)
    print("TURN 2: Follow-up question")
    print("=" * 80)

    result2 = await chat("What about California?", thread_id=thread_id)

    print(f"Thread ID: {result2['thread_id']}")
    print(f"Response: {result2['response'][:200]}...")
    print(f"Tool calls: {result2['tool_calls']}")

    print("\n" + "=" * 80)
    print("ANALYSIS")
    print("=" * 80)

    # Check if the responses are the same
    if result1['response'] == result2['response']:
        print("BUG CONFIRMED: Responses are identical!")
    else:
        print("Responses are different (as expected)")

    # Check if tool calls are the same
    if result1['tool_calls'] == result2['tool_calls']:
        print("BUG: Tool calls are identical!")
    else:
        print("Tool calls are different (as expected)")


if __name__ == "__main__":
    asyncio.run(test_conversation())
