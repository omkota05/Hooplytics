from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = Field(
        default="",
        description="SQLAlchemy URL, e.g. postgresql+psycopg://user:pass@localhost:5433/hooplytics",
    )
    test_database_url: str = ""
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    history_seasons: int = Field(default=2, ge=0, le=15)

    sync_on_startup: bool = True
    sync_interval_minutes: int = Field(default=30, ge=5)
    sync_stale_minutes: int = Field(default=30, ge=1)
    auto_backfill: bool = True
    upcoming_days: int = Field(default=14, ge=1, le=60)

    provider_min_request_interval_seconds: float = Field(default=0.35, ge=0.05)
    provider_timeout_seconds: float = Field(default=20, ge=1)
    provider_max_retries: int = Field(default=4, ge=0, le=10)

    log_level: str = "INFO"

    unabated_api_key: str = ""
    unabated_partner_code: str = ""
    unabated_api_base_url: str = ""
    unabated_min_request_interval_seconds: float = Field(default=5.0, ge=5.0)
    unabated_timeout_seconds: float = Field(default=25.0, ge=1)
    prop_odds_sync_on_startup: bool = True
    prop_odds_sync_interval_minutes: int = Field(default=15, ge=5)

    enable_ml_recommendations: bool = Field(
        default=False,
        description="When false, /api/recommendations is disabled and sync will not warm ML recommendation cache.",
    )
    enable_probability_calibration: bool = Field(
        default=False,
        description="When false, no Beta-calibrated win probabilities or EV are shown.",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
