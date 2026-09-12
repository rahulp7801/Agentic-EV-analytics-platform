"""Run inside the built worker image, without networking or production credentials."""
import asyncio
import os
import ssl
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sportsbet
from sportsbet.graph.graph import create_graph
from sportsbet.ingestion.archive import write_archive


assert os.getuid() == 10001
assert not os.environ.get('ODDS_API_KEY')
for name in ('.env', '.git', 'frontend', 'src', 'uv.lock', 'pyproject.toml'):
    assert not Path('/app', name).exists()
assert not os.access(Path(sportsbet.__file__).parent, os.W_OK)
assert not Path(sys.executable).with_name('uv').exists()
ssl.create_default_context(cafile='certs/supabase-prod-ca-2021.crt')

# Verify the actual worker imports with the final Linux shared libraries.
subprocess.run([sys.executable, '-m', 'sportsbet.daily', '--help'], check=True)
subprocess.run([sys.executable, '-m', 'sportsbet.ingestion.kalshi_history', '--help'], check=True)

now = datetime.now(timezone.utc)
legs = []
for side in ('yes', 'no'):
    legs.append(dict(leg_id=side, venue='kalshi', account='arithmetic-fixture', quote_id=side,
        source_sha256='a'*64, rules_ref='synthetic-payoff-fixture', observed_at=now,
        available_at=now, event_start=now+timedelta(days=1), unit_cost='0.40',
        fee_per_unit_bound='0', max_units='1', unit_step='1',
        payouts={state: '1' if side == state else '0' for state in ('yes', 'no')}))


async def check():
    output = await create_graph().ainvoke(dict(session_id='image-smoke', request_type='market_analysis',
        market_request=dict(as_of=now, budget='1', candidates=[dict(candidate_id='fixture',
            event_scope='fixture', coverage_review_ref='synthetic-fixture-review', states=['yes', 'no'], legs=legs)])))
    report = output['market_report']
    result, = report['results']
    assert report['status'] == 'complete' and not report['execution_ready']
    assert result['status'] == 'scenario_edge' and result['worst_profit'] == '0.20'
    archive = write_archive(report)
    assert archive.is_file() and archive.is_relative_to('.local')


asyncio.run(check())
print('Worker image verified: non-root, read-only code, writable evidence, native solver, no network. Fixture is not market performance.')
