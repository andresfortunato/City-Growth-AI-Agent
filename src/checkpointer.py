"""
checkpointer.py - Checkpointer factories for LangGraph agent persistence

Provides both InMemorySaver (for CLI/testing) and PostgresSaver (for API).
"""

import os
from typing import Optional

from dotenv import load_dotenv
from langgraph.checkpoint.memory import InMemorySaver

load_dotenv()

# Singleton instances
_memory_saver: Optional[InMemorySaver] = None
_postgres_saver = None


def get_memory_checkpointer() -> InMemorySaver:
    """Get in-memory checkpointer (for CLI and testing).

    Thread state is lost when process exits.
    """
    global _memory_saver
    if _memory_saver is None:
        _memory_saver = InMemorySaver()
    return _memory_saver


def get_postgres_checkpointer():
    """Get PostgreSQL checkpointer (for API with persistence).

    Stores thread state in PostgreSQL for cross-session persistence.
    Uses the existing database configured in .env.

    Requires: pip install langgraph-checkpoint-postgres psycopg[binary,pool]
    """
    global _postgres_saver

    if _postgres_saver is not None:
        return _postgres_saver

    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg_pool import ConnectionPool
    except ImportError as e:
        raise ImportError(
            "PostgresSaver requires additional dependencies. Install with:\n"
            "uv add langgraph-checkpoint-postgres 'psycopg[binary,pool]'"
        ) from e

    # Build connection string from environment
    DB_USER = os.getenv("DB_USER", "city_growth_postgres")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = os.getenv("DB_PORT", "5432")
    DB_NAME = os.getenv("DB_NAME", "postgres")

    db_uri = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

    # Create connection pool
    pool = ConnectionPool(conninfo=db_uri, min_size=1, max_size=10)

    # Create PostgresSaver
    _postgres_saver = PostgresSaver(pool)

    # Create tables if they don't exist
    _postgres_saver.setup()

    print(f"PostgresSaver initialized with {DB_HOST}:{DB_PORT}/{DB_NAME}")
    return _postgres_saver


def close_postgres_checkpointer():
    """Clean shutdown of PostgreSQL connection pool."""
    global _postgres_saver
    if _postgres_saver is not None:
        try:
            _postgres_saver.pool.close()
        except Exception:
            pass
        _postgres_saver = None


def reset_checkpointers():
    """Reset all checkpointers (for testing)."""
    global _memory_saver, _postgres_saver
    close_postgres_checkpointer()
    _memory_saver = None
