-- init_app_db.sql - SQLite schema for City Growth AI chat persistence
-- This stores conversation metadata and messages for the UI.
-- LangGraph thread state is stored separately in PostgreSQL via PostgresSaver.

-- Conversations table (UI metadata)
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,              -- UUID, matches LangGraph thread_id
    title TEXT NOT NULL,              -- Auto-generated from first message
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    message_count INTEGER DEFAULT 0
);

-- Messages table (for display, searchable history)
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    artifact_json TEXT,               -- Plotly JSON spec (if visualization)
    artifact_path TEXT,               -- Path to HTML file (if visualization)
    tool_calls TEXT,                  -- JSON array of tool calls made
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at DESC);

-- Trigger to update conversation timestamp and message count
CREATE TRIGGER IF NOT EXISTS update_conversation_on_message
AFTER INSERT ON messages
BEGIN
    UPDATE conversations
    SET updated_at = CURRENT_TIMESTAMP,
        message_count = message_count + 1
    WHERE id = NEW.conversation_id;
END;
