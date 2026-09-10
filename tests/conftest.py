"""Shared pytest fixtures for the Quant-Sports test suite.

Fixtures:
- alembic_cfg: Alembic Config object for migration tests
- pg_engine: SQLAlchemy sync engine (skips if DB not reachable)
- graph_fixture: compiled graph with MemorySaver + fresh thread_id per test

Tests requiring a live DB use SPORTSBET_TEST_DATABASE_URL env var.
If not set, they are skipped automatically (no hard CI failure without DB).
"""

from __future__ import annotations

import os
import uuid

import pytest
import sqlalchemy
from alembic.config import Config
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.engine import Engine

from sportsbet.config import settings
from sportsbet.graph import create_graph


@pytest.fixture(scope="session")
def alembic_cfg() -> Config:
    """Alembic Config pointed at alembic.ini.

    Used by migration tests (Plan 02). The URL is set dynamically in env.py
    from sportsbet.config.settings.
    """
    return Config("alembic.ini")


@pytest.fixture
def pg_engine() -> Engine:  # type: ignore[return]
    """Synchronous SQLAlchemy engine for the test database.

    Requires an explicit disposable SPORTSBET_TEST_DATABASE_URL.
    Skips automatically if PostgreSQL is not reachable.
    """
    url = os.environ.get("SPORTSBET_TEST_DATABASE_URL")
    if not url:
        pytest.skip("SPORTSBET_TEST_DATABASE_URL not set")
    try:
        # connect_args timeout ensures fast skip when PostgreSQL is not running.
        engine = sqlalchemy.create_engine(
            url,
            connect_args={"connect_timeout": 3},
        )
        # Lightweight connectivity check — fails fast if DB is unavailable.
        with engine.connect():
            pass
        return engine
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Test PostgreSQL unavailable ({type(exc).__name__})")


@pytest.fixture
def graph_fixture():
    """Compiled graph with MemorySaver + fresh thread_id per test. No disk I/O.

    Returns a (compiled_graph, config) tuple where config carries a unique
    thread_id. Each test invocation gets an independent MemorySaver instance
    so there is no shared checkpoint state between tests.
    """
    saver = MemorySaver()
    compiled = create_graph(checkpointer=saver)
    thread_id = str(uuid.uuid4())
    return compiled, {"configurable": {"thread_id": thread_id}}
