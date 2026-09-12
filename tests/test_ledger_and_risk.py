from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import pytest
from sportsbet.ledger import Ledger
from sportsbet.graph.models import EVSignal, PropResult
from sportsbet.prop.arbitrage import make_prop_arbitrage_agent
from sportsbet.ingestion.prop_odds import PlayerPropSnapshotCreate
from sportsbet.quant.vig import american_to_raw_prob

def sig(player='A', direction='over', stake='0.02'):
    return EVSignal(ev_percentage=Decimal('.05'),expected_return=Decimal('.1'),true_probability=Decimal('.6'),
        implied_probability=Decimal('.5'),kelly_fraction=Decimal(stake),trade_plan=[],market_type='player_points',
        game_id='game',player_name=player,direction=direction)

def test_budget_survives_restart_and_deduplicates(tmp_path):
    path=tmp_path/'risk.sqlite'
    assert Ledger(path).reserve(sig(),20.5)[0]
    assert Ledger(path).reserve(sig(),20.5)[0]
    assert Ledger(path).reserve(sig('B'),20.5)[0]
    assert Ledger(path).reserve(sig('C'),20.5)==(False,'daily_exposure_limit')
    assert Ledger(path).reserve(sig(direction='under'),20.5)==(False,'correlated_exposure')

def test_concurrent_reservations_cannot_exceed_budget(tmp_path):
    ledger=Ledger(tmp_path/'risk.sqlite')
    with ThreadPoolExecutor(max_workers=6) as pool:
        result=list(pool.map(lambda i:ledger.reserve(sig(str(i)),20.5),range(12)))
    assert sum(ok for ok,_ in result)==2

def test_audit_records_rejected_and_pending_without_fabricated_results(tmp_path):
    ledger=Ledger(tmp_path/'audit.sqlite');now=datetime.now(timezone.utc)
    payload=dict(game_id='g',player='P',prop_type='points',direction='under',line=20.5,sportsbook='book',
        american_odds=100,model_probability=.6,accepted=False,stake_fraction=0,
        captured_at=now.isoformat(),game_start_time=(now+timedelta(hours=1)).isoformat())
    key=ledger.record('scan',payload)
    assert ledger.record('scan',payload)==key
    assert ledger.report()['pending_count']==1
    assert ledger.report()['roi'] is None
    ledger.settle({key:True})
    assert ledger.report()['brier_score'] is None
    assert ledger.report()['unverified_settlements']==1
    assert ledger.report(True)['sample_size']==0
    with pytest.raises(ValueError):ledger.settle({'unknown':False})


def test_manual_settlement_cli_hashes_the_exact_input_file(tmp_path,monkeypatch,capsys):
    path=tmp_path/'audit.sqlite';ledger=Ledger(path);now=datetime.now(timezone.utc)
    key=ledger.record('scan',dict(game_id='g',player='P',prop_type='points',direction='over',
        line=20.5,sportsbook='book',american_odds=100,model_probability=.6,
        captured_at=now.isoformat(),game_start_time=(now+timedelta(hours=1)).isoformat()))
    raw=json.dumps({key:True},indent=2).encode();outcomes=tmp_path/'outcomes.json';outcomes.write_bytes(raw)
    monkeypatch.setattr('sys.argv',['ledger','--path',str(path),'--settlements',str(outcomes)])
    from sportsbet.ledger import main
    main();capsys.readouterr()
    row=Ledger(path).predictions()[0]
    assert row['outcome_source']=='manual'
    assert row['outcome_ref']=='sha256:'+hashlib.sha256(raw).hexdigest()


def test_claimed_automatic_outcomes_require_retained_evidence(tmp_path):
    ledger=Ledger(tmp_path/'audit.sqlite');now=datetime.now(timezone.utc)
    key=ledger.record('scan',dict(game_id='g',player='P',prop_type='points',direction='over',
        line=20.5,sportsbook='book',american_odds=100,model_probability=.6,
        captured_at=now.isoformat(),game_start_time=(now+timedelta(hours=1)).isoformat()))
    ledger.settle({key:True},source='espn_final_stats',source_ref='legacy')
    legacy=ledger.report()
    assert legacy['settled_count']==0 and legacy['pending_count']==1
    assert legacy['unverified_settlements']==1
    with pytest.raises(ValueError,match='evidence'):
        ledger.settle({key:True},source='observed_final_stats',source_ref='verified')

@pytest.mark.parametrize('side', ['over','under'])
async def test_sample_gate_and_synthetic_prices_apply_to_both_sides(side):
    q=PlayerPropSnapshotCreate(sport='nba',player_name='P',sportsbook='book',prop_type='player_points',
        side=side.title(),line=Decimal('20.5'),price=100,implied_probability=Decimal('.5'))
    state=dict(player_name='P',prop_type='points',prop_line=Decimal('20.5'),prop_side=side,
        nba_prop_result=PropResult(true_probability=Decimal('.6') if side=='over' else Decimal('.4'),sample_size=2),
        player_prop_snapshots=[q])
    assert (await make_prop_arbitrage_agent(sport='nba')(state))['gate_reason']=='insufficient_sample'
    state['nba_prop_result'].sample_size=50
    q.sportsbook='prizepicks'
    assert (await make_prop_arbitrage_agent(sport='nba')(state))['gate_reason']=='synthetic_price'

async def test_under_push_probability_and_return_are_not_overstated():
    q=PlayerPropSnapshotCreate(sport='nba',player_name='P',sportsbook='book',prop_type='player_points',
        side='Under',line=Decimal('20'),price=200,implied_probability=american_to_raw_prob(200))
    state=dict(player_name='P',prop_type='points',prop_line=Decimal('20'),prop_side='under',
        nba_prop_result=PropResult(true_probability=Decimal('.5'),push_probability=Decimal('.1'),sample_size=50),
        player_prop_snapshots=[q])
    s=(await make_prop_arbitrage_agent(sport='nba')(state))['ev_signal']
    assert s.true_probability==Decimal('.4')
    assert s.expected_return==Decimal('.3')
    assert float(s.kelly_fraction)==pytest.approx(1/24)

async def test_scanner_routes_both_sides_through_shared_agent():
    import runpy
    from pathlib import Path
    from sportsbet.graph.graph import create_graph
    ns=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scan_game_ev.py'))
    async def quant(state):
        return {'nba_prop_result':PropResult(true_probability=Decimal('.6'),sample_size=50)}
    graph=create_graph(nba_quant_node=quant,prop_arbitrage_node=make_prop_arbitrage_agent(sport='nba'))
    quotes=[PlayerPropSnapshotCreate(sport='nba',player_name='Test Player',sportsbook='book',
        prop_type='player_points',side=side,line=Decimal('20.5'),price=price,implied_probability=american_to_raw_prob(price))
        for side,price in [('Over',-110),('Under',200)]]
    rows=await ns['run_ev_for_player'](pool=None,graph=graph,all_snapshots=quotes,
        player_name='Test Player',player_id='1',home_team='LAL',away_team='BOS',thread_id='test')
    assert {r['direction'] for r in rows}=={'over','under'}
    for row in rows:
        assert isinstance(row['ev'],EVSignal)
        assert row['ev'].direction==row['direction']
        assert row['ev'].game_id
        assert row['quote'].side.lower()==row['direction']
