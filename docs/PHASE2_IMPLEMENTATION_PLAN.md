# Phase 2 Implementation Plan: FastAPI + SQLite + Frontend

**Goal:** Add web interface to the City Growth AI Agent with embedded Plotly visualizations in chat.

**Status:** Planning Complete

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              FRONTEND (React + Vite)                            │
│  ┌──────────────┐  ┌──────────────────────────────────────────────────────────┐ │
│  │   Sidebar    │  │                    Chat Area                              │ │
│  │              │  │  ┌──────────────────────────────────────────────────┐    │ │
│  │ - Conv List  │  │  │ User: Show wage trends in Austin                 │    │ │
│  │ - New Chat   │  │  ├──────────────────────────────────────────────────┤    │ │
│  │ - Dates      │  │  │ Assistant: Here's the analysis...               │    │ │
│  │              │  │  │ ┌────────────────────────────────────┐           │    │ │
│  │              │  │  │ │  [Plotly Chart Rendered Inline]    │           │    │ │
│  │              │  │  │ └────────────────────────────────────┘           │    │ │
│  └──────────────┘  │  └──────────────────────────────────────────────────┘    │ │
│                    │  ┌──────────────────────────────────────────────────┐    │ │
│                    │  │ [Message Input]                        [Send]    │    │ │
│                    │  └──────────────────────────────────────────────────┘    │ │
│                    └──────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────────────────┬─┘
                                                                                │
                                    WebSocket / REST                            │
                                                                                ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                            FASTAPI BACKEND                                      │
│  ┌─────────────┐  ┌─────────────────────────────────────────────────────────┐  │
│  │  chat.py    │  │                    service.py                           │  │
│  │             │  │  - stream_chat()       - save_message()                 │  │
│  │ /ws         │──│  - send_message()      - get_conversations()           │  │
│  │ /message    │  │  - get_conversation()  - delete_conversation()          │  │
│  │ /convs      │  └─────────────────────────────────────────────────────────┘  │
│  └─────────────┘                            │                                   │
│                                             ▼                                   │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │                         EXISTING AGENT STACK                              │  │
│  │  conversation.chat() → agent.ainvoke() → tools → visualization_agent     │  │
│  └──────────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────┘
                                             │
                                             ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              DATA LAYER                                         │
│  ┌──────────────────────────┐  ┌────────────────────────────────────────────┐  │
│  │   SQLite (App State)     │  │  PostgreSQL (LangGraph + QCEW Data)        │  │
│  │  - conversations         │  │  - langgraph.checkpoints (thread state)    │  │
│  │  - messages              │  │  - msa_wages_employment_data (QCEW)        │  │
│  │  - artifact_json         │  └────────────────────────────────────────────┘  │
│  └──────────────────────────┘                                                   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## File Structure (New Files)

```
City-Growth-AI-Agent/
├── api/
│   ├── __init__.py            # Package marker
│   ├── app.py                 # FastAPI app, CORS, lifespan
│   ├── chat.py                # WebSocket + REST endpoints
│   ├── service.py             # Business logic + SQLite ops
│   └── models.py              # Pydantic request/response schemas
├── frontend/
│   ├── src/
│   │   ├── App.jsx            # Main app component
│   │   ├── Chat.jsx           # Chat interface
│   │   ├── Sidebar.jsx        # Conversation history
│   │   ├── Message.jsx        # Message renderer (with Plotly)
│   │   ├── api.js             # WebSocket + REST client
│   │   └── main.jsx           # Entry point
│   ├── public/
│   │   └── index.html
│   ├── package.json
│   └── vite.config.js
├── database/
│   └── app.db                 # SQLite database (gitignored)
└── src/
    └── checkpointer.py        # PostgresSaver factory (NEW)
```

**Files to Modify:**
- `src/agent.py` - Accept checkpointer parameter
- `src/conversation.py` - Return artifact_json in response
- `src/prompts.py` - Add `fig.to_json()` requirement
- `src/tools/workflow_tool.py` - Extract and return Plotly JSON
- `src/validator.py` - Allow JSON output alongside HTML
- `pyproject.toml` - Add FastAPI dependencies

---

## Database Schema

### SQLite (Application State)

```sql
-- database/init_app_db.sql

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,              -- UUID, matches thread_id
    title TEXT NOT NULL,              -- Auto-generated from first message
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    message_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,               -- 'user' or 'assistant'
    content TEXT NOT NULL,            -- Message text
    artifact_json TEXT,               -- Plotly JSON spec (if visualization)
    artifact_path TEXT,               -- Path to HTML file (if visualization)
    tool_calls TEXT,                  -- JSON array of tool calls
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at DESC);
```

### PostgreSQL (LangGraph Checkpoints)

LangGraph's `PostgresSaver` will create its own tables in the `langgraph` schema automatically:
- `langgraph.checkpoints`
- `langgraph.checkpoint_writes`
- `langgraph.checkpoint_blobs`

---

## API Endpoints

### WebSocket: `/api/chat/ws`

**Client → Server:**
```json
{"type": "message", "content": "What is Austin's wage?", "thread_id": null}
{"type": "message", "content": "Compare to Dallas", "thread_id": "abc123"}
{"type": "ping"}
```

