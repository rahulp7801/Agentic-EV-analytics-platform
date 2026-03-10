"""Schema tests (DATA-01, DATA-03).

Tests verify that all required composite indexes exist on play_by_play,
that the query planner uses an Index Scan (not Seq Scan) when seqscan is
disabled, and that odds_snapshots accepts writes and returns snapped_at.

All tests use the pg_engine fixture which skips if DB is not reachable.
"""

from __future__ import annotations

import sqlalchemy as sa


def test_pbp_indexes(pg_engine: sa.Engine) -> None:
    """play_by_play must have all 6 required composite indexes (DATA-01).

    Queries pg_indexes system catalog directly so the test is immune to
    SQLAlchemy inspection quirks.
    """
    with pg_engine.connect() as conn:
        result = conn.execute(
            sa.text("SELECT indexname FROM pg_indexes WHERE tablename = 'play_by_play'")
        )
        index_names = {row[0] for row in result}

    required = {
        "idx_pbp_season_week",
        "idx_pbp_posteam_season",
        "idx_pbp_defteam_season",
        "idx_pbp_play_type_season",
        "idx_pbp_passer_season",
        "idx_pbp_receiver_season",
    }
    assert required.issubset(index_names), (
        f"Missing indexes on play_by_play: {required - index_names}"
    )


def test_explain_no_seq_scan(pg_engine: sa.Engine) -> None:
    """EXPLAIN on season/posteam/play_type filter must not use Seq Scan (DATA-01).

    Uses SET enable_seqscan = off so the planner is forced to prefer index
    scans regardless of table row count. This is reliable at any data volume —
    including an empty table (avoids the single-row planner heuristic that
    would otherwise choose Seq Scan on small tables).
    """
    with pg_engine.connect() as conn:
        conn.execute(sa.text("SET enable_seqscan = off"))
        plan = conn.execute(
            sa.text(
                "EXPLAIN SELECT * FROM play_by_play "
                "WHERE season = 2023 AND posteam = 'KC' AND play_type = 'pass'"
            )
        ).fetchall()
    plan_text = " ".join(str(row) for row in plan)
    assert "Seq Scan" not in plan_text, (
        f"Unexpected Seq Scan with enable_seqscan=off: {plan_text[:200]}"
    )


def test_odds_snapshot_write_read(pg_engine: sa.Engine) -> None:
    """odds_snapshots must accept a row and return it with auto-populated snapped_at (DATA-03)."""
    with pg_engine.begin() as conn:
        # Insert parent row to satisfy FK (ON CONFLICT DO NOTHING handles reruns)
        conn.execute(
            sa.text(
                "INSERT INTO games (game_id, season, week, home_team, away_team, game_date) "
                "VALUES ('2023_01_KC_DET', 2023, 1, 'KC', 'DET', '2023-09-10') "
                "ON CONFLICT DO NOTHING"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO odds_snapshots (game_id, sportsbook, market_type, line, price) "
                "VALUES ('2023_01_KC_DET', 'DraftKings', 'moneyline', NULL, -150)"
            )
        )
        row = conn.execute(
            sa.text(
                "SELECT game_id, sportsbook, market_type, price, snapped_at "
                "FROM odds_snapshots "
                "WHERE game_id = '2023_01_KC_DET' "
                "ORDER BY snapped_at DESC LIMIT 1"
            )
        ).fetchone()

    assert row is not None, "No row returned from odds_snapshots after insert"
    assert row[0] == "2023_01_KC_DET", f"game_id mismatch: {row[0]}"
    assert row[1] == "DraftKings", f"sportsbook mismatch: {row[1]}"
    assert row[2] == "moneyline", f"market_type mismatch: {row[2]}"
    assert row[3] == -150, f"price mismatch: {row[3]}"
    assert row[4] is not None, "snapped_at is None — server_default not applied"
