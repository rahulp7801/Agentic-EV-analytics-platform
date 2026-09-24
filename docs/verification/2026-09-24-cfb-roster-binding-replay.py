"""Offline replay: PYTHONPATH=src python docs/verification/2026-09-24-cfb-roster-binding-replay.py."""
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path

from sportsbet.prop.availability import injury_report, player_availability

root = Path(__file__).resolve().parent
report = json.loads((root / '2026-09-24-cfb-roster-binding.json').read_text(encoding='utf-8'))
source = report['roster_source']
raw = gzip.decompress((root / '2026-09-24-cfb-roster-324.json.gz').read_bytes())
assert hashlib.sha256(raw).hexdigest() == source['source_sha256']
athletes = [a for group in json.loads(raw)['athletes'] for a in group['items']]
assert all(isinstance(a.get('injuries'), list) for a in athletes)
now = datetime.fromisoformat(source['observed_at'])
team = dict(abbreviation='CCU', roster_names=[a['displayName'] for a in athletes],
    roster_ids={a['id']: a['displayName'] for a in athletes},
    roster_statuses={a['displayName']: a['status']['name'] for a in athletes},
    reports=[injury_report(a['displayName'], a['position']['abbreviation'], injury, now)
        for a in athletes for injury in a['injuries']], injury_coverage='observed',
    roster_source_url=source['url'], roster_source_sha256=source['source_sha256'],
    injury_source_url=source['url'], injury_source_sha256=source['source_sha256'])
context = dict(status='observed', captured_at=source['observed_at'], teams=[team],
    source_url=source['url'], source_sha256=source['source_sha256'])
old, _ = player_availability(context, 'Dominic Knicely', now)
new, reason = player_availability(context, 'Dominic Knicely', now, player_id='5203477', sport='cfb')
assert old['status'] == 'unavailable'
assert new['status'] == 'observed' and new['roster_player_name'] == 'Dominic Lee-Knicely'
assert new['player_id'] == '5203477' and new['probability_adjusted'] is False
assert new['identity_source_sha256'] == source['source_sha256']
print(json.dumps({'previous_status':old['status'], 'exact_id_status':new['status'],
    'reason':reason, 'roster_player_name':new['roster_player_name'], 'source_sha256':source['source_sha256']}))
