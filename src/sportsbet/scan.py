"""Scheduled NFL/NBA prop evaluation. External data stays outside graph logic."""
from __future__ import annotations
import argparse
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
import httpx
from sportsbet.config import settings
from sportsbet.dashboard import publish_snapshot
from sportsbet.db.connection import create_async_pool
from sportsbet.graph.graph import create_graph
from sportsbet.ingestion.prop_odds import PlayerPropSnapshotCreate
from sportsbet.ledger import Ledger
from sportsbet.prop.agents import make_prop_quant_agent
from sportsbet.prop.nba_agents import make_nba_quant_agent
from sportsbet.prop.arbitrage import make_prop_arbitrage_agent
from sportsbet.quant.vig import american_to_raw_prob

MARKETS = {'nba':{'player_points':'points','player_rebounds':'rebounds','player_assists':'assists'},
           'nfl':{'player_pass_yds':'pass_yds','player_rush_yds':'rush_yds','player_reception_yds':'rec_yds'}}
SPORT_KEYS = {'nba':'basketball_nba','nfl':'americanfootball_nfl'}

def timestamp(value: str) -> datetime:
    result=datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.tzinfo is None:
        raise ValueError('Provider timestamp has no timezone')
    return result

def quotes_from_event(event: dict, sport: str) -> list[PlayerPropSnapshotCreate]:
    start=timestamp(event['commence_time'])
    quotes=[]
    for book in event.get('bookmakers',[]):
        if book.get('key','').lower()=='prizepicks':
            continue
        for market in book.get('markets',[]):
            if market.get('key') not in MARKETS[sport]:
                continue
            updated=market.get('last_update') or book.get('last_update')
            if not updated:
                continue
            for outcome in market.get('outcomes',[]):
                if outcome.get('name') not in ('Over','Under') or not outcome.get('description') or outcome.get('point') is None:
                    continue
                price=outcome.get('price')
                if type(price) is not int or abs(price)<100:
                    continue
                quotes.append(PlayerPropSnapshotCreate(sport=sport,game_id=event['id'],player_name=outcome['description'],
                    sportsbook=book['key'],prop_type=market['key'],side=outcome['name'],line=Decimal(str(outcome['point'])),
                    price=price,implied_probability=american_to_raw_prob(price),snapped_at=timestamp(updated),game_start_time=start))
    return quotes

