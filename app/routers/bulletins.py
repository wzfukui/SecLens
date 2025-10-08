"""Read-only bulletin APIs."""
from datetime import datetime
from typing import Optional

from email.utils import format_datetime
from xml.etree import ElementTree as ET

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app import crud
from app.database import get_db_session
from app.schemas import (
    BulletinListResponse,
    BulletinOut,
    HomeSectionOut,
    PaginationMeta,
    SourceSectionOut,
)
from app.services import build_home_sections

router = APIRouter(prefix="/v1/bulletins", tags=["bulletins"])


@router.get("/home", response_model=list[HomeSectionOut])
def get_home_sections(
    db: Session = Depends(get_db_session),
    limit_per_source: int = Query(default=5, ge=1, le=20),
) -> list[HomeSectionOut]:
    sections = build_home_sections(db, limit_per_source=limit_per_source)
    return [
        HomeSectionOut(
            slug=section.slug,
            title=section.title,
            description=section.description,
            sources=[
                SourceSectionOut(
                    slug=source.slug,
                    title=source.title,
                    total=source.total,
                    items=source.items,
                )
                for source in section.sources
            ],
        )
        for section in sections
    ]


@router.get("", response_model=BulletinListResponse)
def list_bulletins(
    source_slug: Optional[str] = Query(default=None, description="Filter by collector source slug"),
    label: Optional[str] = Query(default=None, description="Filter bulletins that include this label"),
    topic: Optional[str] = Query(default=None, description="Filter bulletins tagged with this topic"),
    since: Optional[datetime] = Query(
        default=None,
        description="Only bulletins published at or after this time",
    ),
    until: Optional[datetime] = Query(
        default=None,
        description="Only bulletins published before or at this time",
    ),
    text: Optional[str] = Query(default=None, description="Match text within bulletin titles"),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db_session),
) -> BulletinListResponse:
    """Return paginated bulletins satisfying optional filters."""

    items, total = crud.list_bulletins(
        db,
        source_slug=source_slug,
        label=label,
        topic=topic,
        since=since,
        until=until,
        text=text,
        limit=limit,
        offset=offset,
    )
    return BulletinListResponse(
        items=[BulletinOut.model_validate(item) for item in items],
        pagination=PaginationMeta(total=total, limit=limit, offset=offset),
    )


@router.get("/rss", response_class=Response, tags=["rss"])
def bulletins_rss(
    limit: int = Query(default=20, ge=1, le=100),
    source_slug: Optional[str] = Query(default=None),
    db: Session = Depends(get_db_session),
) -> Response:
    """Generate an RSS feed for recent bulletins."""

    items, _ = crud.list_bulletins(db, limit=limit, source_slug=source_slug)
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "SecLens Bulletins"
    ET.SubElement(channel, "link").text = "https://localhost"
    description = "Latest advisories collected by SecLens."
    if source_slug:
        description = f"Latest bulletins from {source_slug}."
    ET.SubElement(channel, "description").text = description

    for bulletin in items:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = bulletin.title
        link = bulletin.origin_url or f"https://localhost/v1/bulletins/{bulletin.id}"
        ET.SubElement(item, "link").text = link
        description = bulletin.summary or (bulletin.body_text[:400] if bulletin.body_text else None)
        if description:
            ET.SubElement(item, "description").text = description
        if bulletin.published_at:
            ET.SubElement(item, "pubDate").text = format_datetime(bulletin.published_at)
        guid = ET.SubElement(item, "guid")
        guid.text = f"seclens:{bulletin.id}"
        guid.set("isPermaLink", "false")

    xml_bytes = ET.tostring(rss, encoding="utf-8", xml_declaration=True)
    return Response(content=xml_bytes, media_type="application/rss+xml; charset=utf-8")


@router.get("/{bulletin_id}", response_model=BulletinOut)
def get_bulletin(bulletin_id: int, db: Session = Depends(get_db_session)) -> BulletinOut:
    bulletin = crud.get_bulletin(db, bulletin_id)
    if not bulletin:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bulletin not found")
    return BulletinOut.model_validate(bulletin)
