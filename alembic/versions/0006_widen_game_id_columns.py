"""Widen game_id columns to accommodate Odds API 32-char event IDs.

Revision ID: 0006_widen_game_id_columns
Revises: 0005_add_gamelog_schema
Create Date: 2026-03-27

Odds API event IDs are 32 hex chars; player_prop_snapshots.game_id and
odds_snapshots.game_id were VARCHAR(30) which caused truncation errors.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_widen_game_id_columns"
down_revision = "0005_add_gamelog_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "player_prop_snapshots",
        "game_id",
        type_=sa.String(64),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "player_prop_snapshots",
        "game_id",
        type_=sa.String(30),
        existing_nullable=True,
    )
