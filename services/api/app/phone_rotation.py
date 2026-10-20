from __future__ import annotations

import argparse
from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .database import SessionLocal
from .models import PhoneEncryptionStatus, VerifiedPhone
from .phone_protection import phone_needs_rotation, rotate_verified_phone


@dataclass(frozen=True)
class PhoneRotationResult:
    examined: int
    rotated: int
    requires_reverification: int


def rotate_phone_batch(
    db: Session,
    *,
    limit: int,
    apply: bool,
    settings: Settings | None = None,
) -> PhoneRotationResult:
    if limit < 1 or limit > 10_000:
        raise ValueError("limit must be between 1 and 10000")
    settings = settings or get_settings()
    examined = db.scalar(select(func.count()).select_from(VerifiedPhone)) or 0
    unavailable = (
        db.scalar(
            select(func.count())
            .select_from(VerifiedPhone)
            .where(VerifiedPhone.encryption_status != PhoneEncryptionStatus.encrypted)
        )
        or 0
    )
    phones = db.scalars(
        select(VerifiedPhone)
        .where(
            VerifiedPhone.encryption_status == PhoneEncryptionStatus.encrypted,
            or_(
                VerifiedPhone.encryption_key_id != settings.phone_encryption_active_key_id,
                VerifiedPhone.hmac_key_id != settings.phone_hmac_active_key_id,
            ),
        )
        .order_by(VerifiedPhone.id)
        .limit(limit)
    ).all()
    for phone in phones:
        if not phone_needs_rotation(phone, settings=settings):
            continue
        if apply:
            rotate_verified_phone(phone, settings=settings)
    if apply:
        db.commit()
    return PhoneRotationResult(
        examined=examined,
        rotated=len(phones),
        requires_reverification=unavailable,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="轮换可恢复的已验证手机号密钥")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--apply", action="store_true", help="实际写入；默认只输出计划")
    args = parser.parse_args()
    with SessionLocal() as db:
        result = rotate_phone_batch(db, limit=args.limit, apply=args.apply)
    mode = "已应用" if args.apply else "仅计划"
    print(
        f"手机号轮换{mode}：检查 {result.examined}，需轮换 {result.rotated}，"
        f"需重新验证 {result.requires_reverification}"
    )


if __name__ == "__main__":
    main()
