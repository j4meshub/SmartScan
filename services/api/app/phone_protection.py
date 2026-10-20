from __future__ import annotations

import base64
import binascii
import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import Settings, get_settings
from .models import PhoneEncryptionStatus, VerifiedPhone
from .security import mask_phone, normalize_phone, phone_hmac

NONCE_BYTES = 12


class PhoneProtectionError(RuntimeError):
    """不携带手机号、密文或密钥内容的稳定安全错误。"""


@dataclass(frozen=True)
class ProtectedPhone:
    phone_hmac: str
    hmac_key_id: str
    phone_masked: str
    phone_ciphertext: str
    encryption_key_id: str


def _decode_encryption_key(settings: Settings, key_id: str) -> bytes:
    encoded_key = settings.resolved_phone_encryption_keys().get(key_id)
    if encoded_key is None:
        raise PhoneProtectionError("phone_encryption_key_unavailable")
    try:
        raw_key = base64.b64decode(encoded_key, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError, TypeError) as exc:
        raise PhoneProtectionError("phone_encryption_key_invalid") from exc
    if len(raw_key) != 32:
        raise PhoneProtectionError("phone_encryption_key_invalid")
    return raw_key


def _associated_data(user_id: str, key_id: str) -> bytes:
    return f"smartscan:verified-phone:v1:{user_id}:{key_id}".encode()


def protect_phone(
    phone: str,
    *,
    user_id: str,
    settings: Settings | None = None,
) -> ProtectedPhone:
    settings = settings or get_settings()
    settings.validate_phone_protection()
    normalized = normalize_phone(phone)
    encryption_key_id = settings.phone_encryption_active_key_id
    raw_key = _decode_encryption_key(settings, encryption_key_id)
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(raw_key).encrypt(
        nonce,
        normalized.encode(),
        _associated_data(user_id, encryption_key_id),
    )
    return ProtectedPhone(
        phone_hmac=phone_hmac(normalized, settings=settings),
        hmac_key_id=settings.phone_hmac_active_key_id,
        phone_masked=mask_phone(normalized),
        phone_ciphertext=base64.urlsafe_b64encode(nonce + ciphertext).decode(),
        encryption_key_id=encryption_key_id,
    )


def decrypt_phone(
    phone: VerifiedPhone,
    *,
    settings: Settings | None = None,
) -> str:
    if (
        phone.encryption_status != PhoneEncryptionStatus.encrypted
        or not phone.phone_ciphertext
        or not phone.encryption_key_id
    ):
        raise PhoneProtectionError("phone_reverification_required")
    settings = settings or get_settings()
    raw_key = _decode_encryption_key(settings, phone.encryption_key_id)
    try:
        payload = base64.b64decode(phone.phone_ciphertext, altchars=b"-_", validate=True)
        if len(payload) <= NONCE_BYTES:
            raise ValueError("ciphertext too short")
        plaintext = AESGCM(raw_key).decrypt(
            payload[:NONCE_BYTES],
            payload[NONCE_BYTES:],
            _associated_data(phone.user_id, phone.encryption_key_id),
        )
        return normalize_phone(plaintext.decode())
    except (binascii.Error, InvalidTag, UnicodeDecodeError, ValueError) as exc:
        raise PhoneProtectionError("phone_ciphertext_invalid") from exc


def phone_needs_rotation(
    phone: VerifiedPhone,
    *,
    settings: Settings | None = None,
) -> bool:
    settings = settings or get_settings()
    return phone.encryption_status == PhoneEncryptionStatus.encrypted and (
        phone.encryption_key_id != settings.phone_encryption_active_key_id
        or phone.hmac_key_id != settings.phone_hmac_active_key_id
    )


def rotate_verified_phone(
    phone: VerifiedPhone,
    *,
    settings: Settings | None = None,
) -> None:
    settings = settings or get_settings()
    plaintext = decrypt_phone(phone, settings=settings)
    protected = protect_phone(plaintext, user_id=phone.user_id, settings=settings)
    phone.phone_hmac = protected.phone_hmac
    phone.hmac_key_id = protected.hmac_key_id
    phone.phone_masked = protected.phone_masked
    phone.phone_ciphertext = protected.phone_ciphertext
    phone.encryption_key_id = protected.encryption_key_id
    phone.encryption_status = PhoneEncryptionStatus.encrypted
    if phone.user is not None:
        phone.user.phone_hmac = protected.phone_hmac
        phone.user.phone_masked = protected.phone_masked
