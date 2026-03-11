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

from datetime import datetime
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
