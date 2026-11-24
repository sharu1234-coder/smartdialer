from __future__ import annotations
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/smartdialer"
    database_url_async: str = ""
    secret_key: str = "dev-secret"
    environment: str = "development"
    log_level: str = "INFO"
    worker_id: str = "worker-1"
    lease_duration_seconds: int = 30
    max_retry_attempts: int = 3
    provider_timeout_seconds: int = 10
    circuit_breaker_threshold: int = 5
    circuit_breaker_timeout: int = 60

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
