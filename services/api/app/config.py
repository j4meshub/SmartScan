from __future__ import annotations

import base64
import binascii
import hashlib
import re
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
    internal_file_send_prefix: str = ""
    secret_key: str = "development-only-secret-change-me"
    phone_pepper: str = "development-only-phone-pepper"
    phone_hmac_active_key_id: str = "legacy-v1"
    phone_hmac_peppers: dict[str, str] = Field(default_factory=dict)
    phone_encryption_active_key_id: str = "phone-v1"
    phone_encryption_keys: dict[str, str] = Field(default_factory=dict)
    superadmin_password: str = ""
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:8080"])
    dev_sms_code: str = "246810"
    sms_mode: str = "mock"
    sms_challenge_ttl_seconds: int = Field(default=300, ge=60, le=900)
    sms_max_attempts: int = Field(default=5, ge=1, le=10)
    sms_rate_window_seconds: int = Field(default=900, ge=60, le=3600)
    sms_phone_rate_limit: int = Field(default=3, ge=1, le=20)
    sms_ip_rate_limit: int = Field(default=10, ge=1, le=100)
    wecom_mode: str = "disabled"
    wecom_corp_id: str = ""
    wecom_agent_id: str = ""
    wecom_secret: str = ""
    wecom_redirect_uri: str = ""
    wecom_state_ttl_seconds: int = Field(default=600, ge=60, le=1800)
    wecom_binding_ttl_seconds: int = Field(default=600, ge=60, le=1800)
    wecom_timeout_seconds: float = Field(default=5.0, ge=1.0, le=30.0)
    access_token_minutes: int = Field(default=15, ge=5, le=60)
    refresh_token_days: int = Field(default=30, ge=1, le=90)
    account_deletion_grace_days: int = Field(default=7, ge=1, le=7)
    phone_reuse_quarantine_days: int = Field(default=30, ge=30, le=365)
    session_hours: int = 24
    max_upload_bytes: int = 25 * 1024 * 1024
    upload_chunk_bytes: int = 4 * 1024 * 1024
    upload_expiry_hours: int = 24
    job_lease_seconds: int = Field(default=300, ge=30, le=1800)
    job_retry_base_seconds: int = Field(default=5, ge=1, le=300)
    job_max_attempts: int = Field(default=3, ge=1, le=10)
    vision_document_min_area_ratio: float = Field(default=0.2, gt=0.05, lt=0.95)
    vision_max_detection_dimension: int = Field(default=1600, ge=640, le=4096)
    ocr_enabled: bool = False
    ocr_model_root: Path = Path("./models/ocr")
    ocr_package_version: str = "3.7.0"
    ocr_engine_version: str = "3.3.1"
    ocr_model_version: str = "PP-OCRv6-small-v1"
    ocr_cpu_threads: int = Field(default=4, ge=1, le=16)
    ocr_min_confidence: float = Field(default=0.55, ge=0.0, le=1.0)
    ocr_title_min_confidence: float = Field(default=0.70, ge=0.0, le=1.0)
    ocr_orientation_margin: float = Field(default=0.04, ge=0.0, le=0.5)

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

    @field_validator("sms_mode")
    @classmethod
    def validate_sms_mode(cls, value: str) -> str:
        if value not in {"disabled", "mock"}:
            raise ValueError("SMARTSCAN_SMS_MODE must be disabled or mock")
        return value

    @field_validator("internal_file_send_prefix")
    @classmethod
    def validate_internal_file_send_prefix(cls, value: str) -> str:
        value = value.rstrip("/")
        if value and (not value.startswith("/") or ".." in value.split("/")):
            raise ValueError(
                "SMARTSCAN_INTERNAL_FILE_SEND_PREFIX must be an absolute safe URI path"
            )
        return value

    @staticmethod
    def _validate_key_id(value: str, setting_name: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", value):
            raise RuntimeError(f"{setting_name} must be a safe key identifier")

    def resolved_phone_hmac_peppers(self) -> dict[str, str]:
        if self.phone_hmac_peppers:
            return dict(self.phone_hmac_peppers)
        return {self.phone_hmac_active_key_id: self.phone_pepper}

    def resolved_phone_encryption_keys(self) -> dict[str, str]:
        if self.phone_encryption_keys:
            return dict(self.phone_encryption_keys)
        if self.env == "development":
            derived = hashlib.sha256(
                f"smartscan-development-phone-key:{self.secret_key}".encode()
            ).digest()
            return {self.phone_encryption_active_key_id: base64.urlsafe_b64encode(derived).decode()}
        return {}

    def validate_phone_protection(self) -> None:
        self._validate_key_id(
            self.phone_hmac_active_key_id,
            "SMARTSCAN_PHONE_HMAC_ACTIVE_KEY_ID",
        )
        self._validate_key_id(
            self.phone_encryption_active_key_id,
            "SMARTSCAN_PHONE_ENCRYPTION_ACTIVE_KEY_ID",
        )
        hmac_peppers = self.resolved_phone_hmac_peppers()
        if self.phone_hmac_active_key_id not in hmac_peppers:
            raise RuntimeError("active phone HMAC key is missing from the configured keyring")
        for key_id, pepper in hmac_peppers.items():
            self._validate_key_id(key_id, "SMARTSCAN_PHONE_HMAC_PEPPERS key")
            if self.env == "production" and (
                len(pepper) < 32 or "replace" in pepper.lower() or "development" in pepper.lower()
            ):
                raise RuntimeError("each phone HMAC pepper must be a strong production secret")

        encryption_keys = self.resolved_phone_encryption_keys()
        if self.phone_encryption_active_key_id not in encryption_keys:
            raise RuntimeError("active phone encryption key is missing from the configured keyring")
        for key_id, encoded_key in encryption_keys.items():
            self._validate_key_id(key_id, "SMARTSCAN_PHONE_ENCRYPTION_KEYS key")
            try:
                raw_key = base64.b64decode(encoded_key, altchars=b"-_", validate=True)
            except (binascii.Error, ValueError, TypeError) as exc:
                raise RuntimeError("phone encryption keys must be URL-safe base64") from exc
            if len(raw_key) != 32:
                raise RuntimeError("each phone encryption key must decode to exactly 32 bytes")

    def validate_production(self) -> None:
        if self.env == "production":
            if len(self.secret_key) < 32 or "change" in self.secret_key.lower():
                raise RuntimeError("SMARTSCAN_SECRET_KEY must be a strong production secret")
            if not self.phone_hmac_peppers and (
                len(self.phone_pepper) < 32
                or "replace" in self.phone_pepper.lower()
                or "development" in self.phone_pepper.lower()
            ):
                raise RuntimeError("SMARTSCAN_PHONE_PEPPER must be a strong production secret")
            self.validate_phone_protection()
            if not self.superadmin_password:
                raise RuntimeError(
                    "SMARTSCAN_SUPERADMIN_PASSWORD is required on first production start"
                )
            if self.wecom_mode == "mock":
                raise RuntimeError("SMARTSCAN_WECOM_MODE=mock is forbidden in production")
            if self.sms_mode == "mock":
                raise RuntimeError("SMARTSCAN_SMS_MODE=mock is forbidden in production")
            if self.wecom_mode == "live" and not all(
                (
                    self.wecom_corp_id,
                    self.wecom_agent_id,
                    self.wecom_secret,
                    self.wecom_redirect_uri,
                )
            ):
                raise RuntimeError("live WeCom configuration is incomplete")
            if not self.ocr_enabled:
                raise RuntimeError("SMARTSCAN_OCR_ENABLED=true is required in production")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_production()
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    return settings
