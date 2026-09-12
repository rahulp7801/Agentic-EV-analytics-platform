"""Daily read-only orchestration: refresh histories, collect markets, evaluate props."""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from sportsbet.dashboard import load_snapshot, publish_snapshot
from sportsbet.market_watch import run as watch, DEFAULT_GAME_LIMIT
from sportsbet.ledger import Ledger
from sportsbet.model_contract import MODEL_VERSION
from sportsbet.refresh import refresh_history
from sportsbet.scan import run as scan, timestamp
from sportsbet.schedules import collect as collect_schedule
from sportsbet.settlement import pending_schedule_offsets, settle_final_props

MODES=('daily','monitor','public_daily','public_monitor')
PUBLIC_SCOPES={
    'public_daily':(
        'Public-only daily collection: Kalshi markets, ESPN schedules, NBA/NFL history refresh, '
        'and settlement evaluation. Sportsbooks, PrizePicks and prop recommendations are not '
        'requested. Partial market sampling is retained explicitly. This is periodic collection, '
        'not continuous arbitrage monitoring.'
    ),
    'public_monitor':(
        'Public-only market observation: Kalshi markets and ESPN schedules. History refresh, '
        'settlement evaluation, sportsbooks, PrizePicks and prop recommendations are not requested. '
        'Partial market sampling is retained explicitly. This is periodic collection, not continuous '
        'arbitrage monitoring.'
    ),
}


class DailyState(TypedDict, total=False):
    sports: list[str]
    mode: str
    daily_credit_limit: int
    histories: dict
    markets: dict
    schedules: dict
    schedule_evidence: dict
    settlements: dict
    props: dict
    report: dict


