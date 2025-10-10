"""Database models."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Sequence

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_values(values: Iterable[str] | None) -> list[str]:
    unique: list[str] = []
    if not values:
        return unique
    for value in values:
        if not value:
            continue
        if value not in unique:
            unique.append(value)
    return unique


class User(Base):
    """End-user account with authentication and VIP metadata."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    display_name = Column(String(200), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)
    vip_activated_at = Column(DateTime(timezone=True), nullable=True)
    vip_expires_at = Column(DateTime(timezone=True), nullable=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)

    notification_settings = relationship(
        "UserNotificationSetting",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    push_rules = relationship("UserPushRule", back_populates="user", cascade="all, delete-orphan")
    subscriptions = relationship("UserSubscription", back_populates="user", cascade="all, delete-orphan")
    activation_logs = relationship("ActivationCode", back_populates="used_by_user")


class ActivationCode(Base):
    """VIP activation code purchased via third-party channels."""

    __tablename__ = "activation_codes"

    id = Column(Integer, primary_key=True)
    code = Column(String(64), unique=True, nullable=False, index=True)
    batch = Column(String(50), nullable=True)
    notes = Column(String(255), nullable=True)
    is_used = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    used_at = Column(DateTime(timezone=True), nullable=True)
    used_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    used_by_user = relationship("User", back_populates="activation_logs")


class UserNotificationSetting(Base):
    """Preferred notification channels for a user."""

    __tablename__ = "user_notification_settings"

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    webhook_url = Column(String(1024), nullable=True)
    notify_email = Column(String(255), nullable=True)
    send_webhook = Column(Boolean, default=False, nullable=False)
    send_email = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    user = relationship("User", back_populates="notification_settings")


class UserPushRule(Base):
    """Keyword-based trigger that initiates notifications."""

    __tablename__ = "user_push_rules"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_user_push_rule_name"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    keyword = Column(String(120), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    notify_via_webhook = Column(Boolean, default=True, nullable=False)
    notify_via_email = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    user = relationship("User", back_populates="push_rules")


class UserSubscription(Base):
    """Customized RSS subscription configuration."""

    __tablename__ = "user_subscriptions"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_user_subscription_name"),
        UniqueConstraint("token", name="uq_user_subscription_token"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    token = Column(String(64), nullable=False, index=True)
    keyword_filter = Column(String(200), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    user = relationship("User", back_populates="subscriptions")
    channel_links = relationship(
        "UserSubscriptionChannel",
        back_populates="subscription",
        cascade="all, delete-orphan",
        lazy="joined",
    )

    @property
    def channel_slugs(self) -> list[str]:
        return [link.plugin_slug for link in self.channel_links]


class UserSubscriptionChannel(Base):
    """Link table between subscriptions and plugin channels."""

    __tablename__ = "user_subscription_channels"

    subscription_id = Column(
        Integer,
        ForeignKey("user_subscriptions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    plugin_slug = Column(String(100), primary_key=True)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    subscription = relationship("UserSubscription", back_populates="channel_links")


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
    published_at = Column(DateTime(timezone=True), nullable=True)
    fetched_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=_now,
        onupdate=_now,
        nullable=False,
    )
    attributes = Column(JSON, nullable=True)
    raw = Column(JSON, nullable=True)

    label_links = relationship(
        "BulletinLabel",
        cascade="all, delete-orphan",
        lazy="selectin",
        back_populates="bulletin",
    )
    topic_links = relationship(
        "BulletinTopic",
        cascade="all, delete-orphan",
        lazy="selectin",
        back_populates="bulletin",
    )

    @property
    def labels(self) -> list[str]:
        return [link.label for link in self.label_links]

    @labels.setter
    def labels(self, values: Sequence[str] | None) -> None:
        normalized = _normalize_values(values)
        self.label_links = [BulletinLabel(label=value) for value in normalized]

    @property
    def topics(self) -> list[str]:
        return [link.topic for link in self.topic_links]

    @topics.setter
    def topics(self, values: Sequence[str] | None) -> None:
        normalized = _normalize_values(values)
        self.topic_links = [BulletinTopic(topic=value) for value in normalized]


class BulletinLabel(Base):
    """Secondary table storing bulletin labels."""

    __tablename__ = "bulletin_labels"

    bulletin_id = Column(
        Integer,
        ForeignKey("bulletins.id", ondelete="CASCADE"),
        primary_key=True,
    )
    label = Column(String(100), primary_key=True)
    bulletin = relationship("Bulletin", back_populates="label_links")


class BulletinTopic(Base):
    """Secondary table storing bulletin topics."""

    __tablename__ = "bulletin_topics"

    bulletin_id = Column(
        Integer,
        ForeignKey("bulletins.id", ondelete="CASCADE"),
        primary_key=True,
    )
    topic = Column(String(100), primary_key=True)
    bulletin = relationship("Bulletin", back_populates="topic_links")


class Plugin(Base):
    """Metadata for collector plugins (identity-level)."""

    __tablename__ = "plugins"

    id = Column(Integer, primary_key=True)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    is_enabled = Column(Boolean, default=True, nullable=False)
    display_name = Column(String(200), nullable=True)
    group_slug = Column(String(100), nullable=True, index=True)
    group_title = Column(String(200), nullable=True)
    group_description = Column(Text, nullable=True)
    group_order = Column(Integer, nullable=True)
    source_order = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)
    current_version_id = Column(Integer, ForeignKey("plugin_versions.id"), nullable=True)

    versions = relationship(
        "PluginVersion",
        back_populates="plugin",
        cascade="all, delete-orphan",
        order_by="PluginVersion.created_at.desc()",
        foreign_keys="PluginVersion.plugin_id",
    )
    runs = relationship("PluginRun", back_populates="plugin", cascade="all, delete-orphan")
    current_version = relationship(
        "PluginVersion",
        foreign_keys=[current_version_id],
        post_update=True,
    )


class PluginVersion(Base):
    """Specific uploaded version of a plugin."""

    __tablename__ = "plugin_versions"
    __table_args__ = (
        UniqueConstraint("plugin_id", "version", name="uq_plugin_version"),
    )

    id = Column(Integer, primary_key=True)
    plugin_id = Column(
        Integer,
        ForeignKey("plugins.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version = Column(String(50), nullable=False)
    entrypoint = Column(String(255), nullable=False)
    schedule = Column(String(100), nullable=True)
    manifest = Column(JSON, nullable=True)
    upload_path = Column(String(1024), nullable=False)
    status = Column(String(32), default="uploaded", nullable=False)
    is_active = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)
    activated_at = Column(DateTime(timezone=True), nullable=True)
    deactivated_at = Column(DateTime(timezone=True), nullable=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True)

    plugin = relationship(
        "Plugin",
        back_populates="versions",
        foreign_keys=[plugin_id],
    )
    runs = relationship("PluginRun", back_populates="version", cascade="all, delete-orphan")


class PluginRun(Base):
    """Execution history for registered plugins."""

    __tablename__ = "plugin_runs"

    id = Column(Integer, primary_key=True)
    plugin_id = Column(
        Integer,
        ForeignKey("plugins.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plugin_version_id = Column(
        Integer,
        ForeignKey("plugin_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    started_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(32), nullable=False)
    message = Column(Text, nullable=True)
    output = Column(Text, nullable=True)

    plugin = relationship("Plugin", back_populates="runs")
    version = relationship("PluginVersion", back_populates="runs")


__all__ = [
    "Bulletin",
    "BulletinLabel",
    "BulletinTopic",
    "Plugin",
    "PluginVersion",
    "PluginRun",
]