**Server → Client:**
```json
{"type": "conversation_created", "thread_id": "abc123"}
{"type": "token", "content": "Austin"}
{"type": "token", "content": "'s average"}
{"type": "complete", "thread_id": "abc123", "content": "...", "artifact_json": "..."}
{"type": "error", "message": "Something went wrong"}
{"type": "pong"}
```

### REST Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/chat/message` | Send message (non-streaming) |
| GET | `/api/chat/conversations` | List all conversations |
| GET | `/api/chat/conversations/{id}` | Get conversation with messages |
| DELETE | `/api/chat/conversations/{id}` | Delete conversation |
| GET | `/api/health` | Health check |

### Request/Response Models

```python
# ChatRequest
class ChatRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None

# ChatResponse
class ChatResponse(BaseModel):
    response: str
    thread_id: str
    artifact_json: Optional[str] = None
    artifact_path: Optional[str] = None

# ConversationSummary
class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int

# MessageDetail
class MessageDetail(BaseModel):
    id: int
    role: str  # "user" or "assistant"
    content: str
    artifact_json: Optional[str] = None
    artifact_path: Optional[str] = None
    created_at: datetime
```

---

## Plotly Embedding Strategy

### The Challenge
Current system saves Plotly charts as HTML files (`fig.write_html()`). Users must open separate files to view visualizations.

### The Solution: Plotly JSON + plotly.js

1. **Modify Code Generation** (`src/prompts.py`)
   - Require generated code to output BOTH HTML and JSON:
   ```python
   fig.write_html('{output_path}')
   with open('{output_path}'.replace('.html', '.json'), 'w') as f:
       f.write(fig.to_json())
   ```

2. **Extract JSON** (`src/tools/workflow_tool.py`)
   - Read the JSON file from workspace
   - Include in tool response as `ARTIFACT_METADATA: {...}`

3. **Pass Through Stack** (`src/conversation.py`)
   - Parse artifact metadata from tool responses
   - Return `artifact_json` field in chat response

4. **Store in Database** (`api/service.py`)
   - Save artifact_json in messages table
   - Keep artifact_path for debugging/fallback

5. **Render in Frontend** (`frontend/src/Message.jsx`)
   ```jsx
   import Plotly from 'plotly.js-dist';

   function Message({ message }) {
     const chartRef = useRef(null);

     useEffect(() => {
       if (message.artifact_json && chartRef.current) {
         const data = JSON.parse(message.artifact_json);
         Plotly.newPlot(chartRef.current, data.data, data.layout);
       }
     }, [message.artifact_json]);

     return (
       <div className="message">
         <div className="content">{message.content}</div>
         {message.artifact_json && (
           <div ref={chartRef} className="chart-container" />
         )}
       </div>
     );
   }
   ```

---

## Implementation Phases

### Phase 1: Backend Foundation (2-3 hours)

**Goal**: FastAPI app starts, SQLite initialized, PostgresSaver works

**Tasks:**
- [ ] Create `api/__init__.py`
- [ ] Create `api/app.py` with FastAPI setup, CORS, lifespan events
- [ ] Create `api/models.py` with Pydantic schemas
- [ ] Create `database/init_app_db.sql`
- [ ] Create `src/checkpointer.py` with PostgresSaver factory
- [ ] Modify `src/agent.py` to accept checkpointer parameter
- [ ] Update `pyproject.toml` with dependencies

**Dependencies to Add:**
```toml
"fastapi>=0.115.0",
"uvicorn[standard]>=0.32.0",
"websockets>=13.0",
"aiosqlite>=0.20.0",
"langgraph-checkpoint-postgres>=2.0.0",
```

**Verification:**
```bash
uv run uvicorn api.app:app --reload --port 8000
curl http://localhost:8000/api/health
```

### Phase 2: Service Layer + REST API (2-3 hours)

**Goal**: Chat works via REST endpoint

**Tasks:**
- [ ] Create `api/service.py` with ChatService class:
  - `send_message(message, thread_id)` - calls conversation.chat()
  - `_save_conversation()` - SQLite insert
  - `_save_message()` - SQLite insert
  - `_update_conversation()` - Update timestamp, message count
  - `get_conversations()` - List with pagination
  - `get_conversation_detail()` - Single conversation with messages
  - `delete_conversation()` - Cascade delete
- [ ] Create `api/chat.py` with REST endpoints
- [ ] Wire up router in `api/app.py`

**Verification:**
```bash
curl -X POST http://localhost:8000/api/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the average wage in Austin?"}'
```

### Phase 3: Visualization Integration (2-3 hours)

**Goal**: Plotly JSON extracted and returned

**Tasks:**
- [ ] Modify `src/prompts.py` - Add `fig.to_json()` requirement
- [ ] Modify `src/validator.py` - Allow JSON output (add to REQUIRED_PATTERNS)
- [ ] Modify `src/tools/workflow_tool.py`:
  - Read JSON file from workspace
  - Include in response as `ARTIFACT_METADATA: {...}`
- [ ] Modify `src/conversation.py`:
  - Parse ARTIFACT_METADATA from tool responses
  - Return artifact_json in response dict
