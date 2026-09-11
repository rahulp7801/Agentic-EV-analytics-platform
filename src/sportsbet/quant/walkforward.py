"""Run the actual graph against archived outcomes at an explicit research threshold.

No sportsbook line or price is inferred. This checks forecast calibration, not ROI.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path

from sportsbet.config import settings
from sportsbet.db.connection import create_async_pool
from sportsbet.graph.graph import create_graph
from sportsbet.ingestion.espn_history import STATS
from sportsbet.prop.agents import make_prop_quant_agent
from sportsbet.prop.arbitrage import make_prop_arbitrage_agent
from sportsbet.prop.nba_agents import make_nba_quant_agent
from sportsbet.quant.backtest import calibration_metrics


async def evaluate(dataset: dict, prop: str, threshold: Decimal) -> dict:
    sport = dataset['sport']
    if dataset.get('kind') != 'final_player_stats' or sport not in STATS or prop not in STATS[sport].values():
        raise ValueError('Unsupported outcome dataset or prop')
    if not threshold.is_finite() or threshold < 0:
        raise ValueError('Research threshold must be finite and nonnegative')
    if settings.experimental_probability_adjustments:
        raise ValueError('Historical context adjustments are not point-in-time verified')
    pool = await create_async_pool()
    graph = create_graph(nba_quant_node=make_nba_quant_agent(pool),
        prop_quant_node=make_prop_quant_agent(pool), prop_arbitrage_node=make_prop_arbitrage_agent(sport=sport))
    scored, skipped, predictions, identities = [], Counter(), [], {}
    rows = [r for r in dataset['records'] if r['prop_type'] == prop]
    seen = set()
    try:
        for row in sorted(rows, key=lambda r: (r['game_date'], r['event_id'], r['player_id'])):
            identity = (row['event_id'], row['player_id'])
            if identity in seen:
                raise ValueError('Duplicate outcome identity')
            seen.add(identity)
            target = date.fromisoformat(row['game_date'])
            if target >= date.today():
                raise ValueError('Historical validation requires completed past dates')
            name = row['player_name']
            if name not in identities:
                table = 'nba_player_gamelogs' if sport == 'nba' else 'player_stats'
                async with pool.acquire() as conn:
                    identities[name] = await conn.fetch(f'SELECT DISTINCT player_id FROM {table} WHERE LOWER(player_name)=LOWER($1)', name)
            players = identities[name]
            if len(players) != 1:
                skipped['unknown_or_ambiguous_player'] += 1
                continue
            season = target.year if target.month >= (10 if sport == 'nba' else 9) else target.year-1
            state = await graph.ainvoke(dict(session_id='historical-forecast',
                request_type='nba_prop_analysis' if sport == 'nba' else 'prop_analysis',
                game_id=row['event_id'], season=season-2, week=1, sport=sport,
                receiver_gsis_id=str(players[0]['player_id']), player_name=name,
                prop_type=prop, prop_line=threshold, prop_side='over',
                as_of_date=target, last_n_games=40, player_prop_snapshots=[]))
            estimate = state.get('nba_prop_result' if sport == 'nba' else 'prop_result')
            if not estimate or estimate.true_probability is None or estimate.sample_size < 20:
                skipped['missing_or_small_sample'] += 1
                continue
            actual = Decimal(str(row['actual_value']))
            outcome = 'push' if actual == threshold else bool(actual > threshold)
            p, push = float(estimate.true_probability), float(estimate.push_probability)
            if type(outcome) is bool and push < 1:
                predictions.append((p/(1-push), int(outcome)))
            scored.append(row | dict(model_player_id=str(players[0]['player_id']),
                research_threshold=str(threshold), model_probability=p, push_probability=push,
                sample_size=estimate.sample_size, outcome=outcome))
    finally:
        await pool.close()
    return dict(sport=sport, prop_type=prop, research_threshold=str(threshold), model_version='empirical-v2',
        candidate_count=len(rows), evaluated_count=len(scored), skipped=dict(skipped),
        **calibration_metrics(predictions),
        baseline_50_brier=0.25 if predictions else None, roi=None, clv=None,
        records=scored, limitations=[
            'Fixed user-specified research threshold, not a historical sportsbook line; no priced betting result.',
            'Actual LangGraph quant nodes, exclusive game-date cutoff, last 40 games, minimum 20 observations.',
            'Participating-player outcome cohort; missing identities and small samples are reported, not filled.',
            'Historical stats include later provider corrections. No historical injury/roster adjustment.',
            'Multiple players share games; samples are not independent. Small pilot results do not establish an edge.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--prop', required=True)
    parser.add_argument('--threshold', type=Decimal, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.dataset.read_bytes()
    report = asyncio.run(evaluate(json.loads(raw), args.prop, args.threshold))
    report['dataset_sha256'] = hashlib.sha256(raw).hexdigest()
    # Fingerprint the code actually evaluated, including uncommitted fixes.
    model_source = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted(model_source.rglob('*.py')):
        digest.update(path.relative_to(model_source).as_posix().encode())
        digest.update(path.read_bytes())
    report['source_code_sha256'] = digest.hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k != 'records'}, indent=2, allow_nan=False))
    if not report['calibration_count']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
