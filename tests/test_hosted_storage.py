"""Real PostgreSQL contract checks, run against a disposable CI database."""
import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
import pytest
import sqlalchemy as sa
from sportsbet.ledger import Ledger
from sportsbet.graph.models import EVSignal
from sportsbet.config import settings
from sportsbet.provider_cache import ProviderResponseCache

pytestmark = pytest.mark.skipif(not os.environ.get('SPORTSBET_TEST_DATABASE_URL'),reason='Disposable test database required')

def test_postgres_audit_and_concurrent_budget():
    url=os.environ['SPORTSBET_TEST_DATABASE_URL']
    ledger=Ledger(database_url=url)
    group=uuid.uuid4().hex
    now=datetime.now(timezone.utc)
    key=ledger.record(group,dict(game_id=group,player='P',prop_type='points',direction='over',line=20.5,
        sportsbook='book',american_odds=100,model_probability=.6,captured_at=now.isoformat(),
        game_start_time=(now+timedelta(hours=1)).isoformat(),model_version=group))
    ledger.settle({key:True})
    assert any(r['prediction_id']==key and r['outcome'] is True for r in ledger.predictions())
    report=ledger.report(model_version=group)
    assert report['settled_count']==0 and report['unverified_settlements']==1
    def reserve(i):
        signal=EVSignal(game_id=group,player_name=str(i),direction='over',market_type='player_points',
            ev_percentage=Decimal('.1'),true_probability=Decimal('.6'),implied_probability=Decimal('.5'),
            kelly_fraction=Decimal('.02'),trade_plan=[])
        return Ledger(database_url=url).reserve(signal,20.5,risk_day=group)[0]
    with ThreadPoolExecutor(max_workers=6) as pool:
        assert sum(pool.map(reserve,range(12)))==2


def test_postgres_rolling_api_budget_is_atomic_across_connections(monkeypatch):
    import sportsbet.ledger as ledger_module

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2020, 1, 2, tzinfo=timezone.utc)

    monkeypatch.setattr(ledger_module, 'datetime', Clock)
    monkeypatch.setattr(settings, 'odds_rolling_credit_limit', 6)
    url = os.environ['SPORTSBET_TEST_DATABASE_URL']
    ledger = Ledger(database_url=url)
    with ledger.connect() as db:
        db.execute('INSERT INTO api_usage VALUES (?,?)', ('2020-01-01', 5))
    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: Ledger(database_url=url).reserve_api_credits(1, 25), range(12)))
        assert sum(results) == 1
        assert not Ledger(database_url=url).reserve_api_credits(1, 25)
    finally:
        # This module only runs against the explicitly configured disposable test DB.
        with ledger.connect() as db:
            db.execute('DELETE FROM api_usage WHERE risk_day IN (?,?)', ('2020-01-01', '2020-01-02'))


def test_provider_cache_coalesces_refresh_and_verifies_payload():
    engine=sa.create_engine(os.environ['SPORTSBET_TEST_DATABASE_URL'])
    cache=ProviderResponseCache(engine)
    key='odds:event:nfl:'+uuid.uuid4().hex
    now=datetime.now(timezone.utc)
    owners=[uuid.uuid4().hex for _ in range(8)]
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            claims=list(pool.map(lambda owner:cache.claim(key,'the_odds_api','nfl',owner,now),owners))
        assert sum(claims)==1
        owner=owners[claims.index(True)]
        payload={'id':'event','home_team':'Home','away_team':'Away','commence_time':
            (now+timedelta(hours=1)).isoformat(),'bookmakers':[]}
        cache.store(key,'the_odds_api','nfl',owner,payload,now,now+timedelta(minutes=5))
        loaded=cache.load(key,'the_odds_api','nfl',now+timedelta(seconds=1))
        assert loaded and loaded.payload==payload and loaded.captured_at==now
        assert cache.load(key,'the_odds_api','nfl',now+timedelta(minutes=6)) is None
    finally:
        with engine.begin() as conn:
            conn.execute(sa.text('DELETE FROM provider_response_cache WHERE cache_key=:key'),{'key':key})
        engine.dispose()


def test_prospective_database_scope_matches_frozen_in_memory_cohort():
    import json
    import psycopg
    from tests.test_multisport_edge import forecast, NOW
    from sportsbet.quant.multisport_edge import ProspectiveLedger, audit_sport

    url=os.environ['SPORTSBET_TEST_DATABASE_URL'];group=uuid.uuid4().hex
    writer=Ledger(database_url=url)
    records={
        'before':forecast('nba','2026-09-25T03:59:59+00:00'),
        'boundary':forecast('nba','2026-09-24T21:00:00-07:00'),
        'after':forecast('nba','2026-09-25T04:01:00+00:00'),
        'cfb':forecast('cfb'),
        'old-model':forecast('nba',model_version='old'),
        'nfl-malformed':dict(sport='nfl',model_version='empirical-jeffreys-v4',captured_at='not a timestamp'),
    }
    class GroupLedger(Ledger):
        def _prediction_records(self,**kwargs):
            return [r for r in super()._prediction_records(**kwargs) if r[0].startswith(group)]
    class GroupProspectiveLedger(ProspectiveLedger):
        def _prediction_records(self,**kwargs):
            return [r for r in super()._prediction_records(**kwargs) if r[0].startswith(group)]
    try:
        with writer.connect() as db:
            for key,payload in records.items():
                db.execute('INSERT INTO predictions(id,scan_id,payload,outcome) VALUES (?,?,?,?)',
                    (group+key,group,json.dumps(payload),None))
        full=GroupLedger(database_url=url);scoped=GroupProspectiveLedger(database_url=url)
        with scoped.snapshot():
            assert {r['prediction_id'] for r in scoped.predictions()}=={
                group+'boundary',group+'after',group+'cfb'}
            for sport in ('nba','cfb'):
                expected=audit_sport(full,sport,now=NOW)
                actual=audit_sport(scoped,sport,now=NOW)
                assert actual==expected
        with scoped.connect() as db:
            with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
                db.execute('DELETE FROM predictions WHERE 1=0')
        bad=forecast('nba');bad['captured_at']='not a timestamp'
        with writer.connect() as db:
            db.execute('INSERT INTO predictions(id,scan_id,payload,outcome) VALUES (?,?,?,?)',
                (group+'bad',group,json.dumps(bad),None))
        with pytest.raises(psycopg.errors.InvalidDatetimeFormat):
            scoped.predictions()
    finally:
        with writer.connect() as db:
            db.execute('DELETE FROM predictions WHERE scan_id=?',(group,))
