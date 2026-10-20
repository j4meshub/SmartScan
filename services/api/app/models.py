from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def uuid_str() -> str:
    return str(uuid.uuid4())


class Role(str, enum.Enum):
    user = "user"
    admin = "admin"
    super_admin = "super_admin"


class UserStatus(str, enum.Enum):
    active = "active"
    disabled = "disabled"
    deleting = "deleting"
    deleted = "deleted"


class PhoneEncryptionStatus(str, enum.Enum):
    unavailable = "unavailable"
    encrypted = "encrypted"


class JobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    needs_review = "needs_review"


class UploadStatus(str, enum.Enum):
    pending = "pending"
    completed = "completed"
    expired = "expired"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("username", name="uq_users_username"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_hmac: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    phone_masked: Mapped[str] = mapped_column(String(32), nullable=False)
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.user, nullable=False)
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus), default=UserStatus.active, nullable=False
    )
    locale: Mapped[str] = mapped_column(String(10), default="zh-CN", nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    identities: Mapped[list[UserIdentity]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    verified_phone: Mapped[VerifiedPhone | None] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    projects: Mapped[list[ScanProject]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )


class UserIdentity(Base):
    __tablename__ = "user_identities"
    __table_args__ = (
        UniqueConstraint("provider", "provider_subject", name="uq_identity_provider_subject"),
        UniqueConstraint("user_id", "provider", name="uq_identity_user_provider"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    credential_hash: Mapped[str | None] = mapped_column(String(255))
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    user: Mapped[User] = relationship(back_populates="identities")


class VerifiedPhone(Base):
    __tablename__ = "verified_phones"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_verified_phone_user"),
        UniqueConstraint("phone_hmac", name="uq_verified_phone_hmac"),
        CheckConstraint(
            "(encryption_status = 'unavailable' AND phone_ciphertext IS NULL "
            "AND encryption_key_id IS NULL) OR "
            "(encryption_status = 'encrypted' AND phone_ciphertext IS NOT NULL "
            "AND encryption_key_id IS NOT NULL)",
            name="ck_verified_phone_encryption_state",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    phone_hmac: Mapped[str] = mapped_column(String(64), nullable=False)
    hmac_key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    phone_masked: Mapped[str] = mapped_column(String(32), nullable=False)
    phone_ciphertext: Mapped[str | None] = mapped_column(Text)
    encryption_key_id: Mapped[str | None] = mapped_column(String(64))
    encryption_status: Mapped[PhoneEncryptionStatus] = mapped_column(
        Enum(PhoneEncryptionStatus), nullable=False
    )
    verification_source: Mapped[str] = mapped_column(String(32), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    user: Mapped[User] = relationship(back_populates="verified_phone")


class SmsChallenge(Base):
    __tablename__ = "sms_challenges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    phone_hmac: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    hmac_key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    requester_ip_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_receipt: Mapped[str | None] = mapped_column(String(128))
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class SmsRateLimit(Base):
    __tablename__ = "sms_rate_limits"

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WeComOAuthState(Base):
    __tablename__ = "wecom_oauth_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    state_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WeComBindingTicket(Base):
    __tablename__ = "wecom_binding_tickets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    ticket_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    provider_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    assurance: Mapped[str] = mapped_column(String(32), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AccountMergeAudit(Base):
    __tablename__ = "account_merge_audits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    source_user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    canonical_user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    initiator_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    rule: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[str] = mapped_column(String(20), nullable=False)
    resource_counts: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SessionToken(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScanProject(Base):
    __tablename__ = "scan_projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    mode: Mapped[str] = mapped_column(String(24), default="document", nullable=False)
    reading_order: Mapped[str] = mapped_column(String(12), default="ltr", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    owner: Mapped[User] = relationship(back_populates="projects")
    pages: Mapped[list[ScanPage]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ScanPage(Base):
    __tablename__ = "scan_pages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("scan_projects.id", ondelete="CASCADE"), nullable=False
    )
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    original_path: Mapped[str] = mapped_column(String(500), nullable=False)
    processed_path: Mapped[str | None] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False)
    quality_warning: Mapped[str | None] = mapped_column(String(160))
    ocr_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    project: Mapped[ScanProject] = relationship(back_populates="pages")


class UploadSession(Base):
    __tablename__ = "upload_sessions"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "idempotency_key", name="uq_upload_owner_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("scan_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False)
    total_chunks: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[UploadStatus] = mapped_column(
        Enum(UploadStatus), default=UploadStatus.pending, nullable=False, index=True
    )
    page_id: Mapped[str | None] = mapped_column(
        ForeignKey("scan_pages.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    chunks: Mapped[list[UploadChunk]] = relationship(
        back_populates="upload", cascade="all, delete-orphan"
    )


class UploadChunk(Base):
    __tablename__ = "upload_chunks"
    __table_args__ = (UniqueConstraint("upload_id", "chunk_index", name="uq_upload_chunk"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    upload_id: Mapped[str] = mapped_column(
        ForeignKey("upload_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    upload: Mapped[UploadSession] = relationship(back_populates="chunks")


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("scan_projects.id", ondelete="CASCADE"), nullable=False
    )
    page_id: Mapped[str | None] = mapped_column(ForeignKey("scan_pages.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus), default=JobStatus.pending, nullable=False, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    actor_user_id: Mapped[str | None] = mapped_column(String(36), index=True)
    target_user_id: Mapped[str | None] = mapped_column(String(36), index=True)
    object_type: Mapped[str] = mapped_column(String(40), nullable=False)
    object_id: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[str] = mapped_column(String(20), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
