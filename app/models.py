"""Database models."""
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base


class Bulletin(Base):
    """Represents a normalized bulletin stored via the ingest API."""

    __tablename__ = "bulletins"
    __table_args__ = (
        UniqueConstraint("source_slug", "external_id", name="uq_bulletin_source_external"),
    )

    id = Column(Integer, primary_key=True, index=True)
    source_slug = Column(String(100), nullable=False, index=True)
    external_id = Column(String(128), nullable=True, index=True)
    title = Column(String(500), nullable=False)
    summary = Column(Text, nullable=True)
    body_text = Column(Text, nullable=True)
    origin_url = Column(String(1024), nullable=True)
    severity = Column(String(32), nullable=True)
    labels = Column(JSON, nullable=True)
    topics = Column(JSON, nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    fetched_at = Column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    attributes = Column(JSON, nullable=True)
    raw = Column(JSON, nullable=True)


class Plugin(Base):
    """Metadata for dynamically uploaded collector plugins."""

    __tablename__ = "plugins"

    id = Column(Integer, primary_key=True)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    version = Column(String(50), nullable=False)
    description = Column(Text, nullable=True)
    entrypoint = Column(String(255), nullable=False)
    schedule = Column(String(100), nullable=True)
    manifest = Column(JSON, nullable=True)
    upload_path = Column(String(1024), nullable=False)
    is_active = Column(Boolean, default=False, nullable=False)
    status = Column(String(32), default="pending", nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    activated_at = Column(DateTime(timezone=True), nullable=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True)

    runs = relationship("PluginRun", back_populates="plugin", cascade="all, delete-orphan")


class PluginRun(Base):
    """Execution history for registered plugins."""

    __tablename__ = "plugin_runs"

    id = Column(Integer, primary_key=True)
    plugin_id = Column(Integer, ForeignKey("plugins.id"), nullable=False, index=True)
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(32), nullable=False)
    message = Column(Text, nullable=True)
    output = Column(Text, nullable=True)

    plugin = relationship("Plugin", back_populates="runs")
