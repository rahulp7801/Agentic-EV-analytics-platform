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
