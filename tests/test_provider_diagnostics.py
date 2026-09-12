"""Provider failures must not copy HTTP diagnostics into public logs."""
from unittest.mock import AsyncMock

import httpx
import pytest
from structlog.testing import capture_logs

from sportsbet.ingestion import balldontlie, sleeper
from sportsbet.ingestion.free_odds import ESPNPropsPoller

CANARY = 'private-provider-diagnostic-canary'


def failure():
    request = httpx.Request('GET', 'https://example.invalid/?token=' + CANARY)
    return httpx.HTTPStatusError(CANARY, request=request,
        response=httpx.Response(503, request=request))


@pytest.mark.parametrize('provider', ['averages', 'games', 'stats', 'injuries', 'espn'])
async def test_failed_provider_diagnostics_are_sanitized(monkeypatch, provider):
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get.side_effect = failure()
    monkeypatch.setattr(balldontlie.httpx, 'AsyncClient', lambda **kwargs: client)
    monkeypatch.setattr(sleeper, '_AsyncClient', lambda **kwargs: client)
    calls = {
        'averages': lambda: balldontlie.fetch_player_season_averages(1, 2025),
        'games': lambda: balldontlie.fetch_team_recent_games(1, 2025),
        'stats': lambda: balldontlie.fetch_player_game_logs(1, 2025),
        'injuries': lambda: sleeper.fetch_sleeper_team_injuries('nfl', 'KC'),
    }
    healthy = {'id': 'healthy-event', 'bookmakers': []}
    with capture_logs() as logs:
        if provider == 'espn':
            client.get.side_effect = None
            client.get.return_value = httpx.Response(200,
                request=httpx.Request('GET', 'https://example.invalid/scoreboard'),
                json={'events': [{'id': 'failed-event'}, {'id': 'healthy-event'}]})
            async with ESPNPropsPoller() as poller:
                monkeypatch.setattr(poller, '_fetch_event_props',
                    AsyncMock(side_effect=[failure(), healthy]))
                result = await poller.fetch_player_props('nba')
            assert result == [healthy]
        else:
            result = await calls[provider]()
            assert result == (None if provider == 'averages' else [])
    warnings = [row for row in logs if row['log_level'] == 'warning']
    assert len(warnings) == 1
    assert CANARY not in repr(logs)
    assert warnings[0]['error_type'] == 'HTTPStatusError'
    assert not any(row.get('exc_info') or 'exception' in row for row in logs)
