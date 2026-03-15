"""Add injury_reports table.

Revision ID: 0002_add_injury_reports
Revises: 0001_initial_schema
Create Date: 2026-03-13

Hand-written migration -- autogenerate omits composite indexes (Phase 1 decision).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_add_injury_reports"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "injury_reports",
        sa.Column("id", sa.BigInteger, autoincrement=True, primary_key=True),
        sa.Column("game_id", sa.String(20), sa.ForeignKey("games.game_id"), nullable=True),
        sa.Column("player_name", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("position", sa.String(5), nullable=True),
        sa.Column("team_abbr", sa.String(3), nullable=True),
        sa.Column(
            "scraped_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("source", sa.String(50), nullable=False),
    )
    op.create_index("idx_injury_game_id", "injury_reports", ["game_id"])
    op.create_index("idx_injury_scraped_at", "injury_reports", ["scraped_at"])
    op.create_index(
        "idx_injury_player_scraped", "injury_reports", ["player_name", "scraped_at"]
    )


def downgrade() -> None:
    op.drop_index("idx_injury_player_scraped", table_name="injury_reports")
    op.drop_index("idx_injury_scraped_at", table_name="injury_reports")
    op.drop_index("idx_injury_game_id", table_name="injury_reports")
    op.drop_table("injury_reports")
