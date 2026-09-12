import sqlite3
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from sportsbet.graph.models import AgentOddsSnapshot, ContextSignals, PropParams, PropResult
from sportsbet.prop.query_builder import PropQueryBuilder
from sportsbet.prop.nba_query_builder import NBAQueryBuilder
from sportsbet.prop.agents import make_prop_quant_agent
from sportsbet.prop.arbitrage import make_prop_arbitrage_agent
from sportsbet.ingestion.prop_odds import PlayerPropSnapshotCreate

def execute(db, builder, params):
    sql, args = builder.build(params)
    return db.execute(sql.replace('::float',''), {str(i):v.isoformat() if isinstance(v,date) else v for i,v in enumerate(args,1)}).fetchone()

def test_nfl_cutoff_matches_own_game_and_precedes_recent_limit():
    with sqlite3.connect(':memory:') as db:
        db.execute('CREATE TABLE player_stats (player_id TEXT, season INT, week INT, team TEXT, passing_yards INT, home_away TEXT)')
        db.execute('CREATE TABLE games (season INT, week INT, home_team TEXT, away_team TEXT, game_date TEXT)')
        db.executemany("INSERT INTO player_stats VALUES ('P',2025,?,'KC',?,'home')",[(1,300),(2,100),(3,500)])
        db.executemany("INSERT INTO games VALUES (2025,?,'KC','LV',?)",[(1,'2025-09-07'),(2,'2025-09-14'),(3,'2025-09-21')])
        db.execute("INSERT INTO games VALUES (2025,3,'BUF','MIA','2025-09-18')")
        p=PropParams(game_id='target',player_id='P',season=2025,sport='nfl',prop_type='pass_yds',line=Decimal('200'),filters={},as_of_date=date(2025,9,20),last_n_games=1)
        total,successes,pushes,mean=execute(db,PropQueryBuilder,p)
        assert (total,successes,pushes,mean)==(1,0,0,100)

def test_recent_nba_home_games_skip_more_recent_away_games():
    with sqlite3.connect(':memory:') as db:
        db.execute('CREATE TABLE nba_player_gamelogs (player_id INT, season INT, game_id TEXT, game_date TEXT, points INT, is_home INT)')
        db.executemany("INSERT INTO nba_player_gamelogs VALUES (1,2025,?,?,?,?)", [('old','2026-01-01',30,1),('new','2026-01-02',10,0)])
        p=PropParams(game_id='target',player_id='1',season=2025,sport='nba',prop_type='points',line=Decimal('20'),filters={},as_of_date=date(2026,1,3),last_n_games=1,home_away='home')
        assert execute(db,NBAQueryBuilder,p)==(1,1,0,30)

async def test_nfl_agent_passes_cutoff_and_recency():
    run=AsyncMock(return_value=PropResult(sample_size=0))
    with patch('sportsbet.prop.agents.run_prop_query',run):
        await make_prop_quant_agent(MagicMock())({'receiver_gsis_id':'P','game_id':'g','season':2025,'prop_type':'pass_yds','prop_line':'200','as_of_date':date(2025,9,20),'last_n_games':3,'home_away':'home'})
    p=run.call_args.args[1]
    assert (p.as_of_date,p.last_n_games,p.home_away)==(date(2025,9,20),3,'home')

@pytest.mark.parametrize('change',[{'player_name':'P Junior'},{'side':None},{'line':Decimal('21.5')}])
async def test_partial_name_unlabelled_side_and_wrong_line_cannot_price_prop(change):
    quote=PlayerPropSnapshotCreate(sport='nba',player_name='P',sportsbook='book',prop_type='player_points',side='Over',line=Decimal('20.5'),price=100,implied_probability=Decimal('.5')).model_copy(update=change)
    state={'player_name':'P','prop_type':'points','prop_line':Decimal('20.5'),'player_prop_snapshots':[quote],'nba_prop_result':PropResult(true_probability=Decimal('.6'),sample_size=30)}
    # Even a valid game-level price must not rescue a mismatched player quote.
    from datetime import datetime,timezone
    now=datetime.now(timezone.utc)
    state['context_signals']=ContextSignals(game_id='g',signals_captured_at=now,injury_flags={},odds_snapshot=AgentOddsSnapshot(game_id='g',sportsbook='book',market_type='h2h',implied_probability=Decimal('.5'),snapped_at=now))
    result=await make_prop_arbitrage_agent(sport='nba')(state)
    assert result['ev_signal'] is None
    assert result['gate_reason']=='missing_matching_prop_quote'

