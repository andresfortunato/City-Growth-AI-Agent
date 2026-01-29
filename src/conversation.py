"""
conversation.py - Async conversation interface for the City Growth AI agent

Provides chat() function for multi-turn conversations with thread_id support.
"""

import uuid
from agent import get_agent


async def chat(message: str, thread_id: str = None) -> dict:
    """
    Send a message to the conversational agent.

    Args:
        message: User's message
        thread_id: Conversation thread ID for continuity.
                  Creates new thread if None.

    Returns:
        dict with:
        - response: The agent's text response
        - thread_id: The thread ID (for continuing conversation)
        - tool_calls: List of tools that were called
    """
    if thread_id is None:
        thread_id = uuid.uuid4().hex[:8]

    agent = get_agent()

    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    # Invoke the agent
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": message}]},
        config,
    )

    # Extract the final response (last AI message)
    final_message = result["messages"][-1]
    response_text = final_message.content if hasattr(final_message, "content") else str(final_message)

    # Collect tool calls made during this turn
    tool_calls = []
    for msg in result["messages"]:
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append({
                    "tool": tc["name"],
                    "args": tc.get("args", {}),
                })

    return {
        "response": response_text,
        "thread_id": thread_id,
        "tool_calls": tool_calls,
    }


def chat_sync(message: str, thread_id: str = None) -> dict:
    """
    Synchronous wrapper for chat().

    Useful for CLI or testing when you don't want to manage async.
    """
    import asyncio
    return asyncio.run(chat(message, thread_id))
