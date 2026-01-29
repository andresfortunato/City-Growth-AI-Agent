"""
chat.py - WebSocket and REST endpoints for chat functionality
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Query

from api.models import (
    ChatRequest,
    ChatResponse,
    ConversationListResponse,
    ConversationDetail,
    ConversationSummary,
)
from api.service import get_chat_service

router = APIRouter(prefix="/api/chat", tags=["chat"])


# ─── REST Endpoints ────────────────────────────────────────────────────────────

@router.post("/message", response_model=ChatResponse)
async def send_message(request: ChatRequest):
    """Send a message and get a response (non-streaming).

    If thread_id is None, creates a new conversation.
    Returns the assistant's response along with any visualization artifacts.
    """
    service = get_chat_service()

    try:
        result = await service.send_message(
            message=request.message,
            thread_id=request.thread_id,
        )
        return ChatResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations(
    limit: int = Query(50, ge=1, le=100, description="Max conversations to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """Get list of conversations ordered by most recent."""
    service = get_chat_service()

    conversations, total = service.get_conversations(limit=limit, offset=offset)

    return ConversationListResponse(
        conversations=[ConversationSummary(**c) for c in conversations],
        total=total,
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: str):
    """Get a single conversation with all its messages."""
    service = get_chat_service()

    conversation = service.get_conversation_detail(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return ConversationDetail(**conversation)


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    """Delete a conversation and all its messages."""
    service = get_chat_service()

    deleted = service.delete_conversation(conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return {"status": "deleted", "conversation_id": conversation_id}


@router.patch("/conversations/{conversation_id}")
async def update_conversation(conversation_id: str, title: str = Query(..., min_length=1)):
    """Update a conversation's title."""
    service = get_chat_service()

    updated = service.update_conversation_title(conversation_id, title)
    if not updated:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return {"status": "updated", "conversation_id": conversation_id, "title": title}


# ─── WebSocket Endpoint ────────────────────────────────────────────────────────

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for streaming chat responses.

    Client sends:
        {"type": "message", "content": "...", "thread_id": "..." or null}
        {"type": "ping"}

    Server sends:
        {"type": "conversation_created", "thread_id": "..."}
        {"type": "token", "content": "..."}  (future: streaming tokens)
        {"type": "complete", "thread_id": "...", "content": "...", "artifact_json": "..."}
        {"type": "error", "error": "..."}
        {"type": "pong"}
    """
    await websocket.accept()
    service = get_chat_service()

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            # Handle ping/pong for keepalive
            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            # Handle chat message
            if msg_type == "message":
                content = data.get("content", "").strip()
                thread_id = data.get("thread_id")

                if not content:
                    await websocket.send_json({
                        "type": "error",
                        "error": "Message content is required",
                    })
                    continue

                # Stream responses
                async for event in service.stream_chat(content, thread_id):
                    await websocket.send_json(event)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "error": str(e)})
        except Exception:
            pass