async def test_under_interval_is_complement_of_reported_over_interval():
    quote=PlayerPropSnapshotCreate(sport='nba',player_name='P',sportsbook='book',prop_type='player_points',side='Under',line=Decimal('20.5'),price=100,implied_probability=Decimal('.5'))
    result=await make_prop_arbitrage_agent(sport='nba')({'player_name':'P','prop_type':'points','prop_line':Decimal('20.5'),'prop_side':'under','player_prop_snapshots':[quote],'nba_prop_result':PropResult(true_probability=Decimal('.4'),sample_size=30,confidence_interval=(Decimal('.2'),Decimal('.49')))})
    assert result['ev_signal'].confidence_interval==(Decimal('.51'),Decimal('.8'))

async def test_scanner_evaluates_each_line_and_under_only_quotes():
    import runpy
    from pathlib import Path
    from sportsbet.graph.graph import create_graph
    ns=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scan_game_ev.py'))
    async def quant(state):
        return {'nba_prop_result':PropResult(true_probability=Decimal('.6'),sample_size=50)}
    graph=create_graph(nba_quant_node=quant,prop_arbitrage_node=make_prop_arbitrage_agent(sport='nba'))
    quotes=[PlayerPropSnapshotCreate(sport='nba',player_name='P',sportsbook='book',
        prop_type='player_points',side=side,line=Decimal(line),price=100,implied_probability=Decimal('.5'))
        for side,line in [('Over','20.5'),('Over','21.5'),('Under','22.5')]]
    rows=await ns['run_ev_for_player'](pool=None,graph=graph,all_snapshots=quotes,player_name='P',player_id='1',home_team='LAL',away_team='BOS',thread_id='test')
    assert {(r['direction'],r['line']) for r in rows}=={('over',20.5),('over',21.5),('under',22.5)}

async def test_default_nba_estimate_keeps_empirical_probability_and_interval(monkeypatch):
    from sportsbet.config import settings
    from sportsbet.graph.models import NBAContextSignals
    from sportsbet.prop.nba_agents import make_nba_quant_agent
    monkeypatch.setattr(settings,'experimental_probability_adjustments',False)
    base=PropResult(true_probability=Decimal('.6'),sample_size=50,confidence_interval=(Decimal('.45'),Decimal('.73')))
    run=AsyncMock(return_value=base)
    with patch('sportsbet.prop.nba_agents.run_nba_prop_query',run):
        result=await make_nba_quant_agent(MagicMock())({'receiver_gsis_id':'1','game_id':'g','season':2025,
            'prop_type':'points','prop_line':'20.5','nba_context_signals':NBAContextSignals(is_home=True,rest_days=0,pace_factor=Decimal('100'),opponent_def_rating=Decimal('115'))})
    assert result['nba_prop_result']==base


async def test_play_success_probability_cannot_become_market_recommendation():
    from sportsbet.graph.agents import make_arbitrage_agent
    from sportsbet.graph.models import QuantResult
    result=await make_arbitrage_agent()({'session_id':'test','quant_result':QuantResult(
        true_probability=Decimal('.7'),prediction_target='play_success')})
    assert result['ev_signal'] is None
    assert result['gate_reason']=='incompatible_prediction_target'


async def test_async_database_uses_exact_configured_endpoint(monkeypatch):
    from sportsbet.db.connection import create_async_pool
    from sportsbet.config import settings
    url='postgresql+asyncpg://test:encoded%40password@db.example.test:5432/test?sslmode=require'
    monkeypatch.setattr(settings,'database_url_async',url)
    create=AsyncMock()
    with patch('sportsbet.db.connection.asyncpg.create_pool',create):
        await create_async_pool()
    assert create.call_args.args[0]==url.replace('postgresql+asyncpg://','postgresql://')
    assert 'ssl' not in create.call_args.kwargs
