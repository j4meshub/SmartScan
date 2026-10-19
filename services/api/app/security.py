from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from .config import get_settings

password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)


def normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    digits = digits.removeprefix("00")
    if len(digits) == 11 and digits.startswith("1"):
        digits = "86" + digits
    if not 8 <= len(digits) <= 15:
        raise ValueError("invalid phone number")
    return "+" + digits


def phone_hmac(phone: str) -> str:
    settings = get_settings()
    normalized = normalize_phone(phone)
    return hmac.new(settings.phone_pepper.encode(), normalized.encode(), hashlib.sha256).hexdigest()


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


def new_session() -> tuple[str, str, datetime]:
    settings = get_settings()
    raw = secrets.token_urlsafe(48)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    expires = datetime.now(UTC) + timedelta(hours=settings.session_hours)
    return raw, digest, expires


def token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
