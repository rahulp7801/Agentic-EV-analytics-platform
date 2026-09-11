"""Analyze explicit payoff candidates or replay archived inputs through LangGraph."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from sportsbet.arbitrage.portfolio import MarketAnalysisRequest
from sportsbet.graph.graph import create_graph


class Settlement(BaseModel):
    model_config = ConfigDict(extra='forbid')
    state: str
    source_ref: str = Field(min_length=1)
    resolved_at: AwareDatetime


async def analyze(request: MarketAnalysisRequest, settlements: dict | None = None) -> dict:
    # This is the production graph route, not a separate backtest strategy.
    output = await create_graph().ainvoke(dict(session_id=str(uuid4()),
        request_type='market_analysis', market_request=request.model_dump()))
    report = output['market_report']
    if settlements is not None:
        candidates = {c.candidate_id: c for c in request.candidates}
        if set(settlements) - set(candidates):
            raise ValueError('Unknown settlement candidate')
        parsed = {key: Settlement.model_validate(value) for key, value in settlements.items()}
        for key, value in parsed.items():
            if value.state not in candidates[key].states or value.resolved_at <= request.as_of:
                raise ValueError('Settlement must identify a supplied state resolved after the observation')
            if value.resolved_at > datetime.now(timezone.utc):
                raise ValueError('Cannot replay a future settlement')
        for result in report['results']:
            settlement = parsed.get(result['candidate_id'])
            result['settlement'] = settlement.model_dump(mode='json') if settlement else None
            result['simulated_profit_bound'] = (
                result['state_profits'][settlement.state]
                if settlement and result['status'] == 'scenario_edge' else None)
        report['replay_scope'] = ('Per-candidate payoff replay using supplied settlements and fee bounds; '
            'no queue position, fills, cross-candidate capital reuse, or realized ROI is inferred.')
    source_root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(source_root.rglob('*.py')):
        digest.update(path.relative_to(source_root).as_posix().encode())
        digest.update(path.read_bytes())
    report['source_code_sha256'] = digest.hexdigest()
    report['realized_roi'] = None
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True, help='MarketAnalysisRequest JSON with explicit payout states')
    parser.add_argument('--output', type=Path, default=Path('.local/market-analysis/report.json'))
    parser.add_argument('--replay', action='store_true', help='Use archived as_of instead of the current clock')
    parser.add_argument('--settlements', type=Path, help='Candidate IDs to state/source_ref/resolved_at records; replay only')
    args = parser.parse_args()
    if args.settlements and not args.replay:
        parser.error('--settlements requires --replay')
    try:
        raw = args.input.read_bytes()
        data = json.loads(raw)
        if not args.replay:
            data['as_of'] = datetime.now(timezone.utc).isoformat()
        request = MarketAnalysisRequest.model_validate(data)
        if request.as_of > datetime.now(timezone.utc):
            raise ValueError('Cannot replay future observations')
        settlement_raw = args.settlements.read_bytes() if args.settlements else None
        # CLI owns this process: keep graph/library diagnostics off the JSON channel.
        with redirect_stdout(sys.stderr):
            report = asyncio.run(analyze(request, json.loads(settlement_raw) if settlement_raw else None))
        report.update(mode='replay' if args.replay else 'observation',
            input_file_sha256=hashlib.sha256(raw).hexdigest(),
            settlements_sha256=hashlib.sha256(settlement_raw).hexdigest() if settlement_raw else None)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(dict(candidates=len(report['results']),mode=report['mode'],
            status=report['status'],failed_count=report['failed_count'],execution_ready=False)))
        if report['status']!='complete':
            raise SystemExit(2)
    except Exception as exc:
        # Avoid echoing source documents, account identifiers, or file contents.
        raise SystemExit(f'Market analysis failed ({type(exc).__name__})') from None


if __name__ == '__main__':
    main()