def create_daily_graph():
    graph=StateGraph(DailyState)

    async def schedules(state):
        results={};evidence={}
        for sport in state['sports']:
            catchup=state['mode'] in ('daily','public_daily')
            now=datetime.now(timezone.utc)
            current=await collect_schedule(sport,now)
            publish_snapshot('schedule:'+sport,current)
            results[sport]={'status':current['status'],'captured_at':current['captured_at']}
            if catchup:
                try:
                    extra=pending_schedule_offsets(Ledger(),sport,now)
                except Exception:
                    extra=()
                offsets=tuple(sorted(set(range(-7,-1))|set(extra)))
                older=await collect_schedule(sport,now,offsets=offsets)
                combined={**current,'captured_at':older['captured_at'],
                    'games':older.get('games',[])+current.get('games',[]),
                    'failures':older.get('failures',[])+current.get('failures',[]),
                    'sources':older.get('sources',[])+current.get('sources',[]),
                    'partial':older.get('status')!='complete' or current.get('status')!='complete'}
                combined['status']='complete' if not combined['partial'] else 'unavailable' if (
                    older.get('status')=='unavailable' and current.get('status')=='unavailable') else 'partial'
                evidence[sport]=combined
            else:
                evidence[sport]=current
        return {'schedules':results,'schedule_evidence':evidence}

    async def histories(state):
        results={}
        if state['mode']=='public_monitor':
            return {'histories':{sport:{'status':'not_requested'} for sport in state['sports']}}
        for sport in state['sports']:
            now=datetime.now(timezone.utc)
            if state['mode'] in ('daily','public_daily'):
                result=await asyncio.to_thread(refresh_history,sport,now.date())
            else:
                result=load_snapshot('refresh:'+sport) or {'status':'not_run'}
                try:
                    # Compare after the read: a concurrent refresh may finish during I/O.
                    age=datetime.now(timezone.utc)-timestamp(result['finished_at'])
                    if result['status']!='complete' or not timedelta(0)<=age<=timedelta(hours=36):
                        result={'status':'stale'}
                except (KeyError,ValueError,TypeError,AttributeError):
                    result={'status':'not_run'}
            results[sport]=result
        return {'histories':results}

    async def markets(state):
        results={}
        public=state['mode'].startswith('public_')
        for sport in state['sports']:
            try:
                summary,_=await watch(sport,state['daily_credit_limit'],DEFAULT_GAME_LIMIT,True,**({'provider':'kalshi'} if public else {}))
                complete = bool(summary['sources']) and all(
                    source['status']=='observed' and not source.get('partial_coverage',True)
                    for source in summary['sources'].values()
                )
                status='complete' if complete else 'degraded'
                if public:
                    status='observed' if summary['sources'].get('kalshi',{}).get('status')=='observed' else 'degraded'
                results[sport]=dict(status=status,
                    sources=summary['sources'],captured_at=summary['captured_at'])
            except Exception as exc:
                results[sport]=dict(status='failed',error_type=type(exc).__name__)
        return {'markets':results}

    async def props(state):
        if state['mode'].startswith('public_'):
            return {'props':{sport:{'status':'not_requested','reason':'public_only_collection'} for sport in state['sports']}}
        ready=[s for s in state['sports'] if state['histories'][s]['status']=='complete']
        results={}
        for sport in set(state['sports'])-set(ready):
            result=dict(status='blocked',reason='history_refresh_unavailable',sport=sport,
                finished_at=datetime.now(timezone.utc).isoformat(),execution_ready=False)
            publish_snapshot('scan:'+sport,result)
            results[sport]=result
        if ready:
            try:
                results.update(await scan(ready,state['daily_credit_limit']))
            except Exception as exc:
                for sport in ready:
                    result=dict(status='failed',error_type=type(exc).__name__,sport=sport,
                        finished_at=datetime.now(timezone.utc).isoformat(),execution_ready=False)
                    publish_snapshot('scan:'+sport,result)
                    results[sport]=result
        return {'props':results}

    async def settlements(state):
        if state['mode']=='public_monitor':
            return {'settlements':{sport:{'status':'not_requested','reason':'monitor_mode'}
                for sport in state['sports']}}
        try:
            ledger=Ledger()
        except Exception as exc:
            return {'settlements':{sport:{'status':'failed','error_type':type(exc).__name__}
                for sport in state['sports']}}
        results={}
        for sport in state['sports']:
            if state['histories'][sport]['status']!='complete':
                results[sport]={'status':'blocked','reason':'history_refresh_unavailable'}
                continue
            try:
                results[sport]=await asyncio.to_thread(
                    settle_final_props,ledger,sport,state['schedule_evidence'][sport])
            except Exception as exc:
                results[sport]={'status':'failed','error_type':type(exc).__name__}
        try:
            publish_snapshot('metrics:all',ledger.report(model_version=MODEL_VERSION))
            publish_snapshot('metrics:recommendations',ledger.report(True,model_version=MODEL_VERSION))
        except Exception as exc:
            for result in results.values():
                if result['status']=='complete':
                    result.update(status='failed',error_type=type(exc).__name__)
        return {'settlements':results}

    def report(state):
        public=state['mode'].startswith('public_')
        groups=('markets','schedules') if public else ('histories','markets','props','schedules','settlements')
        if state['mode']=='public_daily':groups+=('histories','settlements')
        accepted=('complete','observed') if public else ('complete',)
        healthy=all(r['status'] in accepted for group in groups for r in state[group].values())
        result=dict(mode=state['mode'],finished_at=datetime.now(timezone.utc).isoformat(),
            status=('observed' if public else 'complete') if healthy else 'degraded',execution_ready=False,
            histories=state['histories'],markets=state['markets'],schedules=state['schedules'],
            settlements=state['settlements'],
            props={s:{k:v for k,v in r.items() if k not in ('attempts','coverage')} for s,r in state['props'].items()})
        if public:
            result['scope']=PUBLIC_SCOPES[state['mode']]
        publish_snapshot('pipeline:'+state['mode'],result)
        return {'report':result}

    graph.add_node('histories',histories)
    graph.add_node('markets',markets)
    graph.add_node('schedules',schedules)
    graph.add_node('settlements',settlements)
    graph.add_node('props',props)
    graph.add_node('report',report)
    graph.add_edge(START,'histories')
    graph.add_edge(START,'markets')
    graph.add_edge(START,'schedules')
    # Collect market prices before props compete for the remaining paid allowance.
    graph.add_edge(['histories','schedules'],'settlements')
    graph.add_edge(['markets','settlements'],'props')
    graph.add_edge('props','report')
    graph.add_edge('report',END)
    return graph.compile()


async def run(sports: list[str], mode: str, daily_credit_limit: int):
    if not sports or len(sports)!=len(set(sports)) or any(s not in ('nba','nfl') for s in sports) or mode not in MODES or daily_credit_limit<1:
        raise ValueError('Invalid pipeline request')
    return (await create_daily_graph().ainvoke(dict(sports=sports,mode=mode,daily_credit_limit=daily_credit_limit)))['report']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sport',choices=['nba','nfl','both'],default='both')
    parser.add_argument('--mode',choices=MODES,default='daily')
    parser.add_argument('--daily-credit-limit',type=int,default=25)
    args=parser.parse_args()
    try:
        report=asyncio.run(run(['nfl','nba'] if args.sport=='both' else [args.sport],args.mode,args.daily_credit_limit))
        print(json.dumps(report))
        # Degraded provider coverage must remain visible as a failed scheduled run.
        if report['status'] not in ('complete','observed'):
            raise SystemExit(2)
    except Exception as exc:
        raise SystemExit(f'Daily pipeline unavailable ({type(exc).__name__})') from None


if __name__=='__main__':
    main()
