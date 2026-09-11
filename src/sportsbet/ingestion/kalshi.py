"""Read-only Kalshi market adapter. No order-placement capability is exposed."""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from sportsbet.config import settings
from sportsbet.ingestion.archive import write_archive


def ticker_path(ticker: str) -> str:
    if not re.fullmatch(r'[A-Z0-9_-]{1,150}', ticker):
        raise ValueError('Invalid Kalshi ticker')
    return ticker


def ask_levels(orderbook: dict, side: str) -> list[tuple[Decimal, Decimal]]:
    """YES asks come from NO bids and vice versa; never double-count both views."""
    if side not in ('yes', 'no'):
        raise ValueError('Side must be yes or no')
    key = 'no_dollars' if side == 'yes' else 'yes_dollars'
    bids = orderbook['orderbook_fp'][key] or []
    levels = []
    seen = set()
    for raw_price, raw_count in bids:
        price, count = Decimal(raw_price), Decimal(raw_count)
        if not price.is_finite() or not 0 < price < 1 or not count.is_finite() or count <= 0:
            raise ValueError('Invalid Kalshi price or depth')
        if price in seen:
            raise ValueError('Duplicate order-book price level')
        seen.add(price)
        levels.append((1-price, count))
    return sorted(levels)


class KalshiReader:
    def __init__(self, *, demo: bool = False, transport=None):
        host = 'external-api.demo.kalshi.co' if demo else 'external-api.kalshi.com'
        self._client = httpx.AsyncClient(base_url=f'https://{host}', timeout=15,
            follow_redirects=False, transport=transport)
        self._key_id = settings.kalshi_demo_api_key_id if demo else settings.kalshi_api_key_id
        self._key_path = settings.kalshi_demo_private_key_path if demo else settings.kalshi_private_key_path
        self._private_key = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self._client.aclose()

    def _headers(self, path: str) -> dict[str, str]:
        if not self._key_id or not self._key_path:
            raise ValueError('Kalshi credentials are not configured for this environment')
        if self._private_key is None:
            key = serialization.load_pem_private_key(Path(self._key_path).read_bytes(), password=None)
            if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
                raise ValueError('Kalshi requires an RSA private key of at least2048 bits')
            self._private_key = key
        timestamp = str(time.time_ns() // 1_000_000)
        message = (timestamp + 'GET' + path.split('?',1)[0]).encode()
        signature = self._private_key.sign(message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256())
        return {'KALSHI-ACCESS-KEY':self._key_id, 'KALSHI-ACCESS-TIMESTAMP':timestamp,
            'KALSHI-ACCESS-SIGNATURE':base64.b64encode(signature).decode()}

    async def _get(self, path: str, *, params=None, authenticated=False) -> dict:
        path = '/trade-api/v2' + path
        headers = self._headers(path) if authenticated else {}
        # Only GET; requests cannot redirect credentials to another host.
        response = await self._client.get(path, params=params, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f'Kalshi read failed (HTTP {response.status_code})')
        return response.json()

    async def check_credentials(self) -> dict:
        data = await self._get('/api_keys', authenticated=True)
        matches = [k for k in data['api_keys'] if k['api_key_id'] == self._key_id]
        if len(matches) != 1:
            raise ValueError('Configured key was not returned by Kalshi')
        return dict(authenticated=True, scopes=matches[0].get('scopes', []))

    async def markets(self, series: str, *, limit: int = 100, cursor: str | None = None) -> dict:
        if not 1 <= limit <= 1000:
            raise ValueError('Market page limit must be1..1000')
        params = dict(series_ticker=ticker_path(series), status='open', limit=limit)
        if cursor:
            params['cursor'] = cursor
        return await self._get('/markets', params=params)

    async def series(self, series: str) -> dict:
        return (await self._get('/series/'+ticker_path(series)))['series']

    async def milestones(self, sport: str, start: datetime, *, limit: int = 100) -> dict:
        if sport not in ('nba', 'nfl') or start.tzinfo is None or not 1 <= limit <= 500:
            raise ValueError('Invalid milestone query')
        return await self._get('/milestones', params=dict(limit=limit, category='Sports',
            # Actual API accepts NFL/NBA; the prose examples returned empty NFL data.
            competition=sport.upper(),
            minimum_start_date=start.isoformat()))

    async def event(self, ticker: str) -> dict:
        return await self._get('/events/'+ticker_path(ticker))

    async def target(self, target_id: str) -> dict:
        return (await self._get('/structured_targets/'+str(UUID(target_id))))['structured_target']

    async def snapshot(self, ticker: str) -> dict:
        ticker = ticker_path(ticker)
        started = datetime.now(timezone.utc)
        market, book = await asyncio.gather(self._get('/markets/'+ticker), self._get('/markets/'+ticker+'/orderbook'))
        received = datetime.now(timezone.utc)
        yes_asks, no_asks = ask_levels(book, 'yes'), ask_levels(book, 'no')
        pair = None
        if yes_asks and no_asks:
            pair = dict(ask_cost=str(yes_asks[0][0]+no_asks[0][0]),
                gross_gap_to_one_dollar=str(1-yes_asks[0][0]-no_asks[0][0]),
                displayed_size=str(min(yes_asks[0][1], no_asks[0][1])),
                fee_adjusted_profit=None, execution_ready=False)
        # This is an observation interval, not an invented provider quote-update time.
        return dict(venue='kalshi', request_started_at=started.isoformat(), received_at=received.isoformat(),
            market=market['market'], orderbook=book,
            yes_asks=[(str(p),str(n)) for p,n in yes_asks],
            no_asks=[(str(p),str(n)) for p,n in no_asks],
            same_contract_pair=pair,
            sha256=hashlib.sha256(json.dumps(dict(market=market,orderbook=book),sort_keys=True).encode()).hexdigest())


async def run(series: str, limit: int, output: Path | None, demo: bool, check_auth: bool):
    async with KalshiReader(demo=demo) as reader:
        if check_auth:
            print(json.dumps(await reader.check_credentials()))
        metadata = await reader.series(series)
        page = await reader.markets(series, limit=limit)
        snapshots = []
        # Bounded read-only sampling; the cursor explicitly records incomplete coverage.
        for market in page['markets']:
            snapshots.append(await reader.snapshot(market['ticker']))
        report = dict(series=series, environment='demo' if demo else 'production',
            series_metadata=metadata, snapshots=snapshots, next_cursor=page.get('cursor'),
            scope='Market observations only; no arbitrage, fill or profit is inferred.')
        write_archive(report, output, directory=Path('.local/kalshi'))
        print(json.dumps(dict(markets=len(snapshots),partial_coverage=bool(page.get('cursor')),scope=report['scope'])))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--series', required=True)
    parser.add_argument('--limit', type=int, default=5)
    parser.add_argument('--output', type=Path, help='New archive path; default is a unique file under .local/kalshi/')
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--check-auth', action='store_true')
    args = parser.parse_args()
    try:
        asyncio.run(run(args.series,args.limit,args.output,args.demo,args.check_auth))
    except Exception as exc:
        # Library exceptions can contain request headers, paths or key material.
        raise SystemExit(f'Kalshi read failed ({type(exc).__name__}); no orders were submitted.') from None


if __name__ == '__main__':
    main()
