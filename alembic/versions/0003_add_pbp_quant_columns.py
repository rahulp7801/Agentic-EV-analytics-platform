"""Add air_yards, two_point_attempt, complete_pass to play_by_play.

Revision ID: 0003_add_pbp_quant_columns
Revises: 0002_add_injury_reports
Create Date: 2026-03-22

Hand-written migration -- autogenerate omits composite indexes (Phase 1 decision).
Closes GAP-1 from v1.0 milestone audit: query_builder.py templates reference
these columns but they were absent from the initial schema.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_add_pbp_quant_columns"
down_revision = "0002_add_injury_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("play_by_play", sa.Column("air_yards", sa.SmallInteger(), nullable=True))
    op.add_column("play_by_play", sa.Column("two_point_attempt", sa.SmallInteger(), nullable=True))
    op.add_column("play_by_play", sa.Column("complete_pass", sa.SmallInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("play_by_play", "complete_pass")
    op.drop_column("play_by_play", "two_point_attempt")
    op.drop_column("play_by_play", "air_yards")
