"""Pydantic v2 agent I/O models for the sportsbet graph layer.

All models use ConfigDict(strict=True) — no coercion, no v1 class Config patterns.
Decimal (not float) is used for all probability and fraction values to preserve
precision through the Kelly Criterion calculation pipeline.

Design contract:
- Phase 3+ agent nodes receive typed inputs and return typed outputs via these models.
- Stub nodes in Plan 02 return static fixture instances — Phase 3 implements real logic.
- Zero LLM hallucination: every Decimal field is populated from DB or external API,
  never inferred by an LLM.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class QuantParams(BaseModel):
    """Input parameters for the Quant Agent's dynamic SQL query builder.

    Validated before any SQL executes — enforces stat domain and season range.
    stat_type is a Literal to prevent open-ended string injection into queries.
    season is constrained to [1999, 2030]: earliest reliable NFL play-by-play
    season available via nflreadpy.
    """

    model_config = ConfigDict(strict=True)

    game_id: str
    season: Annotated[int, Field(ge=1999, le=2030)]
    week: int
    posteam: str
    stat_type: Literal["passing", "rushing", "receiving"]
    filters: dict[str, object]


class QuantResult(BaseModel):
    """Stub output model for the Quant Agent.

    All fields are Optional with None defaults — Phase 3 populates real values
    from PostgreSQL query results. Keeping all fields nullable allows Phase 2
    stub nodes to return QuantResult() without DB access.

    confidence_interval stores the (lower, upper) Decimal bounds of the
    95% confidence interval around true_probability.
    """

    model_config = ConfigDict(strict=True)

    true_probability: Optional[Decimal] = None
    sample_size: Optional[int] = None
    confidence_interval: Optional[tuple[Decimal, Decimal]] = None
    data_source: Optional[str] = None


class EVSignal(BaseModel):
    """Output model for the Arbitrage Agent's +EV flag.

    Encodes the full mathematical thesis for a single flagged market discrepancy.
    Enforces hard limits from CLAUDE.md prop firm rules:
    - kelly_fraction capped at 0.25 (fractional Kelly, never full Kelly)
    - kelly_fraction must be positive (no negative sizing / short positions)
    - ev_percentage must be positive (only flag genuine +EV, never -EV)
    - trade_plan capped at 3 bullet points per CLAUDE.md UX requirements
    """

    model_config = ConfigDict(strict=True)

    ev_percentage: Annotated[Decimal, Field(gt=Decimal("0"))]
    # Legacy ev_percentage is probability edge, not return on stake.
    expected_return: Optional[Decimal] = None
    true_probability: Decimal
    implied_probability: Decimal
    kelly_fraction: Annotated[
        Decimal,
        Field(gt=Decimal("0"), le=Decimal("0.25")),
    ]
    trade_plan: Annotated[list[str], Field(max_length=3)]
    market_type: str


class AgentOddsSnapshot(BaseModel):
    """Point-in-time odds snapshot with pre-computed implied probability.

    Unlike the Phase 1 OddsSnapshotCreate (which stores raw American odds int),
    AgentOddsSnapshot stores implied_probability as Decimal. The conversion from
    American odds to implied probability happens at ingestion time — agents never
    operate on raw American odds integers to avoid unit-mismatch bugs.

    implied_probability is always in [0, 1] representing the sportsbook's
    break-even probability (including vig).
    """

    model_config = ConfigDict(strict=True)

    game_id: str
    sportsbook: str
    market_type: str
    implied_probability: Decimal
    snapped_at: datetime
    american_odds: Optional[int] = None  # Raw American odds integer for CLV persistence (e.g. -110)


class GameState(BaseModel):
    """Shared game context passed through the LangGraph state machine.

    Matches the GraphState game context shape defined in Phase 2 graph wiring.
    injury_flags maps player name to status string (e.g., "Out", "Questionable").
    weather_json is nullable: indoor stadiums and non-weather-sensitive markets
    pass None; outdoor weather-sensitive markets populate the full dict.
    """

    model_config = ConfigDict(strict=True)

    game_id: str
    season: int
    week: int
    home_team: str
    away_team: str
    injury_flags: dict[str, str]
    weather_json: Optional[dict[str, object]] = None


class ContextSignals(BaseModel):
    """Structured game context produced by the Context Agent.

    Propagated through GraphState.context_signals so all downstream agents
    (Quant, Arbitrage) read from state rather than re-fetching live data.

    injury_flags mirrors GraphState.injury_flags schema: {"P. Mahomes": "Out"}.
    weather_json is None for indoor stadiums and non-weather-sensitive markets.
    odds_snapshot is None when The Odds API budget is exhausted or call fails.
    signals_captured_at is UTC; always use datetime.now(timezone.utc) to set it.
    """

    model_config = ConfigDict(strict=True)

    game_id: str
    injury_flags: dict[str, str]
    weather_json: Optional[dict[str, object]] = None
    odds_snapshot: Optional[AgentOddsSnapshot] = None
    signals_captured_at: datetime


class PropParams(BaseModel):
    """Input parameters for the Phase 11 Prop Quant Agent SQL query builder.

    Validated before any SQL executes — enforces prop domain, sport, and season
    range. prop_type is a Literal union to prevent open-ended string injection
    into queries. season constrained to [2000, 2030]: NBA/NFL data boundary.

    ConfigDict(strict=True) — no coercion, no v1 class Config patterns.
    LLM produces PropParams; Phase 11 PropQueryBuilder constructs SQL from it.

    Phase 18 situational filter additions (SC-3):
    last_n_games, teammate_out, opponent_team, home_away are Optional with None
    defaults — fully backward-compatible; existing callers pass without those fields
    and PropParams still validates. Plan 03 PropQueryBuilder consumes these to
    apply conditional game-log filters at query time.
    """

    model_config = ConfigDict(strict=True)

    game_id: str
    player_id: str
    season: Annotated[int, Field(ge=2000, le=2030)]
    sport: Literal["nfl", "nba"]
    prop_type: Literal[
        "pass_yds",
        "pass_tds",
        "completions",
        "attempts",
        "rush_yds",
        "rush_tds",
        "carries",
        "rec_yds",
        "rec_tds",
        "receptions",
        "targets",
        "points",
        "rebounds",
        "assists",
        "threes",
        "steals",
        "blocks",
        "pra",
        # NBA composite prop (Phase 12): inclusion-exclusion probability model
        "double_double",
    ]
    line: Decimal
    filters: dict[str, object]
    # Situational filter extensions (Phase 18 — SC-3)
    # All Optional with None defaults — backward compatible; existing callers unchanged.
    # ConfigDict(strict=True) accepts Optional[T] = None per Phase 9 locked decision.
    last_n_games: Optional[int] = None
    teammate_out: Optional[list[str]] = None
    teammate_out_contexts: Optional[list[dict[str, str]]] = None
    opponent_team: Optional[str] = None
    home_away: Optional[Literal["home", "away"]] = None
    # Exclusive NBA game-date cutoff; historical callers must set this explicitly.
    as_of_date: Optional[date] = None


class PropResult(BaseModel):
    """Output model for the Phase 11 Prop Quant Agent.

    All fields are Optional with None defaults — Phase 11 populates real values
    from PostgreSQL query results. Keeping all fields nullable allows stub nodes
    to return PropResult() without DB access during development.

    mean_stat is the historical mean of the queried stat (e.g. average passing
    yards per game) — used alongside true_probability for trade plan generation.
    """

    model_config = ConfigDict(strict=True)

    true_probability: Optional[Decimal] = None
    sample_size: Optional[int] = None
    confidence_interval: Optional[tuple[Decimal, Decimal]] = None
    data_source: Optional[str] = None
    mean_stat: Optional[Decimal] = None


class NBAContextSignals(BaseModel):
    """NBA-specific contextual signals for player prop probability adjustment.

    Carries pace, defensive rating, rest days, and home/away context
    through GraphState for consumption by make_nba_quant_agent.

    All values are caller-supplied (from live data or fixture inputs) —
    never inferred by LLM. ConfigDict(strict=True) enforces type safety:
    no float coercion on Decimal fields.

    Fields
    ------
    opponent_def_rating:
        Opponent's defensive rating (points allowed per 100 possessions).
        League average is ~115.0. Higher = worse defense = more scoring.
    pace_factor:
        Team's pace (possessions per 48 minutes). League avg ~100.0.
        Higher pace = more opportunities for counting stats.
    rest_days:
        Days since last game. 0 = back-to-back (REST_PENALTY applied).
        1 or 2+ = no penalty.
    is_home:
        True if player's team is the home team (HOME_BOOST applied).
    """

    model_config = ConfigDict(strict=True)

    opponent_def_rating: Decimal
    pace_factor: Decimal
    rest_days: int
    is_home: bool
