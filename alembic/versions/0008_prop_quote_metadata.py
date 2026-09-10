"""Persist prop direction, observed quote time, and actual start time."""
from alembic import op
import sqlalchemy as sa
revision = "0008_prop_quote_metadata"
down_revision = "0007_quote_identity"
branch_labels = depends_on = None

def upgrade():
    op.add_column("player_prop_snapshots", sa.Column("side", sa.String(10)))
    op.add_column("player_prop_snapshots", sa.Column("game_start_time", sa.DateTime(timezone=True)))

def downgrade():
    op.drop_column("player_prop_snapshots", "game_start_time")
    op.drop_column("player_prop_snapshots", "side")
