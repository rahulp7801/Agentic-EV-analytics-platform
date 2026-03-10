"""Migration tests (DATA-04).

Tests verify that alembic upgrade head creates all 5 tables and that
alembic downgrade base removes them cleanly.

Marked @pytest.mark.serial to prevent concurrent DB state corruption.
Skipped automatically when SPORTSBET_TEST_DATABASE_URL is not set.
"""

from __future__ import annotations

import os

import pytest
import sqlalchemy as sa
import alembic.command
import alembic.config


def get_alembic_cfg(url: str) -> alembic.config.Config:
    """Build an Alembic Config with the given DB URL."""
    cfg = alembic.config.Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.mark.serial
@pytest.mark.skipif(
    not os.environ.get("SPORTSBET_TEST_DATABASE_URL"),
    reason="SPORTSBET_TEST_DATABASE_URL not set",
)
def test_alembic_upgrade_clean() -> None:
    """alembic upgrade head must run cleanly on a fresh PostgreSQL instance.

    Asserts all 5 tables exist after upgrade. Runs downgrade as cleanup.
    """
    url = os.environ["SPORTSBET_TEST_DATABASE_URL"]
    cfg = get_alembic_cfg(url)
    alembic.command.upgrade(cfg, "head")
    engine = sa.create_engine(url)
    with engine.connect():
        tables = sa.inspect(engine).get_table_names()
    assert "games" in tables, "games table missing after upgrade head"
    assert "play_by_play" in tables, "play_by_play table missing after upgrade head"
    assert "player_stats" in tables, "player_stats table missing after upgrade head"
    assert "ngs_stats" in tables, "ngs_stats table missing after upgrade head"
    assert "odds_snapshots" in tables, "odds_snapshots table missing after upgrade head"
    # Cleanup — leave DB clean for next test run
    alembic.command.downgrade(cfg, "base")


@pytest.mark.serial
@pytest.mark.skipif(
    not os.environ.get("SPORTSBET_TEST_DATABASE_URL"),
    reason="SPORTSBET_TEST_DATABASE_URL not set",
)
def test_alembic_downgrade_clean() -> None:
    """alembic downgrade base must cleanly remove all tables.

    Runs upgrade first, then downgrade, then asserts tables are gone.
    """
    url = os.environ["SPORTSBET_TEST_DATABASE_URL"]
    cfg = get_alembic_cfg(url)
    alembic.command.upgrade(cfg, "head")
    alembic.command.downgrade(cfg, "base")
    engine = sa.create_engine(url)
    tables = sa.inspect(engine).get_table_names()
    assert "games" not in tables, "games table still present after downgrade base"
    assert "play_by_play" not in tables, "play_by_play still present after downgrade base"
    assert "player_stats" not in tables, "player_stats still present after downgrade base"
    assert "ngs_stats" not in tables, "ngs_stats still present after downgrade base"
    assert "odds_snapshots" not in tables, "odds_snapshots still present after downgrade base"
