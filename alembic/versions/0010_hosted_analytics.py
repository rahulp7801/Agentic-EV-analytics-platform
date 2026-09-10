"""Durable hosted dashboard and analytics storage."""
from alembic import op
revision = '0010_hosted_analytics'
down_revision = '0009_signal_storage'
branch_labels = depends_on = None

def upgrade():
    op.execute('CREATE TABLE dashboard_snapshots (snapshot_key TEXT PRIMARY KEY, payload JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())')
    op.execute('CREATE SCHEMA analytics')
    op.execute('CREATE TABLE analytics.predictions (id TEXT PRIMARY KEY, scan_id TEXT NOT NULL, payload TEXT NOT NULL, outcome TEXT)')
    op.execute('CREATE TABLE analytics.exposure (identity TEXT PRIMARY KEY, group_key TEXT NOT NULL, risk_day TEXT NOT NULL, fraction DOUBLE PRECISION NOT NULL)')
    op.execute('CREATE INDEX exposure_day ON analytics.exposure(risk_day)')
    op.execute('CREATE INDEX exposure_group ON analytics.exposure(group_key)')
    op.execute('CREATE TABLE analytics.quotes (identity TEXT NOT NULL, captured_at TEXT NOT NULL, probability DOUBLE PRECISION NOT NULL, PRIMARY KEY(identity,captured_at))')

def downgrade():
    op.execute('DROP TABLE analytics.quotes, analytics.exposure, analytics.predictions')
    op.execute('DROP SCHEMA analytics')
    op.execute('DROP TABLE dashboard_snapshots')
