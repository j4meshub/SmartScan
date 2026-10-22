from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
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


class AccountDeletionStatus(str, enum.Enum):
    pending = "pending"
    cleanup_pending = "cleanup_pending"
    completed = "completed"
    canceled = "canceled"


class JobStatus(str, enum.Enum):
    queued = "queued"
    baseline_processing = "baseline_processing"
    baseline_ready = "baseline_ready"
    optional_enhancing = "optional_enhancing"
    ready = "ready"
    failed_retryable = "failed_retryable"
    failed_final = "failed_final"
    canceled = "canceled"


class PageReviewStatus(str, enum.Enum):
    not_required = "not_required"
    pending = "pending"
    confirmed = "confirmed"


class UploadStatus(str, enum.Enum):
    pending = "pending"
    completed = "completed"
    expired = "expired"
    canceled = "canceled"


class ExportStatus(str, enum.Enum):
    generating = "generating"
    ready = "ready"
    failed = "failed"


class ProjectDeletionStatus(str, enum.Enum):
    cleanup_pending = "cleanup_pending"
    completed = "completed"


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


class AccountDeletionRequest(Base):
    __tablename__ = "account_deletion_requests"
    __table_args__ = (UniqueConstraint("user_id", name="uq_account_deletion_user"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    requested_by_user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    request_source: Mapped[str] = mapped_column(String(20), nullable=False, default="self_service")
    reason: Mapped[str | None] = mapped_column(String(500))
    cancellation_reason: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[AccountDeletionStatus] = mapped_column(
        Enum(AccountDeletionStatus),
        default=AccountDeletionStatus.pending,
        nullable=False,
        index=True,
    )
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    execute_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(64))
    resource_counts: Mapped[str | None] = mapped_column(Text)


class PhoneReuseQuarantine(Base):
    __tablename__ = "phone_reuse_quarantines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    phone_hmac: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    hmac_key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    deletion_request_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SessionToken(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False, default=uuid_str, index=True)
    device_name: Mapped[str] = mapped_column(String(100), nullable=False, default="旧版客户端")
    platform: Mapped[str] = mapped_column(String(32), nullable=False, default="legacy")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("refresh_tokens.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScanProject(Base):
    __tablename__ = "scan_projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    suggested_name: Mapped[str | None] = mapped_column(String(160))
    suggested_name_source: Mapped[str | None] = mapped_column(String(24))
    suggested_name_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mode: Mapped[str] = mapped_column(String(24), default="document", nullable=False)
    reading_order: Mapped[str] = mapped_column(String(12), default="ltr", nullable=False)
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ai_consent_version: Mapped[str | None] = mapped_column(String(32))
    ai_enabled_by_user_id: Mapped[str | None] = mapped_column(String(36))
    ai_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    owner: Mapped[User] = relationship(back_populates="projects")
    pages: Mapped[list[ScanPage]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    exports: Mapped[list[ScanExport]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ScanPage(Base):
    __tablename__ = "scan_pages"
    __table_args__ = (
        CheckConstraint("rotation_degrees IN (0, 90, 180, 270)", name="ck_scan_pages_rotation"),
        CheckConstraint(
            "quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 100)",
            name="ck_scan_pages_quality_score",
        ),
        CheckConstraint("active_result_version >= 0", name="ck_scan_pages_active_result_version"),
        CheckConstraint(
            "ocr_confidence IS NULL OR (ocr_confidence >= 0 AND ocr_confidence <= 1)",
            name="ck_scan_pages_ocr_confidence",
        ),
        CheckConstraint(
            "ocr_rotation_degrees IS NULL OR ocr_rotation_degrees IN (0, 90, 180, 270)",
            name="ck_scan_pages_ocr_rotation",
        ),
        CheckConstraint(
            "ocr_status IN ('pending', 'ready', 'disabled', 'stale', 'legacy')",
            name="ck_scan_pages_ocr_status",
        ),
        CheckConstraint(
            "ocr_result_version IS NULL OR ocr_result_version >= 0",
            name="ck_scan_pages_ocr_result_version",
        ),
        CheckConstraint(
            "exam_classification_status IN ('pending', 'ready', 'disabled', 'stale', 'legacy')",
            name="ck_scan_pages_exam_classification_status",
        ),
        CheckConstraint(
            "exam_result_version IS NULL OR exam_result_version >= 0",
            name="ck_scan_pages_exam_result_version",
        ),
        CheckConstraint(
            "exam_prediction IS NULL OR exam_prediction IN ('ordinary', 'exam')",
            name="ck_scan_pages_exam_prediction",
        ),
        CheckConstraint(
            "exam_probability IS NULL OR (exam_probability >= 0 AND exam_probability <= 1)",
            name="ck_scan_pages_exam_probability",
        ),
        CheckConstraint(
            "exam_confidence_band IS NULL OR exam_confidence_band IN ('low', 'medium', 'high')",
            name="ck_scan_pages_exam_confidence_band",
        ),
        CheckConstraint(
            "exam_recommendation IS NULL OR "
            "exam_recommendation IN ('ordinary', 'ask', 'suggest_cleanup')",
            name="ck_scan_pages_exam_recommendation",
        ),
        CheckConstraint(
            "exam_suggestion_dismissed_result_version IS NULL OR "
            "exam_suggestion_dismissed_result_version >= 0",
            name="ck_scan_pages_exam_dismissed_result_version",
        ),
        CheckConstraint(
            "book_split_status IN "
            "('disabled', 'legacy', 'pending', 'split', 'fallback', 'retake', 'supplement')",
            name="ck_scan_pages_book_split_status",
        ),
        CheckConstraint(
            "book_side IS NULL OR book_side IN ('left', 'right', 'single')",
            name="ck_scan_pages_book_side",
        ),
        CheckConstraint(
            "book_split_confidence IS NULL OR "
            "(book_split_confidence >= 0 AND book_split_confidence <= 1)",
            name="ck_scan_pages_book_split_confidence",
        ),
        CheckConstraint(
            "book_dewarp_source_score IS NULL OR "
            "(book_dewarp_source_score >= 0 AND book_dewarp_source_score <= 1)",
            name="ck_scan_pages_book_dewarp_source_score",
        ),
        CheckConstraint(
            "book_dewarp_output_score IS NULL OR "
            "(book_dewarp_output_score >= 0 AND book_dewarp_output_score <= 1)",
            name="ck_scan_pages_book_dewarp_output_score",
        ),
        CheckConstraint(
            "book_page_number_status IN "
            "('disabled', 'legacy', 'pending', 'ready', 'none', 'ambiguous', 'stale')",
            name="ck_scan_pages_book_page_number_status",
        ),
        CheckConstraint(
            "book_page_number_kind IS NULL OR book_page_number_kind IN ('arabic', 'roman')",
            name="ck_scan_pages_book_page_number_kind",
        ),
        CheckConstraint(
            "book_page_number_confidence IS NULL OR "
            "(book_page_number_confidence >= 0 AND book_page_number_confidence <= 1)",
            name="ck_scan_pages_book_page_number_confidence",
        ),
        CheckConstraint(
            "book_page_number_result_version IS NULL OR book_page_number_result_version >= 0",
            name="ck_scan_pages_book_page_number_result_version",
        ),
        CheckConstraint(
            "book_fingerprint_result_version IS NULL OR book_fingerprint_result_version >= 0",
            name="ck_scan_pages_book_fingerprint_result_version",
        ),
        UniqueConstraint("book_capture_id", "book_side", name="uq_scan_pages_book_capture_side"),
        UniqueConstraint("book_replaced_by_page_id", name="uq_scan_pages_book_replaced_by"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("scan_projects.id", ondelete="CASCADE"), nullable=False
    )
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    original_path: Mapped[str] = mapped_column(String(500), nullable=False)
    original_mime_type: Mapped[str] = mapped_column(
        String(64), default="image/jpeg", nullable=False
    )
    processed_path: Mapped[str | None] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False)
    quality_warning: Mapped[str | None] = mapped_column(String(160))
    quality_score: Mapped[float | None] = mapped_column(Float)
    quality_details: Mapped[str | None] = mapped_column(Text)
    rotation_degrees: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active_result_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    review_status: Mapped[PageReviewStatus] = mapped_column(
        Enum(PageReviewStatus), default=PageReviewStatus.not_required, nullable=False, index=True
    )
    review_reason: Mapped[str | None] = mapped_column(String(160))
    reviewed_by_user_id: Mapped[str | None] = mapped_column(String(36))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ocr_text: Mapped[str | None] = mapped_column(Text)
    ocr_status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    ocr_result_version: Mapped[int | None] = mapped_column(Integer)
    ocr_model_version: Mapped[str | None] = mapped_column(String(64))
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    ocr_rotation_degrees: Mapped[int | None] = mapped_column(Integer)
    ocr_details: Mapped[str | None] = mapped_column(Text)
    ocr_title_candidate: Mapped[str | None] = mapped_column(String(160))
    ocr_error_code: Mapped[str | None] = mapped_column(String(64))
    ocr_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exam_classification_status: Mapped[str] = mapped_column(
        String(24), default="pending", nullable=False
    )
    exam_result_version: Mapped[int | None] = mapped_column(Integer)
    exam_classifier_version: Mapped[str | None] = mapped_column(String(96))
    exam_prediction: Mapped[str | None] = mapped_column(String(16))
    exam_probability: Mapped[float | None] = mapped_column(Float)
    exam_confidence_band: Mapped[str | None] = mapped_column(String(16))
    exam_recommendation: Mapped[str | None] = mapped_column(String(24))
    exam_details: Mapped[str | None] = mapped_column(Text)
    exam_suggestion_dismissed_result_version: Mapped[int | None] = mapped_column(Integer)
    exam_suggestion_dismissed_by_user_id: Mapped[str | None] = mapped_column(String(36))
    exam_suggestion_dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exam_suggestion_dismissal_reason: Mapped[str | None] = mapped_column(String(160))
    exam_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    book_capture_id: Mapped[str | None] = mapped_column(String(36), index=True)
    book_side: Mapped[str | None] = mapped_column(String(8))
    book_split_status: Mapped[str] = mapped_column(String(24), default="disabled", nullable=False)
    book_split_confidence: Mapped[float | None] = mapped_column(Float)
    book_split_reason: Mapped[str | None] = mapped_column(String(64))
    book_spine_x: Mapped[int | None] = mapped_column(Integer)
    book_logical_source_path: Mapped[str | None] = mapped_column(String(500))
    book_dewarp_applied: Mapped[bool | None] = mapped_column(Boolean)
    book_dewarp_source_score: Mapped[float | None] = mapped_column(Float)
    book_dewarp_output_score: Mapped[float | None] = mapped_column(Float)
    book_dewarp_reason: Mapped[str | None] = mapped_column(String(64))
    book_replaced_by_page_id: Mapped[str | None] = mapped_column(
        ForeignKey("scan_pages.id", ondelete="SET NULL"), index=True
    )
    book_page_number_status: Mapped[str] = mapped_column(
        String(24), default="disabled", nullable=False
    )
    book_page_number_label: Mapped[str | None] = mapped_column(String(24))
    book_page_number_value: Mapped[int | None] = mapped_column(Integer)
    book_page_number_kind: Mapped[str | None] = mapped_column(String(12))
    book_page_number_confidence: Mapped[float | None] = mapped_column(Float)
    book_page_number_reason: Mapped[str | None] = mapped_column(String(64))
    book_page_number_result_version: Mapped[int | None] = mapped_column(Integer)
    book_expected_page_label: Mapped[str | None] = mapped_column(String(24))
    book_content_fingerprint: Mapped[str | None] = mapped_column(String(16))
    book_fingerprint_result_version: Mapped[int | None] = mapped_column(Integer)
    book_assembly_included: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    book_assembly_exclusion_reason: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    project: Mapped[ScanProject] = relationship(back_populates="pages")
    results: Mapped[list[PageResult]] = relationship(
        back_populates="page", cascade="all, delete-orphan"
    )


class PageResult(Base):
    __tablename__ = "page_results"
    __table_args__ = (
        UniqueConstraint("page_id", "version", name="uq_page_result_version"),
        CheckConstraint("rotation_degrees IN (0, 90, 180, 270)", name="ck_page_result_rotation"),
        CheckConstraint(
            "source_result_version IS NULL OR source_result_version >= 1",
            name="ck_page_results_source_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    page_id: Mapped[str] = mapped_column(
        ForeignKey("scan_pages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    result_type: Mapped[str] = mapped_column(String(32), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    rotation_degrees: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processor_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_result_version: Mapped[int | None] = mapped_column(Integer)
    provenance: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    page: Mapped[ScanPage] = relationship(back_populates="results")


class BookIntegrityDecision(Base):
    __tablename__ = "book_integrity_decisions"
    __table_args__ = (
        UniqueConstraint("project_id", "issue_key", name="uq_book_integrity_decision_issue"),
        CheckConstraint(
            "decision IN ('ignored', 'confirmed_absent', 'keep_both', 'exclude_duplicate')",
            name="ck_book_integrity_decisions_decision",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("scan_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    issue_key: Mapped[str] = mapped_column(String(160), nullable=False)
    issue_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    details: Mapped[str | None] = mapped_column(Text)
    decided_by_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScanExport(Base):
    __tablename__ = "scan_exports"
    __table_args__ = (
        CheckConstraint("format IN ('jpg', 'pdf')", name="ck_scan_exports_format"),
        CheckConstraint(
            "quality IN ('clear', 'balanced', 'small')", name="ck_scan_exports_quality"
        ),
        CheckConstraint(
            "status IN ('generating', 'ready', 'failed')", name="ck_scan_exports_status"
        ),
        CheckConstraint("page_count >= 1", name="ck_scan_exports_page_count"),
        CheckConstraint(
            "ocr_pages_used >= 0 AND ocr_pages_used <= page_count",
            name="ck_scan_exports_ocr_pages_used",
        ),
        CheckConstraint(
            "book_assembly_revision IS NULL OR book_assembly_revision >= 1",
            name="ck_scan_exports_book_assembly_revision",
        ),
        UniqueConstraint(
            "project_id", "book_assembly_signature", name="uq_scan_exports_book_assembly_signature"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("scan_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    format: Mapped[str] = mapped_column(String(8), nullable=False)
    quality: Mapped[str] = mapped_column(String(16), nullable=False)
    include_ocr_text: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[ExportStatus] = mapped_column(
        Enum(ExportStatus, native_enum=False, length=16),
        default=ExportStatus.generating,
        nullable=False,
        index=True,
    )
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    ocr_pages_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    base_file_name: Mapped[str] = mapped_column(String(160), nullable=False)
    page_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    processor_version: Mapped[str] = mapped_column(String(64), nullable=False)
    book_assembly_signature: Mapped[str | None] = mapped_column(String(64), index=True)
    book_assembly_revision: Mapped[int | None] = mapped_column(Integer)
    book_previous_export_id: Mapped[str | None] = mapped_column(
        ForeignKey("scan_exports.id", ondelete="SET NULL"), index=True
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    project: Mapped[ScanProject] = relationship(back_populates="exports")
    artifacts: Mapped[list[ExportArtifact]] = relationship(
        back_populates="export", cascade="all, delete-orphan", order_by="ExportArtifact.sequence"
    )


class ExportArtifact(Base):
    __tablename__ = "export_artifacts"
    __table_args__ = (
        UniqueConstraint("export_id", "sequence", name="uq_export_artifact_sequence"),
        CheckConstraint("sequence >= 1", name="ck_export_artifacts_sequence"),
        CheckConstraint("size_bytes >= 0", name="ck_export_artifacts_size"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    export_id: Mapped[str] = mapped_column(
        ForeignKey("scan_exports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_id: Mapped[str | None] = mapped_column(
        ForeignKey("scan_pages.id", ondelete="SET NULL"), nullable=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    export: Mapped[ScanExport] = relationship(back_populates="artifacts")


class ProjectDeletion(Base):
    __tablename__ = "project_deletions"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_project_deletions_project"),
        CheckConstraint(
            "status IN ('cleanup_pending', 'completed')",
            name="ck_project_deletions_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    project_title: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[ProjectDeletionStatus] = mapped_column(
        Enum(ProjectDeletionStatus, native_enum=False, length=24),
        default=ProjectDeletionStatus.cleanup_pending,
        nullable=False,
        index=True,
    )
    file_manifest: Mapped[str] = mapped_column(Text, nullable=False)
    resource_counts: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(64))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
        Enum(UploadStatus, native_enum=False, length=16),
        default=UploadStatus.pending,
        nullable=False,
        index=True,
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
    __table_args__ = (
        CheckConstraint("progress >= 0 AND progress <= 100", name="ck_processing_jobs_progress"),
        CheckConstraint("max_attempts >= 1", name="ck_processing_jobs_max_attempts"),
    )
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
        Enum(JobStatus, native_enum=False, length=32),
        default=JobStatus.queued,
        nullable=False,
        index=True,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    baseline_ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    result_version: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AiEnhancementTask(Base):
    __tablename__ = "ai_enhancement_tasks"
    __table_args__ = (
        UniqueConstraint("page_id", "idempotency_key", name="uq_ai_enhancement_page_key"),
        UniqueConstraint("processing_job_id", name="uq_ai_enhancement_processing_job"),
        CheckConstraint(
            "enhancement_kind IN ('recommended', 'complex_ocr', 'exam_review', 'book_review')",
            name="ck_ai_enhancement_kind",
        ),
        CheckConstraint(
            "status IN ('queued', 'processing', 'candidate_ready', 'accepted', 'rejected', "
            "'stale', 'failed', 'canceled')",
            name="ck_ai_enhancement_status",
        ),
        CheckConstraint("source_result_version >= 1", name="ck_ai_enhancement_source_version"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_ai_enhancement_confidence",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("scan_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_id: Mapped[str] = mapped_column(
        ForeignKey("scan_pages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    processing_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("processing_jobs.id", ondelete="SET NULL"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    enhancement_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    requested_tasks: Mapped[str] = mapped_column(Text, nullable=False)
    source_result_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="queued", nullable=False, index=True)
    candidate_result: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[str | None] = mapped_column(Text)
    provider_id: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(128))
    confidence: Mapped[float | None] = mapped_column(Float)
    error_code: Mapped[str | None] = mapped_column(String(64))
    accepted_by_user_id: Mapped[str | None] = mapped_column(String(36))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    busy_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class AiProviderState(Base):
    __tablename__ = "ai_provider_states"
    __table_args__ = (
        CheckConstraint(
            "circuit_state IN ('closed', 'open', 'half_open')",
            name="ck_ai_provider_states_circuit_state",
        ),
        CheckConstraint(
            "consecutive_failures >= 0",
            name="ck_ai_provider_states_consecutive_failures",
        ),
    )

    provider_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    circuit_state: Mapped[str] = mapped_column(String(16), default="closed", nullable=False)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    open_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    half_open_lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class AiProviderCall(Base):
    __tablename__ = "ai_provider_calls"
    __table_args__ = (
        CheckConstraint(
            "status IN ('in_progress', 'succeeded', 'failed', 'rejected', 'expired')",
            name="ck_ai_provider_calls_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_ai_provider_calls_attempt_count"),
        CheckConstraint(
            "reserved_cost_microusd >= 0 AND charged_cost_microusd >= 0",
            name="ck_ai_provider_calls_cost",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    enhancement_task_id: Mapped[str | None] = mapped_column(
        ForeignKey("ai_enhancement_tasks.id", ondelete="SET NULL"), index=True
    )
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reserved_cost_microusd: Mapped[int] = mapped_column(Integer, nullable=False)
    charged_cost_microusd: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    request_body_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    response_body_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    lease_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AiProviderAttempt(Base):
    __tablename__ = "ai_provider_attempts"
    __table_args__ = (
        UniqueConstraint("call_id", "attempt_number", name="uq_ai_provider_attempt_number"),
        CheckConstraint("attempt_number >= 1", name="ck_ai_provider_attempt_number"),
        CheckConstraint(
            "outcome IN ('in_progress', 'succeeded', 'failed')",
            name="ck_ai_provider_attempts_outcome",
        ),
        CheckConstraint("charged_cost_microusd >= 0", name="ck_ai_provider_attempts_cost"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    call_id: Mapped[str] = mapped_column(
        ForeignKey("ai_provider_calls.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    charged_cost_microusd: Mapped[int] = mapped_column(Integer, nullable=False)
    request_body_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    response_body_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
