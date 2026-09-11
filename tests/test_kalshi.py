"""Authentication isolation and fixed-point order-book regression checks."""
import base64
from decimal import Decimal

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from sportsbet.ingestion.kalshi import KalshiReader, ask_levels, ticker_path


def test_asks_use_opposite_bids_without_losing_fractional_depth():
    book = {'orderbook_fp': {'yes_dollars': [['0.4200', '12.50']],
                            'no_dollars': [['0.5500', '3.25'], ['0.5701', '0.50']]}}
    assert ask_levels(book, 'yes') == [(Decimal('0.4299'), Decimal('0.50')),
                                       (Decimal('0.4500'), Decimal('3.25'))]
    assert ask_levels(book, 'no') == [(Decimal('0.5800'), Decimal('12.50'))]
    assert ask_levels({'orderbook_fp': {'no_dollars': None}}, 'yes') == []
    for price, size in [('NaN', '1'), ('0.5', '-1'), ('1', '2'), ('0.2', 'Infinity')]:
        with pytest.raises(ValueError):
            ask_levels({'orderbook_fp': {'no_dollars': [[price, size]]}}, 'yes')
    with pytest.raises(ValueError, match='Duplicate'):
        ask_levels({'orderbook_fp': {'no_dollars': [['.5', '1'], ['.50', '2']]}}, 'yes')
    with pytest.raises(KeyError):
        ask_levels({}, 'yes')  # Missing schema is not an empty market.
    for ticker in ['../api_keys', 'https://other.test', 'ABC?x=1', '']:
        with pytest.raises(ValueError):
            ticker_path(ticker)


@pytest.mark.asyncio
async def test_signed_get_is_verifiable_and_cannot_redirect_credentials(monkeypatch, tmp_path):
    from sportsbet.ingestion import kalshi

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_path = tmp_path / 'test.pem'
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    monkeypatch.setattr(kalshi.settings, 'kalshi_api_key_id', 'test-key')
    monkeypatch.setattr(kalshi.settings, 'kalshi_private_key_path', str(key_path))
    monkeypatch.setattr(kalshi.settings, 'kalshi_demo_api_key_id', None)
    monkeypatch.setattr(kalshi.settings, 'kalshi_demo_private_key_path', None)
    calls = []

    def handle(request):
        calls.append(request)
        assert request.method == 'GET'
        assert request.url.host == 'external-api.kalshi.com'
        if request.url.path.endswith('/api_keys'):
            message = (request.headers['KALSHI-ACCESS-TIMESTAMP'] + 'GET' + request.url.path).encode()
            key.public_key().verify(base64.b64decode(request.headers['KALSHI-ACCESS-SIGNATURE']),
                message, padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256())
            if request.url.query:
                return httpx.Response(302, headers={'Location': 'https://other.test/'})
            return httpx.Response(200, json={'api_keys': [{'api_key_id': 'test-key', 'scopes': ['read']}]})
        assert 'KALSHI-ACCESS-KEY' not in request.headers
        return httpx.Response(200, json={'markets': [], 'cursor': ''})

    transport = httpx.MockTransport(handle)
    async with KalshiReader(transport=transport) as reader:
        assert await reader.check_credentials() == {'authenticated': True, 'scopes': ['read']}
        assert (await reader.markets('KXNFLGAME'))['markets'] == []
        with pytest.raises(RuntimeError, match='HTTP 302'):
            await reader._get('/api_keys?probe=1', authenticated=True)
    assert len(calls) == 3
    async with KalshiReader(demo=True, transport=transport) as reader:
        with pytest.raises(ValueError, match='not configured'):
            await reader.check_credentials()
    assert len(calls) == 3  # Never fall back from demo to production credentials.


@pytest.mark.asyncio
async def test_snapshot_preserves_evidence_and_observation_interval():
    def handle(request):
        if request.url.path.endswith('/orderbook'):
            return httpx.Response(200, json={'orderbook_fp': {'yes_dollars': [], 'no_dollars': [['.6', '4']]}})
        return httpx.Response(200, json={'market': {'ticker': 'KXNFLGAME-TEST', 'status': 'active'}})

    async with KalshiReader(transport=httpx.MockTransport(handle)) as reader:
        snapshot = await reader.snapshot('KXNFLGAME-TEST')
    assert snapshot['yes_asks'] == [('0.4', '4')]
    assert snapshot['request_started_at'] <= snapshot['received_at']
    assert len(snapshot['sha256']) == 64
    assert 'quote_updated_at' not in snapshot
