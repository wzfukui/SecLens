"""Application configuration and environment loading helpers."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application settings loaded from environment variables."""

    database_url: str = "postgresql+psycopg://seclens:seclens@localhost:5432/seclens_dev"
    app_env: str = "development"
    ingest_base_url: str = "http://localhost:8000"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached settings instance."""

    return Settings()


__all__ = ["Settings", "get_settings"]
