"""Shared pytest fixtures for the Quant-Sports test suite.

Fixtures:
- alembic_cfg: Alembic Config object for migration tests
- pg_engine: SQLAlchemy sync engine (skips if DB not reachable)

Tests requiring a live DB use SPORTSBET_TEST_DATABASE_URL env var.
If not set, they are skipped automatically (no hard CI failure without DB).
"""

from __future__ import annotations

import os

import pytest
import sqlalchemy
from alembic.config import Config
from sqlalchemy.engine import Engine

from sportsbet.config import settings


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

    Uses SPORTSBET_TEST_DATABASE_URL if set; falls back to settings.database_url.
    Skips automatically if PostgreSQL is not reachable.
    """
    url = os.environ.get("SPORTSBET_TEST_DATABASE_URL", settings.database_url)
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
        pytest.skip(f"PostgreSQL not reachable: {exc}")
