"""Authentication isolation and fixed-point order-book regression checks."""
import base64
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

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
async def test_reads_retry_transient_statuses_with_bounded_exponential_backoff(monkeypatch):
    from sportsbet.ingestion import kalshi
    statuses=iter((503,429,200));calls=[]
    def handle(request):
        calls.append(request)
        status=next(statuses)
        return httpx.Response(status,json={'markets':[]} if status==200 else {'error':'temporary'})
    sleep=AsyncMock();monkeypatch.setattr(kalshi.asyncio,'sleep',sleep)
    async with KalshiReader(transport=httpx.MockTransport(handle)) as reader:
        assert await reader._get('/markets') == {'markets':[]}
    assert len(calls)==3
    assert [call.args[0] for call in sleep.await_args_list]==[0.25,0.5]


@pytest.mark.asyncio
async def test_authenticated_retry_regenerates_request_headers(monkeypatch):
    from sportsbet.ingestion import kalshi
    observed=[];statuses=iter((503,200))
    def handle(request):
        observed.append(request.headers['X-Test-Signature'])
        return httpx.Response(next(statuses),json={'ok':True})
    sleep=AsyncMock();monkeypatch.setattr(kalshi.asyncio,'sleep',sleep)
    async with KalshiReader(transport=httpx.MockTransport(handle)) as reader:
        reader._headers=MagicMock(side_effect=[{'X-Test-Signature':'first'},
            {'X-Test-Signature':'second'}])
        assert await reader._get('/api_keys',authenticated=True) == {'ok':True}
        assert reader._headers.call_count==2
    assert observed==['first','second'] and sleep.await_count==1


@pytest.mark.asyncio
async def test_reads_do_not_retry_permanent_errors_and_bound_transport_retries(monkeypatch):
    from sportsbet.ingestion import kalshi
    sleep=AsyncMock();monkeypatch.setattr(kalshi.asyncio,'sleep',sleep)
    permanent=[]
    def reject(request):
        permanent.append(request)
        return httpx.Response(400,json={'error':'bad request'})
    async with KalshiReader(transport=httpx.MockTransport(reject)) as reader:
        with pytest.raises(RuntimeError,match='HTTP 400'):
            await reader._get('/markets')
    assert len(permanent)==1 and sleep.await_count==0

    attempts=[]
    def disconnect(request):
        attempts.append(request)
        raise httpx.ConnectError('provider unavailable',request=request)
    async with KalshiReader(transport=httpx.MockTransport(disconnect)) as reader:
        with pytest.raises(RuntimeError,match='transport'):
            await reader._get('/markets')
    assert len(attempts)==3 and sleep.await_count==2


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
    assert snapshot['same_contract_pair'] is None  # One empty side cannot be hedged.


@pytest.mark.asyncio
async def test_bulk_targets_use_repeated_validated_ids_without_authentication():
    ids=['10000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000002']
    def handle(request):
        assert request.url.path.endswith('/structured_targets')
        assert request.url.params.get_list('ids')==ids
        assert request.url.params['page_size']=='2'
        assert 'KALSHI-ACCESS-KEY' not in request.headers
        return httpx.Response(200,json={'structured_targets':[],'cursor':''})
    async with KalshiReader(transport=httpx.MockTransport(handle)) as reader:
        assert await reader.targets(ids)=={'structured_targets':[],'cursor':''}
        for invalid in ([],ids+ids[:1],['invalid']):
            with pytest.raises(ValueError):
                await reader.targets(invalid)


def test_repeated_captures_never_overwrite_prior_evidence(tmp_path, monkeypatch):
    import json
    from sportsbet.ingestion.kalshi import write_archive
    monkeypatch.chdir(tmp_path)
    first = write_archive({'capture': 1})
    second = write_archive({'capture': 2})
    assert first != second
    with pytest.raises(FileExistsError):
        write_archive({'capture': 3}, first)
    assert json.loads(first.read_text()) == {'capture': 1}
    assert json.loads(second.read_text()) == {'capture': 2}
