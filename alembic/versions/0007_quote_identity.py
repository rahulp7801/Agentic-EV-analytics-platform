"""Preserve outcome identity and actual start time for quote replay."""
from alembic import op
import sqlalchemy as sa

revision = "0007_quote_identity"
down_revision = "0006_widen_game_id_columns"
branch_labels = depends_on = None

def upgrade():
    op.add_column("odds_snapshots", sa.Column("outcome_name", sa.String(100)))
    op.add_column("odds_snapshots", sa.Column("game_start_time", sa.DateTime(timezone=True)))

def downgrade():
    op.drop_column("odds_snapshots", "game_start_time")
    op.drop_column("odds_snapshots", "outcome_name")
