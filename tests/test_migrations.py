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

    Asserts all 7 tables exist after upgrade (5 original + 2 Phase 10 prop/NBA).
    Runs downgrade as cleanup.
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
    assert "player_prop_snapshots" in tables, "player_prop_snapshots table missing after upgrade head"
    assert "nba_player_stats" in tables, "nba_player_stats table missing after upgrade head"
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
    assert "player_prop_snapshots" not in tables, "player_prop_snapshots still present after downgrade base"
    assert "nba_player_stats" not in tables, "nba_player_stats still present after downgrade base"


@pytest.mark.serial
@pytest.mark.skipif(
    not os.environ.get("SPORTSBET_TEST_DATABASE_URL"),
    reason="SPORTSBET_TEST_DATABASE_URL not set",
)
def test_prop_table_indexes_exist() -> None:
    """Three composite indexes on player_prop_snapshots must exist after upgrade head.

    Uses pg_indexes system catalog to verify index names, which are only present
    after alembic upgrade head succeeds on a live PostgreSQL instance.
    """
    url = os.environ["SPORTSBET_TEST_DATABASE_URL"]
    cfg = get_alembic_cfg(url)
    alembic.command.upgrade(cfg, "head")
    engine = sa.create_engine(url)
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'player_prop_snapshots'"
            )
        ).fetchall()
        index_names = {row[0] for row in rows}

    assert "idx_props_player_prop_snapped" in index_names, (
        "idx_props_player_prop_snapped missing from player_prop_snapshots"
    )
    assert "idx_props_sport_snapped" in index_names, (
        "idx_props_sport_snapped missing from player_prop_snapshots"
    )
    assert "idx_props_game_prop" in index_names, (
        "idx_props_game_prop missing from player_prop_snapshots"
    )
    # Cleanup
    alembic.command.downgrade(cfg, "base")


@pytest.mark.serial
@pytest.mark.skipif(
    not os.environ.get("SPORTSBET_TEST_DATABASE_URL"),
    reason="SPORTSBET_TEST_DATABASE_URL not set",
)
def test_new_prop_quote_constraint_preserves_legacy_rows_and_rejects_bad_inserts() -> None:
    """The unvalidated constraint protects new rows without rewriting legacy evidence."""
    url = os.environ["SPORTSBET_TEST_DATABASE_URL"]
    cfg = get_alembic_cfg(url)
    alembic.command.upgrade(cfg, "0013_nba_stat_provenance")
    engine = sa.create_engine(url)
    with engine.begin() as conn:
        conn.execute(sa.text("""
            INSERT INTO player_prop_snapshots
                (sport, player_name, sportsbook, prop_type, implied_probability)
            VALUES ('nba', 'Legacy Player', 'legacy', 'player_points', 0.5)
        """))
    alembic.command.upgrade(cfg, "head")
    with engine.begin() as conn:
        validated = conn.execute(sa.text("""
            SELECT convalidated FROM pg_constraint
            WHERE conname = 'ck_player_prop_snapshots_complete_quote'
        """)).scalar_one()
        assert validated is False
        assert conn.execute(sa.text(
            "SELECT COUNT(*) FROM player_prop_snapshots WHERE sportsbook='legacy'"
        )).scalar_one() == 1
        conn.execute(sa.text("""
            INSERT INTO player_prop_snapshots
                (sport, game_id, player_name, sportsbook, prop_type, line, price,
                 implied_probability, side, snapped_at, game_start_time)
            VALUES ('nfl', 'event', 'Player', 'book', 'player_pass_yds', 249.5,
                    -110, 0.523809, 'Over', '2026-09-12T00:00:00Z',
                    '2026-09-13T00:00:00Z')
        """))
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as conn:
            conn.execute(sa.text("""
                INSERT INTO player_prop_snapshots
                    (sport, player_name, sportsbook, prop_type, implied_probability)
                VALUES ('nba', 'New Invalid Player', 'book', 'player_points', 0.5)
            """))
    alembic.command.downgrade(cfg, "0013_nba_stat_provenance")
    with engine.connect() as conn:
        assert conn.execute(sa.text("""
            SELECT COUNT(*) FROM pg_constraint
            WHERE conname = 'ck_player_prop_snapshots_complete_quote'
        """)).scalar_one() == 0
    engine.dispose()
    alembic.command.downgrade(cfg, "base")