- [ ] Update `api/service.py`:
  - Store artifact_json in messages table

**Verification:**
```bash
curl -X POST http://localhost:8000/api/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message": "Show wage trends in Austin"}'
# Response should include "artifact_json" field
```

### Phase 4: WebSocket Streaming (2 hours)

**Goal**: Real-time streaming responses

**Tasks:**
- [ ] Add `stream_chat()` method to ChatService
- [ ] Implement WebSocket endpoint in `api/chat.py`
- [ ] Handle connection lifecycle (accept, loop, disconnect)
- [ ] Implement ping/pong for keepalive

**Verification:**
```python
# Test with Python websockets client
import asyncio
import websockets
import json

async def test():
    async with websockets.connect("ws://localhost:8000/api/chat/ws") as ws:
        await ws.send(json.dumps({"type": "message", "content": "Hello"}))
        while True:
            response = await ws.recv()
            print(response)
            if "complete" in response:
                break

asyncio.run(test())
```

### Phase 5: Frontend Foundation (3-4 hours)

**Goal**: Basic React UI with chat

**Tasks:**
- [ ] Initialize Vite + React project in `frontend/`
- [ ] Create `frontend/src/api.js`:
  - WebSocket client with reconnection
  - REST helpers for conversations
- [ ] Create `frontend/src/Chat.jsx`:
  - Message input
  - Message display area
  - Send button with loading state
- [ ] Create `frontend/src/App.jsx`:
  - Main layout container
  - State management for current conversation
- [ ] Add basic CSS styling
- [ ] Configure Vite proxy to backend

**Verification:**
```bash
cd frontend && npm run dev
# Open http://localhost:5173
# Send a message, see response
```

### Phase 6: Plotly Rendering (2 hours)

**Goal**: Charts render inline in chat

**Tasks:**
- [ ] Add plotly.js-dist to frontend dependencies
- [ ] Create `frontend/src/Message.jsx`:
  - Render text content
  - Detect artifact_json presence
  - Create chart container div
  - Call Plotly.newPlot() with parsed JSON
- [ ] Add responsive chart CSS
- [ ] Handle chart resize on window change

**Verification:**
- Ask "Show Austin wage trends"
- Chart should appear inline
- Chart should be interactive (hover, zoom)

### Phase 7: Conversation History (2-3 hours)

**Goal**: Sidebar with conversation list

**Tasks:**
- [ ] Create `frontend/src/Sidebar.jsx`:
  - Fetch conversations on mount
  - Display list with title + date
  - Click to load conversation
  - "New Chat" button
- [ ] Update `App.jsx` to manage sidebar state
- [ ] Implement conversation switching
- [ ] Auto-title: Use first ~50 chars of first message
- [ ] Add delete conversation button

**Verification:**
- Create multiple conversations
- Switch between them
- Refresh page, history persists
- Delete conversation, removed from list

### Phase 8: Polish + Documentation (2 hours)

**Goal**: Production-ready, documented

**Tasks:**
- [ ] Add error handling to all endpoints
- [ ] Add reconnection logic to WebSocket client
- [ ] Create startup script: `scripts/start_server.sh`
- [ ] Update README with new usage instructions
- [ ] Add entries to `.gitignore`:
  ```
  database/app.db
  frontend/node_modules/
  frontend/dist/
  ```
- [ ] Test full end-to-end workflow

---

## Key Decisions Summary

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Plotly Embedding | JSON + plotly.js | Enables inline rendering, interactive charts |
| Chat DB | SQLite | Simple, local, no extra infrastructure |
| Thread State DB | PostgresSaver | LangGraph native, uses existing PG |
| Frontend | React + Vite | Fast dev, minimal config |
| Streaming | WebSocket | Real-time token streaming |
| Auth | None (MVP) | Local use only, add later |

---

## Success Criteria

1. **Chat Works**: Can send messages via web UI and get responses
2. **Visualizations Embedded**: Plotly charts render inline in chat messages
3. **History Persists**: Conversations saved across sessions
4. **Streaming Works**: Tokens appear in real-time during response
5. **Backward Compatible**: CLI still works, existing tests pass

---

## Estimated Timeline

| Phase | Time | Dependencies |
|-------|------|--------------|
| 1. Backend Foundation | 2-3 hours | None |
| 2. Service + REST | 2-3 hours | Phase 1 |
| 3. Visualization Integration | 2-3 hours | Phase 2 |
| 4. WebSocket Streaming | 2 hours | Phase 2 |
| 5. Frontend Foundation | 3-4 hours | Phase 2 |
| 6. Plotly Rendering | 2 hours | Phase 3, 5 |
| 7. Conversation History | 2-3 hours | Phase 5 |
| 8. Polish | 2 hours | All above |

**Total: 17-22 hours** (2-3 working days)

---

## Notes

- No auth for MVP - add JWT when deploying to server
- Keep existing CLI working throughout
- PostgresSaver requires `langgraph-checkpoint-postgres` package
- Frontend uses Vite for fast HMR during development
- Plotly.js CDN version is ~3MB, consider lazy loading
