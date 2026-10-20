from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import (
    AccountDeletionStatus,
    JobStatus,
    PageReviewStatus,
    Role,
    UploadStatus,
    UserStatus,
)


class RegisterRequest(BaseModel):
    phone: str
    sms_code: str = Field(min_length=4, max_length=8)
    sms_challenge_id: str | None = Field(default=None, min_length=36, max_length=36)
    username: str = Field(pattern=r"^[A-Za-z0-9_.-]{3,32}$")
    password: str = Field(min_length=10, max_length=128)
    locale: str = "zh-CN"


class SmsChallengeRequest(BaseModel):
    phone: str
    purpose: str = Field(
        default="registration",
        pattern=(
            r"^(registration|wecom_binding|account_merge|account_deletion|"
            r"account_deletion_cancel)$"
        ),
    )


class SmsChallengeView(BaseModel):
    challenge_id: str
    expires_at: datetime
    retry_after_seconds: int


class WeComAuthorizeView(BaseModel):
    authorization_url: str
    expires_at: datetime


class WeComCallbackView(BaseModel):
    action: str
    access_token: str | None = None
    expires_at: datetime | None = None
    binding_ticket: str | None = None
    binding_expires_at: datetime | None = None


class WeComPhoneBindRequest(BaseModel):
    binding_ticket: str = Field(min_length=32, max_length=256)
    phone: str
    sms_challenge_id: str = Field(min_length=36, max_length=36)
    sms_code: str = Field(min_length=4, max_length=8)


class AccountMergeRequest(BaseModel):
    phone: str
    sms_challenge_id: str = Field(min_length=36, max_length=36)
    sms_code: str = Field(min_length=4, max_length=8)
    idempotency_key: str = Field(
        min_length=16,
        max_length=100,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )


class AccountMergeView(BaseModel):
    merge_id: str
    canonical_user_id: str
    source_user_id: str
    result: str
    require_reauthentication: bool = True
    merged_at: datetime


class LoginRequest(BaseModel):
    username: str
    password: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    refresh_token: str | None = None
    refresh_expires_at: datetime | None = None
    session_id: str | None = None
    device_id: str | None = None


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=64, max_length=256)


class DeviceSessionView(BaseModel):
    id: str
    device_id: str
    device_name: str
    platform: str
    current: bool
    created_at: datetime
    last_seen_at: datetime
    access_expires_at: datetime


class AccountDeletionRequestPayload(BaseModel):
    phone: str
    sms_challenge_id: str = Field(min_length=36, max_length=36)
    sms_code: str = Field(min_length=4, max_length=8)


class AccountDeletionCancelPayload(AccountDeletionRequestPayload):
    pass


class AccountDeletionView(BaseModel):
    id: str
    status: AccountDeletionStatus
    requested_at: datetime
    execute_after: datetime
    canceled_at: datetime | None = None
    completed_at: datetime | None = None


class AdminAccountDeletionRequestPayload(BaseModel):
    confirm_username: str = Field(min_length=3, max_length=64)
    reason: str = Field(min_length=3, max_length=500)


class AdminAccountDeletionCancelPayload(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class AdminAccountDeletionView(BaseModel):
    id: str
    user_id: str
    username: str
    status: AccountDeletionStatus
    request_source: str
    requested_by_user_id: str
    reason: str | None
    cancellation_reason: str | None
    requested_at: datetime
    execute_after: datetime
    canceled_at: datetime | None
    completed_at: datetime | None
    attempts: int
    last_error: str | None


class AuditLogView(BaseModel):
    id: str
    actor_user_id: str | None
    target_user_id: str | None
    object_type: str
    object_id: str | None
    action: str
    result: str
    request_id: str | None
    ip: str | None
    user_agent: str | None
    created_at: datetime


class UserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    username: str
    phone_masked: str
    role: Role
    status: UserStatus
    locale: str
    must_change_password: bool
    created_at: datetime


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    mode: str = Field(default="document", pattern=r"^(document|exam|book)$")
    reading_order: str = Field(default="ltr", pattern=r"^(ltr|rtl)$")


class ProjectView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    owner_user_id: str
    title: str
    mode: str
    reading_order: str
    created_at: datetime
    updated_at: datetime


class PageResultView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    version: int
    result_type: str
    mime_type: str
    sha256: str | None
    size_bytes: int | None
    rotation_degrees: int
    processor_version: str
    created_at: datetime


class PageView(BaseModel):
    id: str
    project_id: str
    page_number: int
    size_bytes: int
    mime_type: str
    original_mime_type: str
    quality_warning: str | None
    quality_score: float | None
    quality_details: dict[str, object] | None
    rotation_degrees: int
    active_result_version: int
    review_status: PageReviewStatus
    review_reason: str | None
    reviewed_by_user_id: str | None
    reviewed_at: datetime | None
    active_result: PageResultView | None
    created_at: datetime
    updated_at: datetime


class PageRotationRequest(BaseModel):
    degrees: Literal[90, 180, 270]


class PageReviewUpdate(BaseModel):
    status: Literal["pending", "confirmed"]
    note: str | None = Field(default=None, max_length=160)


class UploadCreate(BaseModel):
    project_id: str
    file_name: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(pattern=r"^image/(jpeg|png|webp|heic)$")
    size_bytes: int = Field(gt=15)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    idempotency_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")


class UploadView(BaseModel):
    id: str
    project_id: str
    file_name: str
    mime_type: str
    size_bytes: int
    chunk_size: int
    total_chunks: int
    received_chunks: list[int]
    status: UploadStatus
    page_id: str | None
    expires_at: datetime


class ChunkReceipt(BaseModel):
    upload_id: str
    chunk_index: int
    size_bytes: int
    sha256: str


class JobView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    page_id: str | None
    kind: str
    status: JobStatus
    attempts: int
    max_attempts: int
    priority: int
    progress: int
    available_at: datetime
    lease_until: datetime | None
    heartbeat_at: datetime | None
    started_at: datetime | None
    baseline_ready_at: datetime | None
    completed_at: datetime | None
    cancel_requested_at: datetime | None
    canceled_at: datetime | None
    error_code: str | None
    error: str | None
    result_version: int | None
    created_at: datetime
    updated_at: datetime


class RoleChange(BaseModel):
    role: Role


class StatusChange(BaseModel):
    status: UserStatus
