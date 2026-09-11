"""Pydantic v2 settings for Quant-Sports platform."""

from typing import Literal

from pydantic import ConfigDict, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file."""

    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+psycopg://localhost/sportsbet"
    database_url_async: str = "postgresql+asyncpg://localhost/sportsbet"
    postgres_db: str = "sportsbet"
    log_level: str = "INFO"
    odds_api_key: str | None = None
    analytics_database_url: str | None = None
    # Reserved for read-only market research and separate demo integration.
    # Private key contents stay in ignored files, never in frontend settings.
    kalshi_api_key_id: str | None = None
    kalshi_private_key_path: str | None = None
    kalshi_demo_api_key_id: str | None = None
    kalshi_demo_private_key_path: str | None = None

    # Risk management — Kelly Criterion configuration (Phase 5 agents read these)
    bankroll_usd: float = Field(default=10000.0, gt=0)
    max_kelly_fraction: float = Field(default=0.25, ge=0, le=1)
    experimental_probability_adjustments: bool = False

    # Vig removal method for devigging market odds (Phase 15 — QUANT-02)
    # "multiplicative": proportional normalization (standard, default)
    # "pinnacle": power/binary-search devig correcting favorite-longshot bias
    vig_method: Literal["multiplicative", "pinnacle"] = "multiplicative"


settings = Settings()
