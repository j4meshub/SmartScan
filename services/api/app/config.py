from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SMARTSCAN_", extra="ignore")

    env: str = "development"
    database_url: str = "sqlite:///./smartscan.db"
    storage_root: Path = Path("./data")
    secret_key: str = "development-only-secret-change-me"
    phone_pepper: str = "development-only-phone-pepper"
    superadmin_password: str = ""
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:8080"])
    dev_sms_code: str = "246810"
    session_hours: int = 24
    max_upload_bytes: int = 25 * 1024 * 1024

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    def validate_production(self) -> None:
        if self.env == "production":
            if len(self.secret_key) < 32 or "change" in self.secret_key.lower():
                raise RuntimeError("SMARTSCAN_SECRET_KEY must be a strong production secret")
            if not self.superadmin_password:
                raise RuntimeError(
                    "SMARTSCAN_SUPERADMIN_PASSWORD is required on first production start"
                )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_production()
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    return settings
