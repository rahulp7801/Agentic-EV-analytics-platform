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


settings = Settings()
