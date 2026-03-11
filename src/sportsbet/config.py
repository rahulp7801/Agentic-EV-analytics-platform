"""Pydantic v2 settings for Quant-Sports platform."""

from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file."""

    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+psycopg://localhost/sportsbet"
    database_url_async: str = "postgresql+asyncpg://localhost/sportsbet"
    postgres_db: str = "sportsbet"
    log_level: str = "INFO"

    # Risk management — Kelly Criterion configuration (Phase 5 agents read these)
    bankroll_usd: float = 10000.0
    max_kelly_fraction: float = 0.25


settings = Settings()
