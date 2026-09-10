"""Move existing signal storage DDL out of the runtime scanner."""
from alembic import op
revision = "0009_signal_storage"
down_revision = "0008_prop_quote_metadata"
branch_labels = depends_on = None

def upgrade():
    op.execute("""CREATE TABLE IF NOT EXISTS ev_signals (
                        id BIGSERIAL PRIMARY KEY,
                        scan_id VARCHAR(30) NOT NULL,
                        game_id VARCHAR(50) NOT NULL,
                        home_team VARCHAR(5) NOT NULL,
                        away_team VARCHAR(5) NOT NULL,
                        game_date VARCHAR(8) NOT NULL,
                        player_name VARCHAR(100) NOT NULL,
                        prop_type VARCHAR(40) NOT NULL,
                        line NUMERIC(7,2) NOT NULL,
                        true_probability NUMERIC(8,6) NOT NULL,
                        implied_probability NUMERIC(8,6) NOT NULL,
                        ev_percentage NUMERIC(8,6) NOT NULL,
                        kelly_fraction NUMERIC(8,6) NOT NULL,
                        american_odds SMALLINT NOT NULL,
                        sample_size SMALLINT,
                        mean_stat NUMERIC(7,2),
                        sportsbook VARCHAR(50) NOT NULL,
                        gated BOOLEAN NOT NULL DEFAULT FALSE,
                        trade_plan JSONB,
                        opponent_def_rating NUMERIC(7,2),
                        rest_days SMALLINT,
                        is_home BOOLEAN,
                        strength VARCHAR(10) NOT NULL DEFAULT 'medium',
                        direction VARCHAR(5) NOT NULL DEFAULT 'over',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )""")
    op.execute("ALTER TABLE ev_signals ADD COLUMN IF NOT EXISTS direction VARCHAR(5) DEFAULT 'over'")
    for name, columns in (("idx_ev_scan_id","scan_id"),("idx_ev_game_date","game_date"),
                          ("idx_ev_player_prop","player_name,prop_type"),("idx_ev_created_at","created_at")):
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON ev_signals ({columns})")

def downgrade():
    # Table may predate this migration; preserve historical signals.
    pass
