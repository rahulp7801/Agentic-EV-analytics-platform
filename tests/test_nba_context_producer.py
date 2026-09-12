"""TDD tests for make_nba_context_signals_producer — Phase 20 Plan 01.

These tests define the exact contract that nba_context_producer.py must satisfy.

Key invariants tested:
- Happy path: player has gamelog rows, rest_days and is_home computed correctly
- Cold DB (no gamelog rows): returns league-average NBAContextSignals
- Back-to-back not triggered: last game 3 days ago -> rest_days=2
- Invalid player_id (empty string): returns league-average defaults without DB query
- Decimal wrapping: opponent_def_rating is Decimal instance, not float
- No opponent stats (avg_pts_per_game is None): falls back to LEAGUE_AVG_DEF_RATING

MagicMock pool pattern (Phase 4 locked decision):
    conn = MagicMock()
    conn.fetchrow = AsyncMock(side_effect=[row1, row2])
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

asyncio_mode = "auto" in pyproject.toml — tests are bare async def, no decorator needed.
"""
import pytest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, AsyncMock

from sportsbet.prop.nba_context_producer import make_nba_context_signals_producer
from sportsbet.graph.models import NBAContextSignals
from sportsbet.prop.nba_executor import LEAGUE_AVG_DEF_RATING, LEAGUE_AVG_PACE


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_mock_pool(fetchrow_side_effects: list):
    """Create a MagicMock asyncpg pool (Phase 4 locked decision: MagicMock not AsyncMock).

    Each call to conn.fetchrow() consumes the next item from fetchrow_side_effects.
    Use None to simulate no rows returned (empty gamelog).
    """
    conn = MagicMock()
    conn.fetchrow = AsyncMock(side_effect=fetchrow_side_effects)
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    return pool


