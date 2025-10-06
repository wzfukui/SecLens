"""Database helper functions for ingest API."""
from datetime import datetime, timezone
from typing import Optional, Tuple

from sqlalchemy import Select, func, select, String
from sqlalchemy.orm import Session

from app import models
from app.schemas import BulletinCreate


def upsert_bulletin(session: Session, payload: BulletinCreate) -> Tuple[models.Bulletin, bool]:
    """Insert a bulletin or update an existing record.

    Returns a tuple of (bulletin, created_flag).
    """

    existing = None
    if payload.source.external_id:
        stmt = select(models.Bulletin).where(
            models.Bulletin.source_slug == payload.source.source_slug,
            models.Bulletin.external_id == payload.source.external_id,
        )
        existing = session.scalars(stmt).first()
    now = datetime.now(timezone.utc)
    if existing:
        existing.title = payload.content.title
        existing.summary = payload.content.summary
        existing.body_text = payload.content.body_text
        existing.origin_url = str(payload.source.origin_url) if payload.source.origin_url else None
        existing.severity = payload.severity
        existing.labels = payload.labels or None
        existing.topics = payload.topics or None
        existing.attributes = payload.extra or existing.attributes
        existing.published_at = payload.content.published_at
        existing.fetched_at = payload.fetched_at or existing.fetched_at or now
        existing.updated_at = now
        existing.raw = payload.raw
        created = False
        bulletin = existing
    else:
        bulletin = models.Bulletin(
            source_slug=payload.source.source_slug,
            external_id=payload.source.external_id,
            title=payload.content.title,
            summary=payload.content.summary,
            body_text=payload.content.body_text,
            origin_url=str(payload.source.origin_url) if payload.source.origin_url else None,
            severity=payload.severity,
            labels=payload.labels or None,
            topics=payload.topics or None,
            published_at=payload.content.published_at,
            fetched_at=payload.fetched_at or now,
            created_at=now,
            updated_at=now,
            attributes=payload.extra,
            raw=payload.raw,
        )
        session.add(bulletin)
        created = True
    return bulletin, created


def _base_bulletin_query() -> Select:
    return select(models.Bulletin)


def list_bulletins(
    session: Session,
    *,
    source_slug: str | None = None,
    label: str | None = None,
    topic: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    text: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[models.Bulletin], int]:
    """Return bulletins matching filters with a total count."""

    base_query = _base_bulletin_query()

    filters: list = []

    if source_slug:
        filters.append(models.Bulletin.source_slug == source_slug)
    bind = session.get_bind()
    dialect = bind.dialect.name if bind is not None else ""

    def _like_pattern(value: str) -> str:
        return f'%"{value}"%'

    if label:
        filters.append(models.Bulletin.labels.cast(String).like(_like_pattern(label)))
    if topic:
        filters.append(models.Bulletin.topics.cast(String).like(_like_pattern(topic)))
    if since:
        filters.append(models.Bulletin.published_at >= since)
    if until:
        filters.append(models.Bulletin.published_at <= until)
    if text:
        like_pattern = f"%{text}%"
        filters.append(models.Bulletin.title.ilike(like_pattern))

    if filters:
        base_query = base_query.where(*filters)

    total_stmt = select(func.count()).select_from(base_query.subquery())
    total = session.execute(total_stmt).scalar_one()

    safe_limit = max(1, min(limit, 200))
    safe_offset = max(0, offset)

    query = base_query.order_by(models.Bulletin.published_at.desc(), models.Bulletin.id.desc())
    results = session.scalars(query.limit(safe_limit).offset(safe_offset)).all()
    return results, int(total)


def get_bulletin(session: Session, bulletin_id: int) -> Optional[models.Bulletin]:
    """Fetch a single bulletin by primary key."""

    stmt = _base_bulletin_query().where(models.Bulletin.id == bulletin_id)
    return session.scalars(stmt).first()
