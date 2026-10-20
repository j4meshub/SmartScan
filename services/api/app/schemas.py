from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .models import JobStatus, Role, UploadStatus, UserStatus


class RegisterRequest(BaseModel):
    phone: str
    sms_code: str = Field(min_length=4, max_length=8)
    sms_challenge_id: str | None = Field(default=None, min_length=36, max_length=36)
    username: str = Field(pattern=r"^[A-Za-z0-9_.-]{3,32}$")
    password: str = Field(min_length=10, max_length=128)
    locale: str = "zh-CN"


class SmsChallengeRequest(BaseModel):
    phone: str
    purpose: str = Field(default="registration", pattern=r"^registration$")


class SmsChallengeView(BaseModel):
    challenge_id: str
    expires_at: datetime
    retry_after_seconds: int


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


class PageView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    page_number: int
    size_bytes: int
    mime_type: str
    quality_warning: str | None
    created_at: datetime


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
    error: str | None
    created_at: datetime


class RoleChange(BaseModel):
    role: Role


class StatusChange(BaseModel):
    status: UserStatus
