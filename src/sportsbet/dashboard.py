"""Publish sanitized result snapshots for the hosted dashboard."""
import json
from sqlalchemy import text
from sportsbet.db.connection import get_sync_engine

def publish_snapshot(key: str, payload: dict) -> None:
    engine = get_sync_engine()
    try:
        with engine.begin() as conn:
            conn.execute(text('INSERT INTO dashboard_snapshots(snapshot_key,payload) VALUES (:key,CAST(:payload AS JSONB)) '
                'ON CONFLICT(snapshot_key) DO UPDATE SET payload=excluded.payload,updated_at=NOW()'),
                {'key':key,'payload':json.dumps(payload,allow_nan=False)})
    finally:
        engine.dispose()
