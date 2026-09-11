"""Read-only PrizePicks projections; never manufacture single-pick odds or entry payouts."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx
from pydantic import AwareDatetime, BaseModel, Field, ValidationError

from sportsbet.ingestion.archive import write_archive

SOURCE = 'https://api.prizepicks.com/projections'
LEAGUES = {'nba': 7, 'nfl': 9}


class Projection(BaseModel):
    projection_id: str = Field(min_length=1)
    player_id: str = Field(min_length=1)
    player_name: str = Field(min_length=1)
    game_id: str | None = None
    stat_type: str = Field(min_length=1)
    line: Decimal = Field(ge=0, allow_inf_nan=False)
    starts_at: AwareDatetime
    tier: str | None = None
    description: str | None = None
    provider_status: str | None = None


def parse_projections(data: dict) -> tuple[list[dict], int]:
    players = {str(item['id']): item['attributes'] for item in data['included'] if item.get('type') == 'new_player'}
    projections, skipped, seen = [], 0, set()
    for item in data['data']:
        try:
            attributes = item['attributes']
            player_id = str(item['relationships']['new_player']['data']['id'])
            player = players[player_id]
            projection = Projection(projection_id=item['id'], player_id=player_id,
                player_name=player['name'], game_id=str(attributes['game_id']) if attributes.get('game_id') else None,
                stat_type=attributes['stat_type'], line=attributes['line_score'], starts_at=attributes['start_time'],
                tier=attributes.get('odds_type'), description=attributes.get('description'),
                provider_status=attributes.get('status'))
        except (KeyError, TypeError, ValidationError):
            skipped += 1
            continue
        if projection.projection_id in seen:
            raise ValueError('Duplicate projection identity')
        seen.add(projection.projection_id)
        projections.append(projection.model_dump(mode='json'))
    return projections, skipped


async def capture(sport: str, output: Path | None = None):
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        response = await client.get(SOURCE, params={'league_id':LEAGUES[sport], 'per_page':500, 'single_stat':'true'})
        if response.status_code != 200:
            raise RuntimeError(f'Projection source unavailable (HTTP {response.status_code})')
        data = response.json()
    projections, skipped = parse_projections(data)
    report = dict(provider='prizepicks', sport=sport, captured_at=datetime.now(timezone.utc).isoformat(),
        source_url=SOURCE, source_sha256=hashlib.sha256(response.content).hexdigest(), raw=data,
        projections=projections, skipped_count=skipped, partial_coverage=True,
        scope='One projection page only. Entry payouts, available directions, limits, and settlement rules must be verified separately.',
        entry_payouts=None, american_odds=None, execution_ready=False)
    write_archive(report, output, directory=Path('.local/prizepicks'))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sport', choices=LEAGUES, required=True)
    parser.add_argument('--output', type=Path, help='New archive file; existing evidence cannot be overwritten')
    args = parser.parse_args()
    try:
        report = asyncio.run(capture(args.sport, args.output))
        print(json.dumps(dict(projections=len(report['projections']), skipped=report['skipped_count'], execution_ready=False)))
    except Exception as exc:
        raise SystemExit(f'PrizePicks capture unavailable ({type(exc).__name__}); no prices or payouts inferred.') from None


if __name__ == '__main__':
    main()
