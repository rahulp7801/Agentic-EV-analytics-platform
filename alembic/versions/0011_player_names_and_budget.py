"""NFL player identity and persistent provider budget."""
from alembic import op
revision = '0011_player_names_and_budget'
down_revision = '0010_hosted_analytics'
branch_labels = depends_on = None

def upgrade():
    op.execute('ALTER TABLE player_stats ADD COLUMN player_name VARCHAR(100)')
    op.execute('CREATE INDEX ix_player_stats_player_name ON player_stats(player_name)')
    op.execute('CREATE TABLE analytics.api_usage (risk_day TEXT PRIMARY KEY, credits INTEGER NOT NULL)')

def downgrade():
    op.execute('DROP TABLE analytics.api_usage')
    op.execute('DROP INDEX ix_player_stats_player_name')
    op.execute('ALTER TABLE player_stats DROP COLUMN player_name')
