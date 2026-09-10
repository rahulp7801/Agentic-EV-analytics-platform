"""SQLAlchemy 2.0 ORM models — DDL source of truth for all 5 tables.

All models use DeclarativeBase (SQLAlchemy 2.x), Mapped, and mapped_column.
The Alembic migration 0001_initial_schema.py is derived from these definitions.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func

# Use TIMESTAMP WITH TIME ZONE for timezone-aware datetimes.
from sqlalchemy import DateTime as TIMESTAMPTZ  # aliased for clarity


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""

    pass


class Game(Base):
    """NFL/NBA game metadata. Parent table for FKs."""

    __tablename__ = "games"

    game_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    season: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    week: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    home_team: Mapped[str] = mapped_column(String(3), nullable=False)
    away_team: Mapped[str] = mapped_column(String(3), nullable=False)
    game_date: Mapped[date] = mapped_column(Date, nullable=False)
    stadium: Mapped[Optional[str]] = mapped_column(String(100))
    weather_json: Mapped[Optional[dict]] = mapped_column(JSONB)  # type: ignore[type-arg]
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_games_season_week", "season", "week"),
        Index("idx_games_teams", "home_team", "away_team"),
    )


class PlayByPlay(Base):
    """NFL play-by-play records (nflreadpy source)."""

    __tablename__ = "play_by_play"

    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True, primary_key=True)
    game_id: Mapped[Optional[str]] = mapped_column(
        String(20), ForeignKey("games.game_id")
    )
    play_id: Mapped[int] = mapped_column(Integer, nullable=False)
    season: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    week: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    posteam: Mapped[Optional[str]] = mapped_column(String(3))
    defteam: Mapped[Optional[str]] = mapped_column(String(3))
    play_type: Mapped[Optional[str]] = mapped_column(String(20))
    yards_gained: Mapped[Optional[int]] = mapped_column(SmallInteger)
    down: Mapped[Optional[int]] = mapped_column(SmallInteger)
    ydstogo: Mapped[Optional[int]] = mapped_column(SmallInteger)
    passer_player_id: Mapped[Optional[str]] = mapped_column(String(20))
    receiver_player_id: Mapped[Optional[str]] = mapped_column(String(20))
    rusher_player_id: Mapped[Optional[str]] = mapped_column(String(20))
    pass_touchdown: Mapped[Optional[int]] = mapped_column(SmallInteger)
    rush_touchdown: Mapped[Optional[int]] = mapped_column(SmallInteger)
    interception: Mapped[Optional[int]] = mapped_column(SmallInteger)
    air_yards: Mapped[Optional[int]] = mapped_column(SmallInteger)
    two_point_attempt: Mapped[Optional[int]] = mapped_column(SmallInteger)
    complete_pass: Mapped[Optional[int]] = mapped_column(SmallInteger)
    epa: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4))
    wp: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4))

    __table_args__ = (
        UniqueConstraint("game_id", "play_id", name="uq_pbp_game_play"),
        Index("idx_pbp_season_week", "season", "week"),
        Index("idx_pbp_posteam_season", "posteam", "season"),
        Index("idx_pbp_defteam_season", "defteam", "season"),
        Index("idx_pbp_play_type_season", "play_type", "season", "week"),
        Index("idx_pbp_passer_season", "passer_player_id", "season"),
        Index("idx_pbp_receiver_season", "receiver_player_id", "season"),
    )


class PlayerStat(Base):
    """Weekly player statistics (nfl_data_py weekly stats endpoint)."""

    __tablename__ = "player_stats"

    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True, primary_key=True)
    player_id: Mapped[str] = mapped_column(String(20), nullable=False)
    season: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    week: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    team: Mapped[Optional[str]] = mapped_column(String(3))
    position: Mapped[Optional[str]] = mapped_column(String(5))
    completions: Mapped[Optional[int]] = mapped_column(SmallInteger)
    attempts: Mapped[Optional[int]] = mapped_column(SmallInteger)
    passing_yards: Mapped[Optional[int]] = mapped_column(SmallInteger)
    passing_tds: Mapped[Optional[int]] = mapped_column(SmallInteger)
    interceptions: Mapped[Optional[int]] = mapped_column(SmallInteger)
    carries: Mapped[Optional[int]] = mapped_column(SmallInteger)
    rushing_yards: Mapped[Optional[int]] = mapped_column(SmallInteger)
    rushing_tds: Mapped[Optional[int]] = mapped_column(SmallInteger)
    receptions: Mapped[Optional[int]] = mapped_column(SmallInteger)
    targets: Mapped[Optional[int]] = mapped_column(SmallInteger)
    receiving_yards: Mapped[Optional[int]] = mapped_column(SmallInteger)
    receiving_tds: Mapped[Optional[int]] = mapped_column(SmallInteger)
    fantasy_points_ppr: Mapped[Optional[Decimal]] = mapped_column(Numeric(7, 2))
    # Phase 18: opponent_team and home_away added for NFL conditional prop queries.
    # nullable — existing rows do not have this data; populated on new ingest.
    opponent_team: Mapped[Optional[str]] = mapped_column(String(3))
    home_away: Mapped[Optional[str]] = mapped_column(String(4))  # "home" | "away"

    __table_args__ = (
        UniqueConstraint(
            "player_id", "season", "week", name="uq_playerstats_player_season_week"
        ),
        Index("idx_playerstats_player_season", "player_id", "season"),
        Index("idx_playerstats_season_week", "season", "week"),
    )


class NgsStats(Base):
    """AWS Next Gen Stats (separation, time-to-throw, press-man coverage).

    press_man_rate is nullable — forward-compatible for Phase 6 Kinematic Agent
    per RESEARCH.md open question on NGS data availability.
    """

    __tablename__ = "ngs_stats"

    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True, primary_key=True)
    player_gsis_id: Mapped[str] = mapped_column(String(20), nullable=False)
    season: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    week: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    stat_type: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # "passing" | "receiving" | "rushing"
    team_abbr: Mapped[Optional[str]] = mapped_column(String(3))
    player_position: Mapped[Optional[str]] = mapped_column(String(5))
    # Passing fields
    avg_time_to_throw: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    avg_completed_air_yards: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    aggressiveness: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    # Receiving fields
    avg_separation: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    avg_cushion: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    avg_yac_above_expectation: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    # Rushing fields
    efficiency: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    rush_yards_over_expected: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    avg_time_to_los: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    # Forward-compatible Phase 6 column (RESEARCH.md open question — nullable)
    press_man_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))

    __table_args__ = (
        UniqueConstraint(
            "player_gsis_id",
            "season",
            "week",
            "stat_type",
            name="uq_ngs_player_season_week_type",
        ),
        Index("idx_ngs_player_season", "player_gsis_id", "season"),
        Index("idx_ngs_season_week_type", "season", "week", "stat_type"),
    )


class OddsSnapshot(Base):
    """Point-in-time odds snapshot from The Odds API."""

    __tablename__ = "odds_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True, primary_key=True)
    game_id: Mapped[Optional[str]] = mapped_column(
        String(20), ForeignKey("games.game_id")
    )
    sportsbook: Mapped[str] = mapped_column(String(50), nullable=False)
    market_type: Mapped[str] = mapped_column(String(30), nullable=False)
    line: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2))
    price: Mapped[Optional[int]] = mapped_column(SmallInteger)  # American odds e.g. -110
    outcome_name: Mapped[Optional[str]] = mapped_column(String(100))
    game_start_time: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ(timezone=True))
    snapped_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_odds_game_market", "game_id", "market_type"),
        Index(
            "idx_odds_snapped_at_desc",
            "snapped_at",
            postgresql_ops={"snapped_at": "DESC"},
        ),
    )


class InjuryReport(Base):
    """Structured binary state change from ESPN Core API or Playwright scraper.

    Stores player injury status snapshots (Out/Questionable/Probable/Doubtful).
    append-only table — never UPDATE. Query latest scraped_at per player for
    current status.

    source column identifies data origin: "espn_core_api" or "nflweather".
    game_id FK is nullable — injury report may arrive before game_id is known.
    """

    __tablename__ = "injury_reports"

    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True, primary_key=True)
    game_id: Mapped[Optional[str]] = mapped_column(
        String(20), ForeignKey("games.game_id"), nullable=True
    )
    player_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # "Out"|"Questionable"|"Probable"|"Doubtful"
    position: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    team_abbr: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    scraped_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True), nullable=False, server_default=func.now()
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)  # "espn_core_api"

    __table_args__ = (
        Index("idx_injury_game_id", "game_id"),
        Index("idx_injury_scraped_at", "scraped_at"),
        Index("idx_injury_player_scraped", "player_name", "scraped_at"),
    )


class PlayerPropSnapshot(Base):
    """Point-in-time player prop odds snapshot from The Odds API.

    Append-only table — never UPDATE or UPSERT.
    implied_probability is stored as Decimal(str(round(raw_prob, 6))) — never
    float assigned directly to prevent precision loss.

    Three composite indexes support the Phase 11 prop quant engine query patterns:
    - idx_props_player_prop_snapped: player-prop timeline queries
    - idx_props_sport_snapped: sport-level scan with time filter
    - idx_props_game_prop: game-level prop lookup
    """

    __tablename__ = "player_prop_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True, primary_key=True)
    sport: Mapped[str] = mapped_column(String(5), nullable=False)
    game_id: Mapped[Optional[str]] = mapped_column(String(30))
    player_name: Mapped[str] = mapped_column(String(100), nullable=False)
    sportsbook: Mapped[str] = mapped_column(String(50), nullable=False)
    prop_type: Mapped[str] = mapped_column(String(40), nullable=False)
    line: Mapped[Optional[Decimal]] = mapped_column(Numeric(7, 2))
    price: Mapped[Optional[int]] = mapped_column(SmallInteger)
    implied_probability: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    snapped_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_props_player_prop_snapped", "player_name", "prop_type", "snapped_at"),
        Index("idx_props_sport_snapped", "sport", "snapped_at"),
        Index("idx_props_game_prop", "game_id", "prop_type"),
    )


class NBAPlayerStats(Base):
    """NBA player season-level statistics sourced from nba_api.

    Stores per-season aggregates for Phase 10+ NBA prop quant engine.
    UniqueConstraint on (player_id, season) prevents duplicate ingest.
    All counting stats are nullable — not all players have all stat types.

    Four indexes support the Phase 11 NBA query patterns:
    - idx_nba_player_season: player timeline queries
    - idx_nba_season: full-season scans
    - idx_nba_team_season: team roster queries
    """

    __tablename__ = "nba_player_stats"

    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True, primary_key=True)
    player_id: Mapped[int] = mapped_column(Integer, nullable=False)
    player_name: Mapped[str] = mapped_column(String(100), nullable=False)
    season: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    team_id: Mapped[Optional[int]] = mapped_column(Integer)
    team_abbreviation: Mapped[Optional[str]] = mapped_column(String(5))
    games_played: Mapped[Optional[int]] = mapped_column(SmallInteger)
    minutes: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 1))
    points: Mapped[Optional[int]] = mapped_column(Integer)
    rebounds: Mapped[Optional[int]] = mapped_column(Integer)
    assists: Mapped[Optional[int]] = mapped_column(Integer)
    threes_made: Mapped[Optional[int]] = mapped_column(Integer)
    steals: Mapped[Optional[int]] = mapped_column(Integer)
    blocks: Mapped[Optional[int]] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint("player_id", "season", name="uq_nba_player_season"),
        Index("idx_nba_player_season", "player_id", "season"),
        Index("idx_nba_season", "season"),
        Index("idx_nba_team_season", "team_id", "season"),
    )


class NBAPlayerGameLog(Base):
    """NBA per-game log sourced from nba_api PlayerGameLogs bulk endpoint.

    One row per player per game. Supports Phase 18 situational conditional
    probability queries (last_n_games, opponent_team, home_away filters).

    Three composite indexes power the conditional query patterns:
    - idx_nba_gamelog_player_season: player timeline range scans
    - idx_nba_gamelog_game_date: date+season window queries
    - idx_nba_gamelog_opponent: opponent-filtered season aggregations

    UniqueConstraint on (player_id, game_id) prevents duplicate ingest rows.
    is_home and opponent_team are derived at ingest time from the MATCHUP column
    via "@" detection (see sportsbet.ingestion.nba_gamelogs).
    """

    __tablename__ = "nba_player_gamelogs"

    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True, primary_key=True)
    player_id: Mapped[int] = mapped_column(Integer, nullable=False)
    player_name: Mapped[Optional[str]] = mapped_column(String(100))
    team_abbreviation: Mapped[Optional[str]] = mapped_column(String(3))
    game_id: Mapped[str] = mapped_column(String(20), nullable=False)
    game_date: Mapped[Optional[date]] = mapped_column(Date)
    season: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_home: Mapped[Optional[bool]] = mapped_column(Boolean)
    opponent_team: Mapped[Optional[str]] = mapped_column(String(3))
    minutes: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 1))
    points: Mapped[Optional[int]] = mapped_column(SmallInteger)
    rebounds: Mapped[Optional[int]] = mapped_column(SmallInteger)
    assists: Mapped[Optional[int]] = mapped_column(SmallInteger)
    threes_made: Mapped[Optional[int]] = mapped_column(SmallInteger)
    steals: Mapped[Optional[int]] = mapped_column(SmallInteger)
    blocks: Mapped[Optional[int]] = mapped_column(SmallInteger)

    __table_args__ = (
        UniqueConstraint("player_id", "game_id", name="uq_nba_gamelog_player_game"),
        Index("idx_nba_gamelog_player_season", "player_id", "season"),
        Index("idx_nba_gamelog_game_date", "game_date", "season"),
        Index("idx_nba_gamelog_opponent", "opponent_team", "season"),
    )


class EVSignalRecord(Base):
    """Historical EV signal output from the EV scanner pipeline.

    Append-only. One row per player-prop EV signal produced by scan_game_ev.py.
    Enables backtesting, CLV tracking, and trend analysis across scans.

    scan_id groups all signals from a single scan run (THREAD_BASE timestamp).
    """

    __tablename__ = "ev_signals"

    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True, primary_key=True)
    scan_id: Mapped[str] = mapped_column(String(30), nullable=False)
    game_id: Mapped[str] = mapped_column(String(50), nullable=False)
    home_team: Mapped[str] = mapped_column(String(5), nullable=False)
    away_team: Mapped[str] = mapped_column(String(5), nullable=False)
    game_date: Mapped[str] = mapped_column(String(8), nullable=False)  # YYYYMMDD
    player_name: Mapped[str] = mapped_column(String(100), nullable=False)
    prop_type: Mapped[str] = mapped_column(String(40), nullable=False)
    line: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False)
    true_probability: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    implied_probability: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    ev_percentage: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    kelly_fraction: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    american_odds: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    sample_size: Mapped[Optional[int]] = mapped_column(SmallInteger)
    mean_stat: Mapped[Optional[Decimal]] = mapped_column(Numeric(7, 2))
    sportsbook: Mapped[str] = mapped_column(String(50), nullable=False)
    gated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    trade_plan: Mapped[Optional[dict]] = mapped_column(JSONB)  # list[str] stored as JSONB
    opponent_def_rating: Mapped[Optional[Decimal]] = mapped_column(Numeric(7, 2))
    rest_days: Mapped[Optional[int]] = mapped_column(SmallInteger)
    is_home: Mapped[Optional[bool]] = mapped_column(Boolean)
    strength: Mapped[str] = mapped_column(String(10), nullable=False, default="medium")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_ev_scan_id", "scan_id"),
        Index("idx_ev_game_date", "game_date"),
        Index("idx_ev_player_prop", "player_name", "prop_type"),
        Index("idx_ev_created_at", "created_at"),
    )
