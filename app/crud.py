"""Database helper functions for ingest API."""
from datetime import datetime, timezone
from typing import Optional, Tuple

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload

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
        existing.labels = payload.labels
        existing.topics = payload.topics
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
            published_at=payload.content.published_at,
            fetched_at=payload.fetched_at or now,
            created_at=now,
            updated_at=now,
            attributes=payload.extra,
            raw=payload.raw,
        )
        bulletin.labels = payload.labels
        bulletin.topics = payload.topics
        session.add(bulletin)
        created = True
    return bulletin, created


def _base_bulletin_query() -> Select:
    return select(models.Bulletin).options(
        selectinload(models.Bulletin.label_links),
        selectinload(models.Bulletin.topic_links),
    )


def list_bulletins(
    session: Session,
    *,
    source_slug: Optional[str] = None,
    label: Optional[str] = None,
    topic: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    text: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[models.Bulletin], int]:
    """Return bulletins matching filters with a total count."""

    base_query = _base_bulletin_query()

    if source_slug:
        base_query = base_query.where(models.Bulletin.source_slug == source_slug)
    if label:
        base_query = base_query.join(models.Bulletin.label_links).where(models.BulletinLabel.label == label)
    if topic:
        base_query = base_query.join(models.Bulletin.topic_links).where(models.BulletinTopic.topic == topic)
    if since:
        base_query = base_query.where(models.Bulletin.published_at >= since)
    if until:
        base_query = base_query.where(models.Bulletin.published_at <= until)
    if text:
        like_pattern = f"%{text}%"
        base_query = base_query.where(models.Bulletin.title.ilike(like_pattern))

    if label or topic:
        base_query = base_query.distinct(models.Bulletin.id)

    total_stmt = select(func.count()).select_from(base_query.subquery())
    total = session.execute(total_stmt).scalar_one()

    safe_limit = max(1, min(limit, 200))
    safe_offset = max(0, offset)

    order_columns = [
        models.Bulletin.published_at.desc().nullslast(),
        models.Bulletin.id.desc(),
    ]

    if label or topic:
        query = (
            select(models.Bulletin)
            .where(models.Bulletin.id.in_(base_query.with_only_columns(models.Bulletin.id)))
            .order_by(*order_columns)
        )
    else:
        query = base_query.order_by(*order_columns)

    results = session.scalars(query.limit(safe_limit).offset(safe_offset)).all()
    return results, int(total)


def get_bulletin(session: Session, bulletin_id: int) -> Optional[models.Bulletin]:
    """Fetch a single bulletin by primary key."""

    stmt = _base_bulletin_query().where(models.Bulletin.id == bulletin_id)
    return session.scalars(stmt).first()
