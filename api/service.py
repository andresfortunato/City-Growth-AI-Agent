"""
service.py - Business logic and SQLite operations for chat persistence

Handles message sending, conversation management, and database operations.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, List, AsyncGenerator
from contextlib import contextmanager

# Database path
DATABASE_PATH = Path(__file__).parent.parent / "database" / "app.db"


@contextmanager
def get_db():
    """Get SQLite database connection with row factory."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


class ChatService:
    """Service layer for chat operations."""

    async def send_message(
        self,
        message: str,
        thread_id: Optional[str] = None,
        use_postgres: bool = False,
    ) -> dict:
        """Send a message to the agent and get a response.

        Args:
            message: User's message text
            thread_id: Existing conversation ID (creates new if None)
            use_postgres: Use PostgresSaver for checkpointing (for production)

        Returns:
            dict with response, thread_id, artifact_json, artifact_path, tool_calls
        """
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from conversation import chat

        # Call the agent
        result = await chat(message, thread_id)

        # Get or create conversation in SQLite
        actual_thread_id = result["thread_id"]
        is_new_conversation = thread_id is None

        if is_new_conversation:
            # Create new conversation
            title = message[:100] if len(message) > 100 else message
            self._create_conversation(actual_thread_id, title)

        # Save user message
        self._save_message(
            conversation_id=actual_thread_id,
            role="user",
            content=message,
        )

        # Save assistant response
        self._save_message(
            conversation_id=actual_thread_id,
            role="assistant",
            content=result["response"],
            artifact_json=result.get("artifact_json"),
            artifact_path=result.get("artifact_path"),
            tool_calls=result.get("tool_calls"),
        )

        return {
            "response": result["response"],
            "thread_id": actual_thread_id,
            "artifact_json": result.get("artifact_json"),
            "artifact_path": result.get("artifact_path"),
            "tool_calls": result.get("tool_calls", []),
        }

    async def stream_chat(
        self,
        message: str,
        thread_id: Optional[str] = None,
    ) -> AsyncGenerator[dict, None]:
        """Stream chat responses (for WebSocket).

        Yields events like:
        - {"type": "conversation_created", "thread_id": "..."}
        - {"type": "token", "content": "..."}
        - {"type": "complete", "thread_id": "...", "content": "...", "artifact_json": "..."}
        - {"type": "error", "error": "..."}
        """
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
            from conversation import chat

            is_new_conversation = thread_id is None

            # For now, use non-streaming chat and yield complete response
            # TODO: Implement true streaming with astream_events
            result = await chat(message, thread_id)
            actual_thread_id = result["thread_id"]

            # Notify about new conversation
            if is_new_conversation:
                title = message[:100] if len(message) > 100 else message
                self._create_conversation(actual_thread_id, title)
                yield {"type": "conversation_created", "thread_id": actual_thread_id}

            # Save messages to SQLite
            self._save_message(
                conversation_id=actual_thread_id,
                role="user",
                content=message,
            )

            self._save_message(
                conversation_id=actual_thread_id,
                role="assistant",
                content=result["response"],
                artifact_json=result.get("artifact_json"),
                artifact_path=result.get("artifact_path"),
                tool_calls=result.get("tool_calls"),
            )

            # Yield complete response
            yield {
                "type": "complete",
                "thread_id": actual_thread_id,
                "content": result["response"],
                "artifact_json": result.get("artifact_json"),
                "artifact_path": result.get("artifact_path"),
            }

        except Exception as e:
            yield {"type": "error", "error": str(e)}

    def get_conversations(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[List[dict], int]:
        """Get list of conversations ordered by most recent.

        Returns:
            Tuple of (conversations list, total count)
        """
        with get_db() as conn:
            # Get total count
            total = conn.execute(
                "SELECT COUNT(*) FROM conversations"
            ).fetchone()[0]

            # Get paginated conversations
            rows = conn.execute(
                """
                SELECT id, title, created_at, updated_at, message_count
                FROM conversations
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()

            conversations = [
                {
                    "id": row["id"],
                    "title": row["title"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "message_count": row["message_count"],
                }
                for row in rows
            ]

        return conversations, total

    def get_conversation_detail(self, conversation_id: str) -> Optional[dict]:
        """Get full conversation with all messages.

        Returns:
            Conversation dict with messages, or None if not found
        """
        with get_db() as conn:
            # Get conversation
            conv_row = conn.execute(
                """
                SELECT id, title, created_at, updated_at, message_count
                FROM conversations
                WHERE id = ?
                """,
                (conversation_id,),
            ).fetchone()

            if not conv_row:
                return None

            # Get messages
            msg_rows = conn.execute(
                """
                SELECT id, role, content, artifact_json, artifact_path, tool_calls, created_at
                FROM messages
                WHERE conversation_id = ?
                ORDER BY created_at ASC
                """,
                (conversation_id,),
            ).fetchall()

            messages = [
                {
                    "id": row["id"],
                    "role": row["role"],
                    "content": row["content"],
                    "artifact_json": row["artifact_json"],
                    "artifact_path": row["artifact_path"],
                    "tool_calls": row["tool_calls"],
                    "created_at": row["created_at"],
                }
                for row in msg_rows
            ]

            return {
                "id": conv_row["id"],
                "title": conv_row["title"],
                "created_at": conv_row["created_at"],
                "updated_at": conv_row["updated_at"],
                "message_count": conv_row["message_count"],
                "messages": messages,
            }

    def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation and all its messages.

        Returns:
            True if deleted, False if not found
        """
        with get_db() as conn:
            # Check if exists
            exists = conn.execute(
                "SELECT 1 FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()

            if not exists:
                return False

            # Delete (CASCADE will handle messages)
            conn.execute(
                "DELETE FROM conversations WHERE id = ?",
                (conversation_id,),
            )
            conn.commit()
            return True

    def update_conversation_title(self, conversation_id: str, title: str) -> bool:
        """Update a conversation's title.

        Returns:
            True if updated, False if not found
        """
        with get_db() as conn:
            cursor = conn.execute(
                "UPDATE conversations SET title = ? WHERE id = ?",
                (title, conversation_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    # ─── Private helpers ───────────────────────────────────────────────────────

    def _create_conversation(self, conversation_id: str, title: str):
        """Create a new conversation record."""
        with get_db() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO conversations (id, title)
                VALUES (?, ?)
                """,
                (conversation_id, title),
            )
            conn.commit()

    def _save_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        artifact_json: Optional[str] = None,
        artifact_path: Optional[str] = None,
        tool_calls: Optional[list] = None,
    ):
        """Save a message to the database."""
        with get_db() as conn:
            tool_calls_json = json.dumps(tool_calls) if tool_calls else None

            conn.execute(
                """
                INSERT INTO messages (conversation_id, role, content, artifact_json, artifact_path, tool_calls)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (conversation_id, role, content, artifact_json, artifact_path, tool_calls_json),
            )
            conn.commit()


# Singleton service instance
_service: Optional[ChatService] = None


def get_chat_service() -> ChatService:
    """Get or create the chat service singleton."""
    global _service
    if _service is None:
        _service = ChatService()
    return _service