async def evaluate_event(pool, event: dict, sport: str, ledger: Ledger, scan_id: str) -> dict:
    start=timestamp(event['commence_time'])
    game_date=start.astimezone(ZoneInfo('America/New_York')).date()
    season=game_date.year if game_date.month >= (10 if sport=='nba' else 9) else game_date.year-1
    graph=create_graph(nba_quant_node=make_nba_quant_agent(pool),prop_quant_node=make_prop_quant_agent(pool),
        prop_arbitrage_node=make_prop_arbitrage_agent(sport=sport))
    quotes=quotes_from_event(event,sport)
    export=[]
    # A separate model evaluation per line; prices are compared only for identical outcomes.
    selections=sorted({(q.player_name,q.prop_type,q.line,q.side) for q in quotes})
    for player,market,line,side in selections:
        candidates=[q for q in quotes if (q.player_name,q.prop_type,q.line,q.side)==(player,market,line,side)]
        fresh=[q for q in candidates if -60 <= (datetime.now(timezone.utc)-q.snapped_at).total_seconds() <= 300]
        quote=min(fresh or candidates,key=lambda q:american_to_raw_prob(q.price))
        async with pool.acquire() as conn:
            table='nba_player_gamelogs' if sport=='nba' else 'player_stats'
            players=await conn.fetch(f'SELECT DISTINCT player_id FROM {table} WHERE LOWER(player_name)=LOWER($1)',player)
        if len(players)!=1:
            continue  # Unknown/ambiguous identity cannot borrow another player's history.
        state=await graph.ainvoke(dict(session_id=scan_id,request_type='nba_prop_analysis' if sport=='nba' else 'prop_analysis',
            game_id=event['id'],home_team=event['home_team'],away_team=event['away_team'],season=season-2,week=1,
            receiver_gsis_id=str(players[0]['player_id']),player_name=player,sport=sport,prop_type=MARKETS[sport][market],
            prop_line=line,prop_side=side.lower(),as_of_date=game_date,last_n_games=40,player_prop_snapshots=[quote]))
        prop=state.get('nba_prop_result' if sport=='nba' else 'prop_result')
        if not prop or prop.true_probability is None:
            continue
        probability=prop.true_probability if side=='Over' else 1-prop.true_probability-prop.push_probability
        signal=state.get('ev_signal')
        accepted=False
        reason=state.get('gate_reason') or 'no_positive_edge'
        now=datetime.now(timezone.utc)
        if signal:
            if now >= start: reason='game_started'
            elif not -60 <= (now-quote.snapped_at).total_seconds() <= 300: reason='stale_quote'
            else: accepted,reason=ledger.reserve(signal,float(line))
        payload=dict(game_id=event['id'],player=player,player_id=str(players[0]['player_id']),sport=sport,
            game_date=game_date.isoformat(),prop_type=MARKETS[sport][market],direction=side.lower(),line=float(line),
            sportsbook=quote.sportsbook,american_odds=quote.price,model_probability=float(probability),
            push_probability=float(prop.push_probability),captured_at=now.isoformat(),game_start_time=start.isoformat(),
            quote_time=quote.snapped_at.isoformat(),accepted=accepted,gate_reason=reason,
            stake_fraction=float(signal.kelly_fraction) if accepted else 0,model_version='empirical-v2')
        prediction_id=ledger.record(scan_id,payload)
        if signal:
            export.append(dict(id=prediction_id,prediction_id=prediction_id,player=player,sport=sport,
                game_id=event['id'],prop_type=MARKETS[sport][market],direction=side.lower(),line=float(line),
                team='',opponent='',home_team=event['home_team'],away_team=event['away_team'],
                true_prob=float(probability),implied_prob=float(signal.implied_probability),ev_pct=float(signal.ev_percentage),
                expected_return=float(signal.expected_return),push_probability=float(prop.push_probability),
                kelly_fraction=float(signal.kelly_fraction) if accepted else 0,gated=not accepted,gate_reason=reason,
                sportsbook=quote.sportsbook,american_odds=quote.price,snapped_at=quote.snapped_at.isoformat(),
                game_start_time=start.isoformat(),sample_size=prop.sample_size,mean_stat=float(prop.mean_stat) if prop.mean_stat is not None else None,
                confidence_interval=[float(x) for x in signal.confidence_interval] if signal.confidence_interval else None,
                model_version='empirical-v2',strength='unrated',trade_plan=[],injury_flags={},market_type=market))
    return dict(generated_at=datetime.now(timezone.utc).isoformat(),signals=export,games=[dict(game_id=event['id'],
        home_team=event['home_team'],away_team=event['away_team'],date=game_date.strftime('%Y%m%d'),sport=sport)])

async def run(sports: list[str], daily_credit_limit: int):
    if not settings.odds_api_key or not settings.analytics_database_url:
        raise ValueError('Worker credentials are not configured')
    ledger=Ledger()
    pool=await create_async_pool()
    scan_id=uuid.uuid4().hex
    try:
        async with httpx.AsyncClient(base_url='https://api.the-odds-api.com/v4',timeout=20) as client:
            for sport in sports:
                response=await client.get(f'/sports/{SPORT_KEYS[sport]}/events',params={'apiKey':settings.odds_api_key})
                if response.status_code!=200: raise RuntimeError(f'Event provider returned HTTP {response.status_code}')
                now=datetime.now(timezone.utc)
                events=sorted(response.json(),key=lambda e:e['commence_time'])
                for event in events:
                    start=timestamp(event['commence_time'])
                    if not now < start <= now+timedelta(hours=24): continue
                    if not ledger.reserve_api_credits(len(MARKETS[sport]),daily_credit_limit): break
                    response=await client.get(f'/sports/{SPORT_KEYS[sport]}/events/{event["id"]}/odds',params={
                        'apiKey':settings.odds_api_key,'regions':'us','markets':','.join(MARKETS[sport]),'oddsFormat':'american'})
                    if response.status_code!=200: raise RuntimeError(f'Quote provider returned HTTP {response.status_code}')
                    result=await evaluate_event(pool,response.json(),sport,ledger,scan_id)
                    publish_snapshot(f'signals:{sport}:{event["id"]}',result)
        publish_snapshot('metrics:all',ledger.report())
        publish_snapshot('metrics:recommendations',ledger.report(True))
    finally:
        await pool.close()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sport',choices=['nba','nfl','both'],default='both')
    parser.add_argument('--daily-credit-limit',type=int,default=25)
    args=parser.parse_args()
    try:
        asyncio.run(run(['nfl','nba'] if args.sport=='both' else [args.sport],args.daily_credit_limit))
    except Exception as exc:
        raise SystemExit(f'Market update failed ({type(exc).__name__})') from None

if __name__=='__main__': main()
