"""FastAPI dependencies."""

from app.config import Settings
from app.services.redis_client import Redis, get_redis


def get_settings() -> Settings:
    return Settings()


def get_redis_client() -> Redis:
    return get_redis(Settings())
