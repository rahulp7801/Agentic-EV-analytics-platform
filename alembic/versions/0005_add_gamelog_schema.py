"""Add nba_player_gamelogs table and extend player_stats with opponent_team/home_away.

Revision ID: 0005_add_gamelog_schema
Revises: 0004_add_prop_and_nba_tables
Create Date: 2026-03-25

Hand-written migration -- autogenerate omits composite indexes (Phase 1 locked decision).

Phase 18 SC-1 changes:
  (a) Create nba_player_gamelogs table with per-game columns including is_home,
      opponent_team derived from MATCHUP at ingest time.
  (b) Add opponent_team (String(3)) and home_away (String(4)) nullable columns
      to player_stats so NFL conditional prop queries can filter without a JOIN.

Three indexes on nba_player_gamelogs support Phase 18 query patterns:
  - idx_nba_gamelog_player_season: player timeline range scans
  - idx_nba_gamelog_game_date: date+season window queries
  - idx_nba_gamelog_opponent: opponent-filtered season aggregations

One index on player_stats:
  - idx_playerstats_opponent_season: opponent/season conditional filtering
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_add_gamelog_schema"
down_revision = "0004_add_prop_and_nba_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- nba_player_gamelogs --------------------------------------------------
    op.create_table(
        "nba_player_gamelogs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("player_name", sa.String(100), nullable=True),
        sa.Column("team_abbreviation", sa.String(3), nullable=True),
        sa.Column("game_id", sa.String(20), nullable=False),
        sa.Column("game_date", sa.Date(), nullable=True),
        sa.Column("season", sa.SmallInteger(), nullable=False),
        sa.Column("is_home", sa.Boolean(), nullable=True),
        sa.Column("opponent_team", sa.String(3), nullable=True),
        sa.Column("minutes", sa.Numeric(5, 1), nullable=True),
        sa.Column("points", sa.SmallInteger(), nullable=True),
        sa.Column("rebounds", sa.SmallInteger(), nullable=True),
        sa.Column("assists", sa.SmallInteger(), nullable=True),
        sa.Column("threes_made", sa.SmallInteger(), nullable=True),
        sa.Column("steals", sa.SmallInteger(), nullable=True),
        sa.Column("blocks", sa.SmallInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("player_id", "game_id", name="uq_nba_gamelog_player_game"),
    )
    op.create_index(
        "idx_nba_gamelog_player_season",
        "nba_player_gamelogs",
        ["player_id", "season"],
    )
    op.create_index(
        "idx_nba_gamelog_game_date",
        "nba_player_gamelogs",
        ["game_date", "season"],
    )
    op.create_index(
        "idx_nba_gamelog_opponent",
        "nba_player_gamelogs",
        ["opponent_team", "season"],
    )

    # --- player_stats extensions (Phase 18 SC-1 Option A) ---------------------
    op.add_column("player_stats", sa.Column("opponent_team", sa.String(3), nullable=True))
    op.add_column("player_stats", sa.Column("home_away", sa.String(4), nullable=True))
    op.create_index(
        "idx_playerstats_opponent_season",
        "player_stats",
        ["opponent_team", "season"],
    )


def downgrade() -> None:
    # Reverse player_stats extensions
    op.drop_index("idx_playerstats_opponent_season", table_name="player_stats")
    op.drop_column("player_stats", "home_away")
    op.drop_column("player_stats", "opponent_team")

    # Reverse nba_player_gamelogs creation
    op.drop_index("idx_nba_gamelog_opponent", table_name="nba_player_gamelogs")
    op.drop_index("idx_nba_gamelog_game_date", table_name="nba_player_gamelogs")
    op.drop_index("idx_nba_gamelog_player_season", table_name="nba_player_gamelogs")
    op.drop_constraint(
        "uq_nba_gamelog_player_game", table_name="nba_player_gamelogs", type_="unique"
    )
    op.drop_table("nba_player_gamelogs")
