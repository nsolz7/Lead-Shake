from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Lead Intelligence Workbench"
    environment: str = "local"
    database_url: str = "sqlite:///./leadintel.db"
    redis_url: str = "redis://localhost:6379/0"
    data_dir: Path = Path("./data")
    admin_username: str = "admin"
    admin_password: str = "change-me-now"
    jwt_secret: str = "local-development-secret-change-me"
    jwt_expiry_minutes: int = 720
    login_max_failures: int = 8
    login_window_seconds: int = 900
    policy_hmac_secret: str = "local-policy-hmac-change-me"
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173", "http://localhost:8080"]
    google_maps_api_key: str | None = None
    hunter_api_key: str | None = None
    email_verification_api_key: str | None = None
    overture_release: str | None = None
    overture_parquet_uri: str | None = None
    openai_api_key: str | None = None
    openai_research_model: str = "gpt-5.6-luna"
    ai_research_max_budget_cents: int = 0
    ai_research_max_tool_calls: int = 2
    auto_research_enabled: bool = False
    auto_research_batch_size: int = 25
    auto_research_stale_days: int = 30
    free_api_research_enabled: bool = False
    sam_gov_api_key: str | None = None
    sec_user_agent: str | None = None
    max_website_pages: int = 12
    website_timeout_seconds: float = 15.0
    calendar_enabled: bool = False
    google_calendar_client_id: str | None = None
    google_calendar_client_secret: str | None = None
    google_calendar_redirect_uri: str | None = None
    google_calendar_token_encryption_key: str | None = None
    google_calendar_id: str = "primary"
    calendar_sync_interval_seconds: int = 300
    public_app_url: str = "http://localhost:8080"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    @property
    def is_local(self) -> bool:
        return self.environment.lower() in {"local", "dev", "development", "test"}

    @property
    def cookie_secure(self) -> bool:
        """Session cookies require HTTPS everywhere except local development."""
        return not self.is_local

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def validate_feature_configuration(self) -> "Settings":
        if self.calendar_enabled:
            required = {
                "GOOGLE_CALENDAR_CLIENT_ID": self.google_calendar_client_id,
                "GOOGLE_CALENDAR_CLIENT_SECRET": self.google_calendar_client_secret,
                "GOOGLE_CALENDAR_REDIRECT_URI": self.google_calendar_redirect_uri,
                "GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY": self.google_calendar_token_encryption_key,
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise ValueError(f"CALENDAR_ENABLED requires: {', '.join(missing)}")
        return self


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
