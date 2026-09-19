"""Execute the frontend pagination SQL against disposable PostgreSQL, never production."""
import json
import os
from pathlib import Path
import re

import pytest
import sqlalchemy as sa

pytestmark = pytest.mark.skipif(
    not os.environ.get('SPORTSBET_TEST_DATABASE_URL'), reason='Disposable test database required'
)


def test_forecast_pages_remain_bounded_with_large_history_and_exclude_old_candidates():
    source = Path('frontend/lib/forecastPage.ts').read_text(encoding='utf8')
    query = source.split('export const FORECAST_PAGE_QUERY=`', 1)[1].split('`;', 1)[0]
    query = re.sub(r'\$(\d)', lambda match: f'(:p{match[1]})', query)
    engine = sa.create_engine(os.environ['SPORTSBET_TEST_DATABASE_URL'])
    try:
        with engine.begin() as connection:
            # Temporary shadow table keeps every fixture inside this disposable connection.
            connection.execute(sa.text('''CREATE TEMP TABLE dashboard_snapshots (
                snapshot_key text PRIMARY KEY,payload jsonb,updated_at timestamptz
            ) ON COMMIT DROP'''))
            for game in range(13):
                payload = dict(generated_at='2026-09-10T12:00:00Z', games=[], signals=[
                    dict(id=f'{game}-{row}', gated=False) for row in range(500)
                ])
                connection.execute(sa.text('''INSERT INTO dashboard_snapshots VALUES
                    (:key,CAST(:payload AS jsonb),now()-CAST(:age AS interval))'''),
                    dict(key=f'signals:nfl:{game:02}', payload=json.dumps(payload),
                         age='1 day' if game == 0 else '0 seconds'))
            values=dict(p1='signals:nfl:%',p2=['player-profiles:nfl'],p3=False,p4=100,p5=0)
            first=connection.execute(sa.text(query),values).scalar_one()
            assert first['total_count']==6500 and len(first['rows'])==100
            # A row carries one signal only. Repeating the snapshot's entire
            # game list for every signal made the public query exceed its timeout.
            assert all(row['payload']['games']==[] for row in first['rows'])
            second=connection.execute(sa.text(query),{**values,'p5':100}).scalar_one()
            assert first['revision']==second['revision']
            first_ids={row['payload']['signals'][0]['id'] for row in first['rows']}
            second_ids={row['payload']['signals'][0]['id'] for row in second['rows']}
            assert first_ids.isdisjoint(second_ids)
            assert first['invalid_envelopes']==0
            candidates=connection.execute(sa.text(query),{**values,'p3':True,'p4':5001}).scalar_one()
            assert candidates['total_count']==6000 and len(candidates['rows'])==5001
            assert candidates['window_complete'] is True
            assert all(not row['payload']['signals'][0]['id'].startswith('0-')
                       for row in candidates['rows'])
            connection.execute(sa.text("UPDATE dashboard_snapshots SET updated_at=updated_at+interval '1 second' WHERE snapshot_key='signals:nfl:12'"))
            changed=connection.execute(sa.text(query),values).scalar_one()
            assert changed['revision']!=first['revision']
            for index in range(89):
                connection.execute(sa.text('''INSERT INTO dashboard_snapshots VALUES
                    (:key,'{"generated_at":"2026-09-10T12:00:00Z","signals":[],"games":[]}'::jsonb,now())'''),
                    dict(key=f'signals:nfl:overflow:{index}'))
            overflow=connection.execute(sa.text(query),{**values,'p3':True,'p4':5001}).scalar_one()
            assert overflow['window_complete'] is False
    finally:
        engine.dispose()
