"""
conversation.py - Async conversation interface for the City Growth AI agent

Provides chat() function for multi-turn conversations with thread_id support.
"""

import json
import uuid
from agent import get_agent


def _extract_artifact_metadata(messages: list) -> tuple[str | None, str | None]:
    """Extract artifact JSON and path from tool response messages.

    Looks for ARTIFACT_METADATA:{...} in tool responses and extracts
    the Plotly JSON spec and artifact path.

    Returns:
        Tuple of (artifact_json, artifact_path) or (None, None)
    """
    for msg in messages:
        content = None
        if hasattr(msg, "content"):
            content = msg.content
        elif isinstance(msg, dict) and "content" in msg:
            content = msg["content"]

        if content and isinstance(content, str) and "ARTIFACT_METADATA:" in content:
            try:
                # Extract the JSON after the marker
                marker_pos = content.find("ARTIFACT_METADATA:")
                json_start = marker_pos + len("ARTIFACT_METADATA:")
                metadata_str = content[json_start:].strip()

                # Handle case where there might be more text after the JSON
                # Find the end of the JSON object
                brace_count = 0
                json_end = 0
                for i, char in enumerate(metadata_str):
                    if char == "{":
                        brace_count += 1
                    elif char == "}":
                        brace_count -= 1
                        if brace_count == 0:
                            json_end = i + 1
                            break

                if json_end > 0:
                    metadata_str = metadata_str[:json_end]
                    metadata = json.loads(metadata_str)
                    return metadata.get("artifact_json"), metadata.get("artifact_path")
            except (json.JSONDecodeError, KeyError):
                pass

    return None, None


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
        - artifact_json: Plotly JSON spec if visualization created (for web embedding)
        - artifact_path: Path to HTML artifact if created
    """
    if thread_id is None:
        thread_id = uuid.uuid4().hex[:8]

    agent = get_agent()

    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    # Get current state to know where new messages start
    # This is needed because ainvoke returns FULL history, not just new messages
    try:
        current_state = await agent.aget_state(config)
        existing_message_count = len(current_state.values.get("messages", []))
    except Exception:
        # New thread or no prior state
        existing_message_count = 0

    # Invoke the agent
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": message}]},
        config,
    )

    # Extract only NEW messages from this turn (not full history)
    all_messages = result["messages"]
    new_messages = all_messages[existing_message_count:]

    # Get the final AI response from new messages only
    # Fall back to last message if no new messages (shouldn't happen)
    if new_messages:
        final_message = new_messages[-1]
    else:
        final_message = all_messages[-1]

    response_text = final_message.content if hasattr(final_message, "content") else str(final_message)

    # Clean up response text - remove ARTIFACT_METADATA from visible response
    if "ARTIFACT_METADATA:" in response_text:
        response_text = response_text.split("ARTIFACT_METADATA:")[0].strip()

    # Extract artifact metadata from NEW messages only (not previous turns)
    artifact_json, artifact_path = _extract_artifact_metadata(new_messages if new_messages else all_messages)

    # Collect tool calls made during THIS turn only
    tool_calls = []
    messages_to_scan = new_messages if new_messages else all_messages
    for msg in messages_to_scan:
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
        "artifact_json": artifact_json,
        "artifact_path": artifact_path,
    }


def chat_sync(message: str, thread_id: str = None) -> dict:
    """
    Synchronous wrapper for chat().

    Useful for CLI or testing when you don't want to manage async.
    """
    import asyncio
    return asyncio.run(chat(message, thread_id))
