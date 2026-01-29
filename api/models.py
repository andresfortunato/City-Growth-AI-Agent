"""
models.py - Pydantic request/response schemas for the API
"""

from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel, Field


# ─── Request Models ────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    """Request body for sending a chat message."""
    message: str = Field(..., min_length=1, description="The user's message")
    thread_id: Optional[str] = Field(None, description="Conversation thread ID (creates new if None)")


# ─── Response Models ───────────────────────────────────────────────────────────

class ChatResponse(BaseModel):
    """Response from sending a chat message."""
    response: str = Field(..., description="The assistant's response text")
    thread_id: str = Field(..., description="The conversation thread ID")
    artifact_json: Optional[str] = Field(None, description="Plotly JSON spec if visualization created")
    artifact_path: Optional[str] = Field(None, description="Path to HTML artifact if created")
    tool_calls: List[dict] = Field(default_factory=list, description="Tools that were called")


class MessageDetail(BaseModel):
    """A single message in a conversation."""
    id: int
    role: str = Field(..., description="'user' or 'assistant'")
    content: str
    artifact_json: Optional[str] = None
    artifact_path: Optional[str] = None
    tool_calls: Optional[str] = None  # JSON string of tool calls
    created_at: datetime


class ConversationSummary(BaseModel):
    """Summary of a conversation for list view."""
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int


class ConversationDetail(BaseModel):
    """Full conversation with all messages."""
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int
    messages: List[MessageDetail]


class ConversationListResponse(BaseModel):
    """Response for listing conversations."""
    conversations: List[ConversationSummary]
    total: Optional[int] = None


# ─── WebSocket Message Types ───────────────────────────────────────────────────

class WSMessageIn(BaseModel):
    """Incoming WebSocket message from client."""
    type: str = Field(..., description="Message type: 'message', 'ping'")
    content: Optional[str] = None
    thread_id: Optional[str] = None


class WSMessageOut(BaseModel):
    """Outgoing WebSocket message to client."""
    type: str = Field(..., description="Message type: 'token', 'complete', 'error', 'pong', 'conversation_created'")
    content: Optional[str] = None
    thread_id: Optional[str] = None
    artifact_json: Optional[str] = None
    artifact_path: Optional[str] = None
    error: Optional[str] = None


# ─── Health Check ──────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "healthy"
    version: str = "0.1.0"
