"""Read-only PrizePicks projections; never manufacture single-pick odds or entry payouts."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Literal

import httpx
from pydantic import AwareDatetime, BaseModel, Field, ValidationError

from sportsbet.ingestion.archive import write_archive
from sportsbet.ingestion.provenance import row_sha256

SOURCE = 'https://api.prizepicks.com/projections'
LEAGUES = {'nba': 7, 'nfl': 9}


class PrizePicksUnavailable(RuntimeError):
    """A projection request failed with a safe public reason."""

    def __init__(self, reason: str):
        if reason not in {'access_denied','rate_limited','upstream_unavailable','request_rejected'}:
            raise ValueError('Invalid public provider failure reason')
        super().__init__('Projection source unavailable')
        self.reason = reason


def _failure_reason(status_code: int) -> str:
    if status_code in (401,403):
        return 'access_denied'
    if status_code == 429:
        return 'rate_limited'
    if 500 <= status_code <= 599:
        return 'upstream_unavailable'
    return 'request_rejected'


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
    source_provider: Literal['prizepicks']
    source_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    source_record_sha256: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    source_observed_at: AwareDatetime


def provider_payload_sha256(data: dict) -> str:
    """Hash the archived JSON value so its source commitment is replayable."""
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def projection_record_sha256(projection: Projection | dict) -> str:
    """Hash every normalized field needed to authenticate one projection."""
    projection = Projection.model_validate(projection)
    if projection.source_provider != 'prizepicks' or not projection.source_sha256:
        raise ValueError('Projection source evidence is incomplete')
    return row_sha256(dict(provider=projection.source_provider,
        batch_sha256=projection.source_sha256, projection_id=projection.projection_id,
        player_id=projection.player_id, player_name=projection.player_name,
        game_id=projection.game_id, stat_type=projection.stat_type, line=projection.line,
        starts_at=projection.starts_at, tier=projection.tier,
        description=projection.description, provider_status=projection.provider_status,
        observed_at=projection.source_observed_at))


def parse_projections(data: dict, observed_at: datetime) -> tuple[list[dict], int]:
    source_sha256 = provider_payload_sha256(data)
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
                provider_status=attributes.get('status'), source_provider='prizepicks',
                source_sha256=source_sha256, source_observed_at=observed_at)
        except (KeyError, TypeError, ValidationError):
            skipped += 1
            continue
        if projection.projection_id in seen:
            raise ValueError('Duplicate projection identity')
        seen.add(projection.projection_id)
        projection = projection.model_copy(update={
            'source_record_sha256': projection_record_sha256(projection)})
        projections.append(projection.model_dump(mode='json'))
    return projections, skipped


async def capture(sport: str, output: Path | None = None):
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        response = await client.get(SOURCE, params={'league_id':LEAGUES[sport], 'per_page':500, 'single_stat':'true'})
        if response.status_code != 200:
            raise PrizePicksUnavailable(_failure_reason(response.status_code))
        data = response.json()
    captured_at = datetime.now(timezone.utc)
    projections, skipped = parse_projections(data, captured_at)
    report = dict(provider='prizepicks', sport=sport, captured_at=captured_at.isoformat(),
        source_url=SOURCE, source_sha256=provider_payload_sha256(data),
        source_encoding='canonical-json-v1', raw=data,
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
