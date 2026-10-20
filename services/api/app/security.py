from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from .config import Settings, get_settings

password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)


def normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    digits = digits.removeprefix("00")
    if len(digits) == 11 and digits.startswith("1"):
        digits = "86" + digits
    if not 8 <= len(digits) <= 15:
        raise ValueError("invalid phone number")
    return "+" + digits


def phone_hmac(
    phone: str,
    *,
    key_id: str | None = None,
    settings: Settings | None = None,
) -> str:
    settings = settings or get_settings()
    selected_key_id = key_id or settings.phone_hmac_active_key_id
    pepper = settings.resolved_phone_hmac_peppers().get(selected_key_id)
    if pepper is None:
        raise RuntimeError("phone_hmac_key_unavailable")
    normalized = normalize_phone(phone)
    return hmac.new(pepper.encode(), normalized.encode(), hashlib.sha256).hexdigest()


def phone_hmac_candidates(
    phone: str,
    *,
    settings: Settings | None = None,
) -> dict[str, str]:
    settings = settings or get_settings()
    return {
        key_id: phone_hmac(phone, key_id=key_id, settings=settings)
        for key_id in settings.resolved_phone_hmac_peppers()
    }


def mask_phone(phone: str) -> str:
    normalized = normalize_phone(phone)
    return normalized[:3] + "****" + normalized[-4:]


def hash_password(password: str) -> str:
    if len(password) < 10:
        raise ValueError("password must contain at least 10 characters")
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def new_session(*, legacy: bool = False) -> tuple[str, str, datetime]:
    settings = get_settings()
    raw = secrets.token_urlsafe(48)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    lifetime = (
        timedelta(hours=settings.session_hours)
        if legacy
        else timedelta(minutes=settings.access_token_minutes)
    )
    expires = datetime.now(UTC) + lifetime
    return raw, digest, expires


def new_refresh_token() -> tuple[str, str, datetime]:
    settings = get_settings()
    raw = secrets.token_urlsafe(64)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    expires = datetime.now(UTC) + timedelta(days=settings.refresh_token_days)
    return raw, digest, expires


def token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
