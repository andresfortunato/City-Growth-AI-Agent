"""
app.py - FastAPI application setup for City Growth AI Agent

Run with: uv run uvicorn api.app:app --reload --port 8000
"""

import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.models import HealthResponse

# Database path
DATABASE_DIR = Path(__file__).parent.parent / "database"
DATABASE_PATH = DATABASE_DIR / "app.db"
SCHEMA_PATH = DATABASE_DIR / "init_app_db.sql"


def init_database():
    """Initialize SQLite database with schema."""
    DATABASE_DIR.mkdir(exist_ok=True)

    conn = sqlite3.connect(DATABASE_PATH)

    # Read and execute schema
    if SCHEMA_PATH.exists():
        with open(SCHEMA_PATH) as f:
            conn.executescript(f.read())

    conn.commit()
    conn.close()
    print(f"Database initialized at {DATABASE_PATH}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown events."""
    # Startup
    print("Starting City Growth AI API...")
    init_database()

    yield

    # Shutdown
    print("Shutting down City Growth AI API...")


# Create FastAPI app
app = FastAPI(
    title="City Growth AI Agent",
    description="Conversational agent for urban economics analysis with QCEW data",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite dev server
        "http://localhost:5174",  # Alternate Vite port
        "http://localhost:3000",  # Alternative dev port
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Health Check ──────────────────────────────────────────────────────────────

@app.get("/api/health", response_model=HealthResponse, tags=["system"])
async def health_check():
    """Check if the API is running."""
    return HealthResponse(status="healthy", version="0.1.0")


# ─── Import and mount routers ──────────────────────────────────────────────────
from api.chat import router as chat_router
app.include_router(chat_router)