def _make_state(
    receiver_gsis_id: str = "2544",
    season: int = 2024,
    home_team: str = "LAL",
    away_team: str = "BOS",
) -> dict:
    """Return a GraphState-like dict for testing."""
    return {
        "receiver_gsis_id": receiver_gsis_id,
        "season": season,
        "home_team": home_team,
        "away_team": away_team,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_happy_path_back_to_back():
    """Test 1: player has gamelog rows, last game was yesterday -> rest_days=0 (B2B).

    target_date = date(2025, 1, 15), last_game_date = date(2025, 1, 14).
    Formula: max(0, (1 day).days - 1) = 0.
    Player's team is LAL (home_team), so is_home=True.
    opponent_def_rating is Decimal in [90, 140].
    """
    target_date = date(2025, 1, 15)
    last_game_date = date(2025, 1, 14)

    # fetchrow call 1: gamelog row with team_abbreviation and game_date
    row1 = {"team_abbreviation": "LAL", "game_date": last_game_date}
    # fetchrow call 2: opponent stats (BOS is away_team -> opponent)
    row2 = {"avg_pts_per_game": 8.0}  # neutral -> def_rating stays ~115.0

    pool = make_mock_pool([row1, row2])
    state = _make_state(receiver_gsis_id="2544", home_team="LAL", away_team="BOS")
    producer = make_nba_context_signals_producer(pool, target_date=target_date)

    result = await producer(state)

    signals: NBAContextSignals = result["nba_context_signals"]
    assert isinstance(signals, NBAContextSignals)
    assert signals.rest_days == 0, f"Expected B2B rest_days=0, got {signals.rest_days}"
    assert signals.is_home is True, "Player's team is home_team -> is_home=True"
    assert isinstance(signals.opponent_def_rating, Decimal)
    assert Decimal("90") <= signals.opponent_def_rating <= Decimal("140")
    assert signals.pace_factor == LEAGUE_AVG_PACE


async def test_provider_full_names_are_normalized_for_following_quant_node():
    pool=make_mock_pool([{'team_abbreviation':'BOS','game_date':date(2025,1,14)}])
    producer=make_nba_context_signals_producer(pool,target_date=date(2025,1,15))
    result=await producer(_make_state(home_team='Boston Celtics',away_team='Los Angeles Lakers'))
    assert result['home_team']=='BOS' and result['away_team']=='LAL'
    assert result['nba_context_signals'].is_home is True


async def test_unknown_provider_team_identity_fails_closed():
    producer=make_nba_context_signals_producer(make_mock_pool([]),target_date=date(2025,1,15))
    with pytest.raises(ValueError,match='Unknown NBA team identity'):
        await producer(_make_state(home_team='Unknown Team'))


async def test_cold_db_no_gamelog_rows():
    """Test 2: cold DB — fetchrow returns None (no gamelog rows for player/season).

    Should return NBAContextSignals with league-average defaults.
    rest_days=1 (default), opponent_def_rating=LEAGUE_AVG_DEF_RATING,
    pace_factor=LEAGUE_AVG_PACE, is_home=False (default when no DB data).
    """
    pool = make_mock_pool([None])  # Only one fetchrow call; returns None
    state = _make_state(receiver_gsis_id="2544")
    producer = make_nba_context_signals_producer(pool, target_date=date(2025, 1, 15))

    result = await producer(state)

    signals: NBAContextSignals = result["nba_context_signals"]
    assert isinstance(signals, NBAContextSignals)
    assert signals.rest_days == 1, f"Cold DB default rest_days should be 1, got {signals.rest_days}"
    assert signals.opponent_def_rating == LEAGUE_AVG_DEF_RATING
    assert signals.pace_factor == LEAGUE_AVG_PACE
    assert signals.is_home is False


async def test_not_back_to_back_three_days_ago():
    """Test 3: last game 3 days ago -> rest_days=2.

    target_date = date(2025, 1, 15), last_game_date = date(2025, 1, 12).
    Formula: max(0, (15-12).days - 1) = max(0, 3 - 1) = 2.
    """
    target_date = date(2025, 1, 15)
    last_game_date = date(2025, 1, 12)  # 3 days ago

    row1 = {"team_abbreviation": "LAL", "game_date": last_game_date}
    row2 = {"avg_pts_per_game": 8.0}

    pool = make_mock_pool([row1, row2])
    state = _make_state(receiver_gsis_id="2544")
    producer = make_nba_context_signals_producer(pool, target_date=target_date)

    result = await producer(state)

    signals: NBAContextSignals = result["nba_context_signals"]
    assert signals.rest_days == 2, f"Expected rest_days=2, got {signals.rest_days}"


async def test_invalid_player_id_empty_string():
    """Test 4: invalid player_id (empty string) -> returns league-average defaults, no DB query.

    When receiver_gsis_id is empty string, producer should short-circuit and return
    NBAContextSignals with league-average defaults without touching the DB.
    """
    # Pool should NOT be called — pass a pool that would fail if called
    pool = make_mock_pool([])  # No side effects; any call would raise StopAsyncIteration
    state = _make_state(receiver_gsis_id="")  # Empty string -> invalid
    producer = make_nba_context_signals_producer(pool, target_date=date(2025, 1, 15))

    result = await producer(state)

    signals: NBAContextSignals = result["nba_context_signals"]
    assert isinstance(signals, NBAContextSignals)
    assert signals.opponent_def_rating == LEAGUE_AVG_DEF_RATING
    assert signals.pace_factor == LEAGUE_AVG_PACE
    assert signals.rest_days == 1
    assert signals.is_home is False


async def test_decimal_wrapping_opponent_def_rating():
    """Defense stays neutral; offensive season averages must not adjust it."""
    target_date = date(2025, 1, 15)
    last_game_date = date(2025, 1, 14)

    row1 = {"team_abbreviation": "BOS", "game_date": last_game_date}
    row2 = {"avg_pts_per_game": 16.0}  # High -> normalized=230, clamped to 140

    pool = make_mock_pool([row1, row2])
    state = _make_state(
        receiver_gsis_id="2544",
        home_team="LAL",
        away_team="BOS",
    )
    producer = make_nba_context_signals_producer(pool, target_date=target_date)

    result = await producer(state)

    signals: NBAContextSignals = result["nba_context_signals"]
    assert isinstance(signals.opponent_def_rating, Decimal), (
        f"opponent_def_rating must be Decimal, got {type(signals.opponent_def_rating)}"
    )
    assert signals.opponent_def_rating == LEAGUE_AVG_DEF_RATING
    conn = pool.acquire.return_value.__aenter__.return_value
    assert conn.fetchrow.await_count == 1  # only pre-game history, no season aggregate


async def test_no_opponent_stats_falls_back_to_league_avg():
    """Test 6: avg_pts_per_game is None -> falls back to LEAGUE_AVG_DEF_RATING.

    Should not raise ZeroDivisionError or ValidationError.
    """
    target_date = date(2025, 1, 15)
    last_game_date = date(2025, 1, 14)

    row1 = {"team_abbreviation": "LAL", "game_date": last_game_date}
    row2 = {"avg_pts_per_game": None}  # No opponent stats

    pool = make_mock_pool([row1, row2])
    state = _make_state(receiver_gsis_id="2544", home_team="LAL", away_team="BOS")
    producer = make_nba_context_signals_producer(pool, target_date=target_date)

    result = await producer(state)

    signals: NBAContextSignals = result["nba_context_signals"]
    assert isinstance(signals, NBAContextSignals)
    assert signals.opponent_def_rating == LEAGUE_AVG_DEF_RATING, (
        f"Expected LEAGUE_AVG_DEF_RATING={LEAGUE_AVG_DEF_RATING}, got {signals.opponent_def_rating}"
    )
