from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import User, UserIdentity, VerifiedPhone
from .schemas import UserView

LOCAL_PROVIDER = "local"


def local_identity_by_username(db: Session, username: str) -> UserIdentity | None:
    return db.scalar(
        select(UserIdentity).where(
            UserIdentity.provider == LOCAL_PROVIDER,
            UserIdentity.provider_subject == username,
        )
    )


def local_identity_for_user(db: Session, user_id: str) -> UserIdentity | None:
    return db.scalar(
        select(UserIdentity).where(
            UserIdentity.user_id == user_id,
            UserIdentity.provider == LOCAL_PROVIDER,
        )
    )


def verified_phone_by_hmac(db: Session, digest: str) -> VerifiedPhone | None:
    return db.scalar(select(VerifiedPhone).where(VerifiedPhone.phone_hmac == digest))


def verified_phone_for_user(db: Session, user_id: str) -> VerifiedPhone | None:
    return db.scalar(select(VerifiedPhone).where(VerifiedPhone.user_id == user_id))


def add_local_identity(
    db: Session,
    user: User,
    *,
    username: str,
    credential_hash: str,
    verified_at: datetime | None = None,
) -> UserIdentity:
    identity = UserIdentity(
        user_id=user.id,
        provider=LOCAL_PROVIDER,
        provider_subject=username,
        credential_hash=credential_hash,
    )
    if verified_at is not None:
        identity.verified_at = verified_at
        identity.created_at = verified_at
    db.add(identity)
    return identity


def add_verified_phone(
    db: Session,
    user: User,
    *,
    phone_hmac: str,
    phone_masked: str,
    verification_source: str,
    verified_at: datetime | None = None,
) -> VerifiedPhone:
    phone = VerifiedPhone(
        user_id=user.id,
        phone_hmac=phone_hmac,
        phone_masked=phone_masked,
        verification_source=verification_source,
    )
    if verified_at is not None:
        phone.verified_at = verified_at
        phone.created_at = verified_at
    db.add(phone)
    return phone


def user_view(db: Session, user: User) -> UserView:
    identity = local_identity_for_user(db, user.id)
    phone = verified_phone_for_user(db, user.id)
    return UserView(
        id=user.id,
        username=identity.provider_subject if identity is not None else user.username,
        phone_masked=phone.phone_masked if phone is not None else user.phone_masked,
        role=user.role,
        status=user.status,
        locale=user.locale,
        must_change_password=user.must_change_password,
        created_at=user.created_at,
    )
