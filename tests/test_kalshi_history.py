"""Real reader transport and deterministic historical-evidence validation."""
import copy
import json
import sys
from datetime import date

import httpx
import pytest

from sportsbet.ingestion.kalshi import KalshiReader
from sportsbet.ingestion import kalshi_history as history

TICKER = 'KXNBAPTS-26JUN13TEST-PLAYER-40'
PLAYER = '00000000-0000-0000-0000-000000000001'
TEAM = '00000000-0000-0000-0000-000000000002'
OTHER = '00000000-0000-0000-0000-000000000003'
GAME = '00000000-0000-0000-0000-000000000004'
START = '2026-06-14T00:30:00Z'
CUTOFF = int(history.timestamp(START).timestamp())-900


def source(historical=True):
    market = dict(ticker=TICKER, event_ticker='KXNBAPTS-26JUN13TEST',
        status='finalized', market_type='binary', notional_value_dollars='1.0000',
        open_time='2026-06-12T00:00:00Z', close_time='2026-06-14T03:59:00Z', settlement_ts='2026-06-14T04:00:00Z',
        settlement_value_dollars='0.0000', result='no', floor_strike=39.5, strike_type='structured',
        custom_strike=dict(basketball_player=PLAYER, basketball_team=TEAM))
    game = dict(id=GAME, type='basketball_game', start_date=START,
        related_event_tickers=[market['event_ticker']], details=dict(league='NBA',
        home_team_id=TEAM, away_team_id=OTHER, status='scheduled'))
    # The target's current statistics/team must never become historical outcomes/team assignments.
    target = dict(id=PLAYER, name='Fixture Player', type='basketball_player',
        details=dict(league='NBA', team_id=OTHER, player_stats=dict(points=999)))
    field = 'close' if historical else 'close_dollars'
    bar = dict(end_period_ts=CUTOFF, yes_bid={field: '0.1000'}, yes_ask={field: '0.1100'},
        price={field: None, 'previous': '0.5000'}, volume='0.00', open_interest='1000.00')
    return dict(request=dict(sport='nba', date='2026-06-13', tickers=[TICKER]),
        received_at='2026-09-11T00:00:00Z', milestone_pages=[dict(milestones=[game], cursor='')],
        market_pages=[dict(historical=historical, body=dict(markets=[market], cursor=''))],
        observations={TICKER: dict(target=target, candles=dict(ticker=TICKER, candlesticks=[bar]))})


@pytest.mark.parametrize('historical', [True, False])
async def test_actual_reader_collects_both_schemas_without_authentication(historical):
    evidence = source(historical)
    requests = []

    def handle(request):
        requests.append(request)
        assert request.method == 'GET' and request.url.host == 'external-api.kalshi.com'
        assert not any(key.lower().startswith('kalshi-access') for key in request.headers)
        path = request.url.path
        if path.endswith('/milestones'):
            assert request.url.params['minimum_start_date'] == '2026-06-13T00:00:00-04:00'
            return httpx.Response(200, json=evidence['milestone_pages'][0])
        if path.endswith('/markets'):
            assert request.url.params['tickers'] == TICKER
            body = evidence['market_pages'][0]['body'] if ('/historical/' in path) == historical else dict(markets=[], cursor='')
            return httpx.Response(200, json=body)
        if '/structured_targets/' in path:
            return httpx.Response(200, json={'structured_target': evidence['observations'][TICKER]['target']})
        assert path.endswith('/'+TICKER+'/candlesticks')
        assert ('/historical/' in path) == historical
        assert dict(request.url.params) == dict(start_ts=str(CUTOFF-3600), end_ts=str(CUTOFF), period_interval='1')
        return httpx.Response(200, json=evidence['observations'][TICKER]['candles'])

    async with KalshiReader(transport=httpx.MockTransport(handle)) as reader:
        archive = await history.collect(reader, 'nba', date(2026, 6, 13), [TICKER])
    assert len(requests) == 5
    assert archive['dataset'] == history.normalize(archive['evidence'])
    row, = archive['dataset']['records']
    assert row['yes_ask_dollars'] == '0.1100' and row['cutoff_age_seconds'] == 0
    assert row['executable_depth'] is None and row['fee_adjusted_profit'] is None
    assert row['execution_ready'] is False and 'actual_value' not in row
    assert archive['dataset']['roi'] is None


