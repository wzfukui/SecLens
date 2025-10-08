"""Pydantic schemas shared across the API and collectors."""
from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import AliasChoices, BaseModel, Field, HttpUrl


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
    "PluginVersionInfo",
    "PluginInfo",
    "PluginListResponse",
    "PluginActivateRequest",
    "PluginUploadRequest",
    "PluginRunInfo",
]
