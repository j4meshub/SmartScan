from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .models import SmsChallenge, SmsRateLimit
from .security import normalize_phone, phone_hmac


class SmsProviderError(RuntimeError):
    """不携带手机号、验证码或供应商 Secret 的稳定错误。"""


class SmsRateLimitError(RuntimeError):
    pass


class SmsProvider(Protocol):
    name: str

    def send_verification(self, *, phone: str, code: str, challenge_id: str) -> str: ...


class DisabledSmsProvider:
    name = "disabled"

    def send_verification(self, *, phone: str, code: str, challenge_id: str) -> str:
        raise SmsProviderError("sms_provider_disabled")


class DevelopmentMockSmsProvider:
    name = "development_mock"

    def __init__(self, settings: Settings):
        if settings.env != "development":
            raise SmsProviderError("sms_mock_development_only")

    def send_verification(self, *, phone: str, code: str, challenge_id: str) -> str:
        return f"mock-{challenge_id}"


def create_sms_provider(settings: Settings | None = None) -> SmsProvider:
    settings = settings or get_settings()
    if settings.sms_mode == "mock":
        return DevelopmentMockSmsProvider(settings)
    return DisabledSmsProvider()


@dataclass(frozen=True)
class ChallengeVerification:
    accepted: bool
    reason: str
    verification_source: str | None = None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _ip_hash(ip: str, settings: Settings) -> str:
    return hmac.new(
        settings.secret_key.encode(),
        f"smartscan:sms-ip:v1:{ip}".encode(),
        hashlib.sha256,
    ).hexdigest()


def _code_hash(challenge_id: str, code: str, settings: Settings) -> str:
    return hmac.new(
        settings.secret_key.encode(),
        f"smartscan:sms-code:v1:{challenge_id}:{code}".encode(),
        hashlib.sha256,
    ).hexdigest()


def _rate_key(scope: str, value: str, settings: Settings) -> str:
    return hmac.new(
        settings.secret_key.encode(),
        f"smartscan:sms-rate:v1:{scope}:{value}".encode(),
        hashlib.sha256,
    ).hexdigest()


def _consume_rate_limit(
    db: Session,
    *,
    scope: str,
    value: str,
    limit: int,
    now: datetime,
    settings: Settings,
) -> None:
    key_hash = _rate_key(scope, value, settings)
    bucket = db.scalar(
        select(SmsRateLimit).where(SmsRateLimit.key_hash == key_hash).with_for_update()
    )
    if bucket is None:
        try:
            with db.begin_nested():
                bucket = SmsRateLimit(
                    key_hash=key_hash,
                    scope=scope,
                    window_started_at=now,
                    count=1,
                    updated_at=now,
                )
                db.add(bucket)
                db.flush()
            return
        except IntegrityError:
            bucket = db.scalar(
                select(SmsRateLimit).where(SmsRateLimit.key_hash == key_hash).with_for_update()
            )
            if bucket is None:
                raise SmsRateLimitError(f"sms_{scope}_rate_limited") from None
    window_ends = _aware(bucket.window_started_at) + timedelta(
        seconds=settings.sms_rate_window_seconds
    )
    if window_ends <= now:
        bucket.window_started_at = now
        bucket.count = 1
        bucket.updated_at = now
        return
    if bucket.count >= limit:
        raise SmsRateLimitError(f"sms_{scope}_rate_limited")
    bucket.count += 1
    bucket.updated_at = now


def create_sms_challenge(
    db: Session,
    *,
    phone: str,
    purpose: str,
    requester_ip: str,
    provider: SmsProvider,
    settings: Settings | None = None,
) -> SmsChallenge:
    settings = settings or get_settings()
    normalized = normalize_phone(phone)
    ip_digest = _ip_hash(requester_ip, settings)
    now = datetime.now(UTC)
    _consume_rate_limit(
        db,
        scope="phone",
        value=normalized,
        limit=settings.sms_phone_rate_limit,
        now=now,
        settings=settings,
    )
    _consume_rate_limit(
        db,
        scope="ip",
        value=ip_digest,
        limit=settings.sms_ip_rate_limit,
        now=now,
        settings=settings,
    )

    challenge_id = str(uuid.uuid4())
    code = (
        settings.dev_sms_code
        if provider.name == "development_mock"
        else f"{secrets.randbelow(1_000_000):06d}"
    )
    challenge = SmsChallenge(
        id=challenge_id,
        phone_hmac=phone_hmac(normalized, settings=settings),
        hmac_key_id=settings.phone_hmac_active_key_id,
        requester_ip_hash=ip_digest,
        purpose=purpose,
        code_hash=_code_hash(challenge_id, code, settings),
        provider=provider.name,
        attempts=0,
        max_attempts=settings.sms_max_attempts,
        expires_at=now + timedelta(seconds=settings.sms_challenge_ttl_seconds),
        created_at=now,
    )
    db.add(challenge)
    db.flush()
    challenge.provider_receipt = provider.send_verification(
        phone=normalized,
        code=code,
        challenge_id=challenge.id,
    )
    return challenge


def consume_sms_challenge(
    db: Session,
    *,
    challenge_id: str,
    phone: str,
    code: str,
    purpose: str,
    settings: Settings | None = None,
) -> ChallengeVerification:
    settings = settings or get_settings()
    challenge = db.scalar(
        select(SmsChallenge).where(SmsChallenge.id == challenge_id).with_for_update()
    )
    if challenge is None or challenge.purpose != purpose:
        return ChallengeVerification(False, "invalid_sms_challenge")
    now = datetime.now(UTC)
    if challenge.consumed_at is not None:
        return ChallengeVerification(False, "sms_challenge_consumed")
    if _aware(challenge.expires_at) <= now:
        return ChallengeVerification(False, "sms_challenge_expired")
    if challenge.attempts >= challenge.max_attempts:
        return ChallengeVerification(False, "sms_challenge_attempts_exhausted")
    try:
        expected_phone = phone_hmac(phone, key_id=challenge.hmac_key_id, settings=settings)
    except RuntimeError:
        return ChallengeVerification(False, "invalid_sms_challenge")
    expected_code = _code_hash(challenge.id, code, settings)
    if not (
        hmac.compare_digest(challenge.phone_hmac, expected_phone)
        and hmac.compare_digest(challenge.code_hash, expected_code)
    ):
        challenge.attempts += 1
        reason = (
            "sms_challenge_attempts_exhausted"
            if challenge.attempts >= challenge.max_attempts
            else "invalid_sms_code"
        )
        return ChallengeVerification(False, reason)
    challenge.attempts += 1
    challenge.verified_at = now
    challenge.consumed_at = now
    return ChallengeVerification(True, "accepted", challenge.provider)