@pytest.mark.parametrize('mutation', ['late_open', 'stale', 'null', 'future', 'duplicate', 'unsorted',
    'nan', 'crossed', 'cents', 'zero_ask', 'zero_bid', 'early_close', 'conflicting_result',
    'wrong_market', 'wrong_player', 'wrong_game', 'wrong_day',
    'wrong_team', 'ambiguous_game', 'conflicting_game', 'discovery_cursor', 'market_cursor', 'settlement_future'])
def test_exclusions_fail_closed(mutation):
    evidence = source()
    market = evidence['market_pages'][0]['body']['markets'][0]
    game = evidence['milestone_pages'][0]['milestones'][0]
    observation = evidence['observations'][TICKER]
    bars = observation['candles']['candlesticks']
    if mutation == 'late_open': market['open_time'] = START
    elif mutation == 'stale': bars[0]['end_period_ts'] -= 120
    elif mutation == 'null': bars[0]['yes_ask']['close'] = None
    elif mutation == 'future': bars[0]['end_period_ts'] += 60
    elif mutation == 'duplicate': bars.append(copy.deepcopy(bars[0]))
    elif mutation == 'unsorted': bars.append(dict(copy.deepcopy(bars[0]), end_period_ts=CUTOFF-60))
    elif mutation == 'nan': bars[0]['yes_bid']['close'] = 'NaN'
    elif mutation == 'crossed': bars[0]['yes_bid']['close'] = '0.2'
    elif mutation == 'cents': bars[0]['yes_ask']['close'] = '11'
    elif mutation == 'zero_ask': bars[0]['yes_ask']['close'] = '0'
    elif mutation == 'zero_bid': bars[0]['yes_bid']['close'] = '0'
    elif mutation == 'early_close': market['close_time'] = '2026-06-13T00:00:00Z'
    elif mutation == 'conflicting_result': market['result'] = 'yes'
    elif mutation == 'wrong_market': observation['candles']['ticker'] = 'OTHER'
    elif mutation == 'wrong_player': observation['target']['id'] = OTHER
    elif mutation == 'wrong_game': game['related_event_tickers'] = []
    elif mutation == 'wrong_day': game['start_date'] = '2026-06-15T00:30:00Z'
    elif mutation == 'wrong_team': market['custom_strike']['basketball_team'] = PLAYER
    elif mutation == 'ambiguous_game': evidence['milestone_pages'][0]['milestones'].append(dict(game, id=OTHER))
    elif mutation == 'conflicting_game': evidence['milestone_pages'][0]['milestones'].append(dict(game, start_date=START.replace('30', '31')))
    elif mutation == 'discovery_cursor': evidence['milestone_pages'][0]['cursor'] = 'more'
    elif mutation == 'market_cursor': evidence['market_pages'][0]['body']['cursor'] = 'more'
    elif mutation == 'settlement_future': market['settlement_ts'] = '2027-01-01T00:00:00Z'
    result = history.normalize(evidence)
    assert not result['records'] and len(result['exclusions']) == 1 and result['status'] == 'incomplete'


async def test_provider_failure_is_archived_without_exception_text_and_discovery_is_bounded():
    calls = []

    def handle(request):
        calls.append(request)
        if request.url.path.endswith('/milestones'):
            return httpx.Response(200, json=dict(milestones=[], cursor='repeated-cursor'))
        raise RuntimeError('private credential must not appear')

    async with KalshiReader(transport=httpx.MockTransport(handle)) as reader:
        archive = await history.collect(reader, 'nba', date(2026, 6, 13), [TICKER])
    assert len(calls) == 4
    assert archive['dataset']['status'] == 'incomplete'
    assert archive['evidence']['discovery_error'] == 'RuntimeError'
    assert 'private credential' not in json.dumps(archive)


def test_replay_detects_modified_summary_and_preserves_file(monkeypatch, tmp_path, capsys):
    evidence = source()
    archive = dict(evidence=evidence, dataset=history.normalize(evidence))
    path = tmp_path/'archive.json'
    for matches in (True, False):
        if not matches:
            archive['dataset']['records'][0]['yes_ask_dollars'] = '0.0100'
        path.write_text(json.dumps(archive), encoding='utf-8')
        before = path.read_bytes()
        monkeypatch.setattr(sys, 'argv', ['history', '--replay', str(path)])
        with pytest.raises(SystemExit) as error:
            history.main()
        assert error.value.code == (0 if matches else 2)
        assert json.loads(capsys.readouterr().out)['matches'] is matches
        assert path.read_bytes() == before
