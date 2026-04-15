"""
db.py - Centralized database connection pool

All database access should go through get_engine() to share a single
connection pool instead of creating fresh engines per-query.
"""

import os
from sqlalchemy import create_engine, pool
from dotenv import load_dotenv

load_dotenv()

_engine = None


def get_engine():
    """Get or create the shared SQLAlchemy engine with connection pooling."""
    global _engine
    if _engine is None:
        DB_USER = os.getenv("DB_USER")
        DB_PASSWORD = os.getenv("DB_PASSWORD")
        DB_HOST = os.getenv("DB_HOST", "localhost")
        DB_PORT = os.getenv("DB_PORT", "5432")
        DB_NAME = os.getenv("DB_NAME", "postgres")

        db_uri = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

        _engine = create_engine(
            db_uri,
            poolclass=pool.QueuePool,
            pool_size=5,
            max_overflow=10,
            pool_timeout=30,
            pool_recycle=3600,
            pool_pre_ping=True,
        )
    return _engine