@pytest.mark.serial
@pytest.mark.skipif(
    not os.environ.get("SPORTSBET_TEST_DATABASE_URL"),
    reason="SPORTSBET_TEST_DATABASE_URL not set",
)
def test_settlement_constraint_preserves_legacy_and_requires_new_provenance() -> None:
    """Old outcomes remain evidence; every future settlement identifies its source."""
    from sportsbet.ledger import Ledger

    url=os.environ['SPORTSBET_TEST_DATABASE_URL'];cfg=get_alembic_cfg(url)
    alembic.command.upgrade(cfg,'0014_prop_snapshot_integrity')
    engine=sa.create_engine(url)
    with engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO analytics.predictions(id,scan_id,payload,outcome) VALUES ('legacy','s','{}','true')"))
    alembic.command.upgrade(cfg,'head')
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT outcome FROM analytics.predictions WHERE id='legacy'")).scalar_one()=='true'
        assert conn.execute(sa.text("SELECT convalidated FROM pg_constraint WHERE conname='ck_prediction_settlement_evidence'")).scalar_one() is False
    with engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO analytics.predictions(id,scan_id,payload) VALUES ('new','s','{}')"))
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as conn:
            conn.execute(sa.text("UPDATE analytics.predictions SET outcome='true' WHERE id='new'"))
    Ledger(database_url=url).settle({'new':True})
    with engine.connect() as conn:
        row=conn.execute(sa.text("SELECT outcome,outcome_source,outcome_ref,outcome_observed_at FROM analytics.predictions WHERE id='new'")).one()
        assert tuple(row[:3])==('true','manual','caller_supplied') and row[3] is not None
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as conn:
            conn.execute(sa.text("UPDATE analytics.predictions SET actual_value=-1 WHERE id='new'"))
    engine.dispose();alembic.command.downgrade(cfg,'base')


@pytest.mark.serial
@pytest.mark.skipif(
    not os.environ.get("SPORTSBET_TEST_DATABASE_URL"),
    reason="SPORTSBET_TEST_DATABASE_URL not set",
)
def test_stat_source_constraints_preserve_legacy_and_require_new_evidence() -> None:
    url=os.environ['SPORTSBET_TEST_DATABASE_URL'];cfg=get_alembic_cfg(url)
    alembic.command.upgrade(cfg,'0015_settlement_provenance')
    engine=sa.create_engine(url)
    with engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO player_stats(player_id,season,week) VALUES ('legacy',2025,1)"))
        conn.execute(sa.text("INSERT INTO nba_player_gamelogs(player_id,game_id,season) VALUES (1,'legacy',2025)"))
    alembic.command.upgrade(cfg,'head')
    with engine.connect() as conn:
        for name in ('ck_player_stats_source_evidence','ck_nba_gamelog_source_evidence'):
            assert conn.execute(sa.text('SELECT convalidated FROM pg_constraint WHERE conname=:name'),
                {'name':name}).scalar_one() is False
        assert conn.execute(sa.text("SELECT count(*) FROM player_stats WHERE player_id='legacy'" )).scalar_one()==1
        assert conn.execute(sa.text("SELECT count(*) FROM nba_player_gamelogs WHERE game_id='legacy'" )).scalar_one()==1
    with engine.begin() as conn:
        conn.execute(sa.text("""INSERT INTO player_stats(player_id,season,week,source_provider,
            source_sha256,source_record_sha256,source_observed_at)
            VALUES ('valid',2025,1,'nflverse',:hash,:hash,NOW())"""),{'hash':'a'*64})
        conn.execute(sa.text("""INSERT INTO nba_player_gamelogs(player_id,game_id,season,source_provider,
            source_sha256,source_record_sha256,source_observed_at)
            VALUES (2,'valid',2025,'nba',:hash,:hash,NOW())"""),{'hash':'b'*64})
    for statement in (
        "INSERT INTO player_stats(player_id,season,week) VALUES ('invalid',2025,1)",
        "INSERT INTO nba_player_gamelogs(player_id,game_id,season) VALUES (3,'invalid',2025)",
    ):
        with pytest.raises(sa.exc.IntegrityError):
            with engine.begin() as conn:
                conn.execute(sa.text(statement))
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as conn:
            conn.execute(sa.text("UPDATE player_stats SET week=2 WHERE player_id='legacy'"))
    alembic.command.downgrade(cfg,'0015_settlement_provenance')
    columns={column['name'] for column in sa.inspect(engine).get_columns('player_stats')}
    assert not {'source_provider','source_sha256','source_record_sha256','source_observed_at'} & columns
    engine.dispose();alembic.command.downgrade(cfg,'base')
