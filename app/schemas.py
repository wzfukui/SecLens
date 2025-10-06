"""Pydantic schemas shared across the API and collectors."""
from datetime import datetime
from typing import Any

from pydantic import AliasChoices, BaseModel, Field, HttpUrl


class SourceInfo(BaseModel):
    source_slug: str = Field(..., description="Internal slug identifying the collector source.")
    external_id: str | None = Field(
        default=None, description="Stable identifier supplied by the data source (if available)."
    )
    origin_url: HttpUrl | None = Field(default=None, description="Canonical URL for the bulletin.")


class ContentInfo(BaseModel):
    title: str
    summary: str | None = None
    body_text: str | None = None
    published_at: datetime | None = None
    language: str | None = None


class BulletinCreate(BaseModel):
    source: SourceInfo
    content: ContentInfo
    severity: str | None = None
    fetched_at: datetime | None = None
    labels: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    extra: dict[str, Any] | None = Field(default=None, description="Normalized source-specific attributes")
    raw: dict[str, Any] | None = Field(default=None, description="Unstructured payload for debugging.")


class BulletinOut(BaseModel):
    id: int
    source_slug: str
    external_id: str | None
    title: str
    summary: str | None
    body_text: str | None
    origin_url: HttpUrl | None
    severity: str | None
    labels: list[str] | None
    topics: list[str] | None
    published_at: datetime | None
    fetched_at: datetime | None
    created_at: datetime
    updated_at: datetime
    extra: dict[str, Any] | None = Field(
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
    description: str | None = None
    sources: list[SourceSectionOut]


class PluginInfo(BaseModel):
    id: int
    slug: str
    name: str
    version: str
    description: str | None
    entrypoint: str
    schedule: str | None
    is_active: bool
    status: str
    created_at: datetime
    updated_at: datetime
    activated_at: datetime | None
    last_run_at: datetime | None
    next_run_at: datetime | None
    manifest: dict[str, Any] | None

    class Config:
        from_attributes = True


class PluginListResponse(BaseModel):
    items: list[PluginInfo]


class PluginActivateRequest(BaseModel):
    activate: bool = True


class PluginUploadRequest(BaseModel):
    filename: str
    content: str  # base64-encoded archive


class PluginRunInfo(BaseModel):
    id: int
    plugin_id: int
    plugin_slug: str
    status: str
    message: str | None
    started_at: datetime
    finished_at: datetime | None

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
    "PluginInfo",
    "PluginListResponse",
    "PluginActivateRequest",
    "PluginUploadRequest",
    "PluginRunInfo",
]
