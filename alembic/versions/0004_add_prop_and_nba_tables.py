"""Add player_prop_snapshots and nba_player_stats tables.

Revision ID: 0004_add_prop_and_nba_tables
Revises: 0003_add_pbp_quant_columns
Create Date: 2026-03-22

Hand-written migration -- autogenerate omits composite indexes (Phase 1 decision).
Adds PROP-01 (player_prop_snapshots) and PROP-02 (nba_player_stats) tables with
all required indexes for Phase 10 player prop data layer.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_add_prop_and_nba_tables"
down_revision = "0003_add_pbp_quant_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- player_prop_snapshots ------------------------------------------------
    op.create_table(
        "player_prop_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("sport", sa.String(5), nullable=False),
        sa.Column("game_id", sa.String(30), nullable=True),
        sa.Column("player_name", sa.String(100), nullable=False),
        sa.Column("sportsbook", sa.String(50), nullable=False),
        sa.Column("prop_type", sa.String(40), nullable=False),
        sa.Column("line", sa.Numeric(7, 2), nullable=True),
        sa.Column("price", sa.SmallInteger(), nullable=True),
        sa.Column("implied_probability", sa.Numeric(8, 6), nullable=False),
        sa.Column(
            "snapped_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_props_player_prop_snapped",
        "player_prop_snapshots",
        ["player_name", "prop_type", "snapped_at"],
    )
    op.create_index(
        "idx_props_sport_snapped",
        "player_prop_snapshots",
        ["sport", "snapped_at"],
    )
    op.create_index(
        "idx_props_game_prop",
        "player_prop_snapshots",
        ["game_id", "prop_type"],
    )

    # --- nba_player_stats -----------------------------------------------------
    op.create_table(
        "nba_player_stats",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("player_name", sa.String(100), nullable=False),
        sa.Column("season", sa.SmallInteger(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=True),
        sa.Column("team_abbreviation", sa.String(5), nullable=True),
        sa.Column("games_played", sa.SmallInteger(), nullable=True),
        sa.Column("minutes", sa.Numeric(8, 1), nullable=True),
        sa.Column("points", sa.Integer(), nullable=True),
        sa.Column("rebounds", sa.Integer(), nullable=True),
        sa.Column("assists", sa.Integer(), nullable=True),
        sa.Column("threes_made", sa.Integer(), nullable=True),
        sa.Column("steals", sa.Integer(), nullable=True),
        sa.Column("blocks", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("player_id", "season", name="uq_nba_player_season"),
    )
    op.create_index(
        "idx_nba_player_season",
        "nba_player_stats",
        ["player_id", "season"],
    )
    op.create_index(
        "idx_nba_season",
        "nba_player_stats",
        ["season"],
    )
    op.create_index(
        "idx_nba_team_season",
        "nba_player_stats",
        ["team_id", "season"],
    )


def downgrade() -> None:
    op.drop_table("nba_player_stats")
    op.drop_table("player_prop_snapshots")
