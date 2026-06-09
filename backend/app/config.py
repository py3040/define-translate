"""Configuration from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ai_builder_base_url: str
    ai_builder_token: str
    upstash_redis_rest_url: str
    upstash_redis_rest_token: str
    hmac_secret: str
    fingerprint_secret: str
    ai_builder_timeout_sec: float = 60.0  # Timeout for AI Builder Space API calls
    # Number of trusted proxies that append to X-Forwarded-For before the request
    # reaches this app. The real client IP is the entry this many positions from
    # the right; everything further left is client-supplied and spoofable.
    # Measured as 2 on AI Builder Space (platform proxy + Cloudflare). Re-verify
    # with GET /api/_debug/ip if the platform's edge architecture changes.
    trusted_proxy_hops: int = 2
    # When set, enables the GET /api/_debug/ip diagnostic endpoint. Leave unset
    # to keep the endpoint disabled (returns 404) on a public deployment.
    ip_debug_token: str | None = None
    # Required to access GET /api/admin/analytics. If unset, that endpoint is
    # locked (fails closed with 503) rather than being publicly readable.
    admin_key: str | None = None
