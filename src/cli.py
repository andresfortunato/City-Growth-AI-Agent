#!/usr/bin/env python3
"""
cli.py - CLI for the City Growth AI conversational agent

Usage:
    uv run src/cli.py                    # Interactive mode
    uv run src/cli.py "your question"    # Single question mode
"""

import asyncio
import sys


async def interactive_mode():
    """Run interactive conversation loop."""
    from conversation import chat

    print("City Growth AI Agent")
    print("=" * 50)
    print("Ask questions about employment and wages in US cities.")
    print("Data: QCEW MSA employment/wage data, 2001-2024")
    print()
    print("Commands:")
    print("  'quit' or 'exit' - End conversation")
    print("  'new' - Start new conversation thread")
    print("=" * 50)

    thread_id = None

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "q"):
            print("Goodbye!")
            break

        if user_input.lower() == "new":
            thread_id = None
            print("Starting new conversation...")
            continue

        try:
            result = await chat(user_input, thread_id)
            thread_id = result["thread_id"]
            print(f"\nAssistant: {result['response']}")
        except Exception as e:
            print(f"\nError: {e}")
            print("Try rephrasing your question or type 'new' to start fresh.")


async def single_question_mode(question: str):
    """Answer a single question and exit."""
    from conversation import chat

    try:
        result = await chat(question)
        print(result["response"])
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def main():
    """Main entry point."""
    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
        asyncio.run(single_question_mode(question))
    else:
        asyncio.run(interactive_mode())


if __name__ == "__main__":
    main()
