"""Pydantic schemas shared across the API and collectors."""
from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import AliasChoices, BaseModel, EmailStr, Field, HttpUrl


class SourceInfo(BaseModel):
    source_slug: str = Field(
        ...,
        description="Internal slug identifying the collector source.",
    )
    external_id: Optional[str] = Field(
        default=None,
        description="Stable identifier supplied by the data source (if available).",
    )
    origin_url: Optional[HttpUrl] = Field(
        default=None,
        description="Canonical URL for the bulletin.",
    )


class ContentInfo(BaseModel):
    title: str
    summary: Optional[str] = None
    body_text: Optional[str] = None
    published_at: Optional[datetime] = None
    language: Optional[str] = None


class BulletinCreate(BaseModel):
    source: SourceInfo
    content: ContentInfo
    severity: Optional[str] = None
    fetched_at: Optional[datetime] = None
    labels: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    extra: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Normalized source-specific attributes",
    )
    raw: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Unstructured payload for debugging.",
    )


class BulletinOut(BaseModel):
    id: int
    source_slug: str
    external_id: Optional[str]
    title: str
    summary: Optional[str]
    body_text: Optional[str]
    origin_url: Optional[HttpUrl]
    severity: Optional[str]
    labels: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    published_at: Optional[datetime]
    fetched_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    extra: Optional[Dict[str, Any]] = Field(
        default=None,
        validation_alias=AliasChoices("attributes", "extra"),
        serialization_alias="extra",
    )

    class Config:
        from_attributes = True
        populate_by_name = True


class IngestResponse(BaseModel):
    accepted: int
    duplicates: int


class PaginationMeta(BaseModel):
    total: int
    limit: int
    offset: int


class BulletinListResponse(BaseModel):
    items: list[BulletinOut]
    pagination: PaginationMeta


class SourceSectionOut(BaseModel):
    slug: str
    title: str
    total: int
    items: list[BulletinOut]


class HomeSectionOut(BaseModel):
    slug: str
    title: str
    description: Optional[str] = None
    sources: list[SourceSectionOut]


class UserBase(BaseModel):
    email: EmailStr
    display_name: Optional[str] = Field(default=None, max_length=200)


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)
    invitation_code: Optional[str] = Field(default=None, min_length=5, max_length=16)


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenRefreshRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    id: int
    email: EmailStr
    display_name: Optional[str]
    vip_activated_at: Optional[datetime]
    vip_expires_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    is_admin: bool

    class Config:
        from_attributes = True


class ActivationLogOut(BaseModel):
    code: str
    batch: Optional[str]
    notes: Optional[str]
    created_at: datetime
    used_at: Optional[datetime]
    expires_at: Optional[datetime]

    class Config:
        from_attributes = True


class VIPStatus(BaseModel):
    is_vip: bool
    vip_activated_at: Optional[datetime]
    vip_expires_at: Optional[datetime]
    remaining_days: Optional[int]
    history: list[ActivationLogOut] = Field(default_factory=list)


class InvitationInviteeOut(BaseModel):
    id: int  # 添加用户ID字段
    display_label: str
    invited_at: datetime
    has_gift_vip: bool = False  # 添加是否已被赠送VIP的状态


class InvitationSummaryOut(BaseModel):
    invite_code: str
    invite_url: str
    total: int
    limit: int
    offset: int
    invitees: list[InvitationInviteeOut]


class ActivationRequest(BaseModel):
    code: str = Field(min_length=6, max_length=64)


class NotificationSettingUpdate(BaseModel):
    webhook_url: Optional[HttpUrl] = None
    notify_email: Optional[EmailStr] = None
    send_webhook: bool = False
    send_email: bool = False


class NotificationSettingOut(NotificationSettingUpdate):
    updated_at: datetime

    class Config:
        from_attributes = True


class PushRuleBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    keyword: str = Field(min_length=1, max_length=120)
    is_active: bool = True
    notify_via_webhook: bool = True
    notify_via_email: bool = False


class PushRuleCreate(PushRuleBase):
    pass


class PushRuleUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    keyword: Optional[str] = Field(default=None, min_length=1, max_length=120)
    is_active: Optional[bool] = None
    notify_via_webhook: Optional[bool] = None
    notify_via_email: Optional[bool] = None


class PushRuleOut(PushRuleBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SubscriptionBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    channel_slugs: list[str] = Field(default_factory=list)
    keyword_filter: Optional[str] = Field(default=None, max_length=200)
    is_active: bool = True


class SubscriptionCreate(SubscriptionBase):
    pass


class SubscriptionUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    channel_slugs: Optional[list[str]] = None
    keyword_filter: Optional[str] = Field(default=None, max_length=200)
    is_active: Optional[bool] = None


class SubscriptionOut(SubscriptionBase):
    id: int
    token: str
    created_at: datetime
    updated_at: datetime
    rss_url: Optional[HttpUrl] = None

    class Config:
        from_attributes = True

class PluginVersionInfo(BaseModel):
    id: int
    plugin_id: int
    version: str
    entrypoint: str
    schedule: Optional[str]
    status: str
    is_active: bool
    manifest: Optional[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime
    activated_at: Optional[datetime]
    deactivated_at: Optional[datetime]
    last_run_at: Optional[datetime]
    next_run_at: Optional[datetime]

    class Config:
        from_attributes = True


class PluginInfo(BaseModel):
    id: int
    slug: str
    name: str
    description: Optional[str]
    display_name: Optional[str]
    group_slug: Optional[str]
    group_title: Optional[str]
    group_description: Optional[str]
    group_order: Optional[int]
    source_order: Optional[int]
    created_at: datetime
    updated_at: datetime
    is_enabled: bool
    current_version: Optional[PluginVersionInfo] = None
    versions: list[PluginVersionInfo] = Field(default_factory=list)

    class Config:
        from_attributes = True


class PluginListResponse(BaseModel):
    items: list[PluginInfo]


class PluginActivateRequest(BaseModel):
    activate: bool = True
    version_id: Optional[int] = Field(
        default=None,
        description="Activate a specific version. Defaults to plugin's latest uploaded version.",
    )


class PluginUploadRequest(BaseModel):
    filename: str
    content: str  # base64-encoded archive


class PluginRunInfo(BaseModel):
    id: int
    plugin_id: int
    plugin_slug: str
    plugin_version_id: Optional[int]
    plugin_version: Optional[str]
    status: str
    message: Optional[str]
    started_at: datetime
    finished_at: Optional[datetime]

__all__ = [
    "SourceInfo",
    "ContentInfo",
    "BulletinCreate",
    "BulletinOut",
    "IngestResponse",
    "PaginationMeta",
    "BulletinListResponse",
    "SourceSectionOut",
    "HomeSectionOut",
    "UserCreate",
    "UserLoginRequest",
    "TokenPair",
    "TokenRefreshRequest",
    "UserOut",
    "ActivationLogOut",
    "VIPStatus",
    "ActivationRequest",
    "NotificationSettingUpdate",
    "NotificationSettingOut",
    "PushRuleCreate",
    "PushRuleUpdate",
    "PushRuleOut",
    "SubscriptionCreate",
    "SubscriptionUpdate",
    "SubscriptionOut",
    "PluginVersionInfo",
    "PluginInfo",
    "PluginListResponse",
    "PluginActivateRequest",
    "PluginUploadRequest",
    "PluginRunInfo",
]
