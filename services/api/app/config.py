from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SMARTSCAN_", extra="ignore")

    env: str = "development"
    database_url: str = "sqlite:///./smartscan.db"
    auto_migrate: bool = True
    storage_root: Path = Path("./data")
    secret_key: str = "development-only-secret-change-me"
    phone_pepper: str = "development-only-phone-pepper"
    superadmin_password: str = ""
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:8080"])
    dev_sms_code: str = "246810"
    wecom_mode: str = "disabled"
    wecom_corp_id: str = ""
    wecom_agent_id: str = ""
    wecom_secret: str = ""
    wecom_timeout_seconds: float = Field(default=5.0, ge=1.0, le=30.0)
    session_hours: int = 24
    max_upload_bytes: int = 25 * 1024 * 1024
    upload_chunk_bytes: int = 4 * 1024 * 1024
    upload_expiry_hours: int = 24
    vision_document_min_area_ratio: float = Field(default=0.2, gt=0.05, lt=0.95)
    vision_max_detection_dimension: int = Field(default=1600, ge=640, le=4096)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("wecom_mode")
    @classmethod
    def validate_wecom_mode(cls, value: str) -> str:
        if value not in {"disabled", "mock", "live"}:
            raise ValueError("SMARTSCAN_WECOM_MODE must be disabled, mock or live")
        return value

    def validate_production(self) -> None:
        if self.env == "production":
            if len(self.secret_key) < 32 or "change" in self.secret_key.lower():
                raise RuntimeError("SMARTSCAN_SECRET_KEY must be a strong production secret")
            if not self.superadmin_password:
                raise RuntimeError(
                    "SMARTSCAN_SUPERADMIN_PASSWORD is required on first production start"
                )
            if self.wecom_mode == "mock":
                raise RuntimeError("SMARTSCAN_WECOM_MODE=mock is forbidden in production")
            if self.wecom_mode == "live" and not all(
                (self.wecom_corp_id, self.wecom_agent_id, self.wecom_secret)
            ):
                raise RuntimeError("live WeCom configuration is incomplete")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_production()
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    return settings
