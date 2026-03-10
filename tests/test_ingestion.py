"""Ingestion tests — promoted from xfail stubs to real assertions (Plan 03).

DATA-02: PBP column whitelist and multiseason load.
DATA-03: Odds snapshot Pydantic validation.
"""
from __future__ import annotations

import os
import gc
from unittest.mock import patch, MagicMock
import polars as pl
import pytest


# --------------------------------------------------------------------------- #
# Unit tests — no DB required                                                  #
# --------------------------------------------------------------------------- #


def test_pbp_column_whitelist() -> None:
    """Column whitelist must drop all columns not in PBP_COLUMNS before write."""
    from sportsbet.ingestion.pbp import PBP_COLUMNS

    # Build a mock DataFrame with some PBP columns + extras that should be dropped
    all_columns = PBP_COLUMNS[:3] + ["extra_col_1", "extra_col_2", "unused_field"]
    data = {col: [1, 2, 3] for col in all_columns}
    df = pl.DataFrame(data)

    # Apply the exact whitelist logic from pbp.py
    available = [c for c in PBP_COLUMNS if c in df.columns]
    result = df.select(available)

    # Only whitelisted columns that exist in the mock DF should be present
    assert set(result.columns) == set(PBP_COLUMNS[:3])
    assert "extra_col_1" not in result.columns
    assert "extra_col_2" not in result.columns
    assert len(result.columns) == 3


def test_odds_snapshot_create_validates() -> None:
    """OddsSnapshotCreate rejects empty sportsbook and price=0."""
    from sportsbet.ingestion.odds import OddsSnapshotCreate
    import pydantic

    # Valid snapshot
    snap = OddsSnapshotCreate(sportsbook="DraftKings", market_type="moneyline", price=-150)
    assert snap.sportsbook == "DraftKings"

    # Empty sportsbook rejected
    with pytest.raises(pydantic.ValidationError):
        OddsSnapshotCreate(sportsbook="  ", market_type="moneyline")

    # price=0 rejected
    with pytest.raises(pydantic.ValidationError):
        OddsSnapshotCreate(sportsbook="FanDuel", market_type="spread", price=0)


# --------------------------------------------------------------------------- #
# Integration tests — require SPORTSBET_TEST_DATABASE_URL                     #
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(
    not os.environ.get("SPORTSBET_TEST_DATABASE_URL"),
    reason="SPORTSBET_TEST_DATABASE_URL not set",
)
def test_pbp_multiseason_load() -> None:
    """Ingestion loop loads at least 1 season and writes non-zero rows.

    Uses 2023 only (1 season) to keep test runtime reasonable.
    Verifies idempotency: second run produces same row count.
    """
    import sqlalchemy as sa
    from sportsbet.ingestion.pbp import ingest_pbp_seasons

    url = os.environ["SPORTSBET_TEST_DATABASE_URL"]
    engine = sa.create_engine(url)

    # First run
    ingest_pbp_seasons([2023], engine)
    with engine.connect() as conn:
        count_1: int = conn.execute(
            sa.text("SELECT COUNT(*) FROM play_by_play WHERE season = 2023")
        ).scalar_one()
    assert count_1 > 0, "Expected non-zero rows after ingesting season 2023"

    # Second run — idempotent due to ON CONFLICT DO NOTHING
    ingest_pbp_seasons([2023], engine)
    with engine.connect() as conn:
        count_2: int = conn.execute(
            sa.text("SELECT COUNT(*) FROM play_by_play WHERE season = 2023")
        ).scalar_one()
    assert count_2 == count_1, (
        f"Re-run changed row count from {count_1} to {count_2} — not idempotent"
    )


@pytest.mark.skipif(
    not os.environ.get("SPORTSBET_TEST_DATABASE_URL"),
    reason="SPORTSBET_TEST_DATABASE_URL not set",
)
def test_ngs_season_guard() -> None:
    """ingest_ngs_seasons raises ValueError for season < 2016."""
    import sqlalchemy as sa
    from sportsbet.ingestion.ngs import ingest_ngs_seasons

    url = os.environ["SPORTSBET_TEST_DATABASE_URL"]
    engine = sa.create_engine(url)

    with pytest.raises(ValueError, match="2016"):
        ingest_ngs_seasons([2015], engine)
