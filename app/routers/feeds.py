"""RSS feeds for user subscriptions."""
from __future__ import annotations

from datetime import datetime, timezone
from xml.etree import ElementTree as ET

from email.utils import format_datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import crud, models
from app.database import get_db_session
from app.services.subscriptions import filter_bulletins_for_subscription
from app.utils.datetime import to_display_tz


router = APIRouter(tags=["rss"])


@router.get("/rss/{token}", response_class=Response, name="user_subscription_feed")
def user_subscription_feed(
    request: Request,
    token: str,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db_session),
) -> Response:
    """Generate RSS feed for a user's custom subscription."""

    subscription = crud.get_subscription_by_token(db, token)
    if not subscription or not subscription.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订阅不存在或已停用")
    user = subscription.user
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="关联用户不存在")
    expires_at = user.vip_expires_at
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    now_utc = datetime.now(timezone.utc)
    has_active_vip = bool(expires_at and expires_at > now_utc)

    stmt = (
        select(models.Bulletin)
        .order_by(
            models.Bulletin.published_at.desc().nullslast(),
            models.Bulletin.id.desc(),
        )
        .limit(limit)
    )
    channel_slugs = subscription.channel_slugs
    if channel_slugs:
        stmt = stmt.where(models.Bulletin.source_slug.in_(channel_slugs))
    bulletins = db.scalars(stmt).all()
    filtered = filter_bulletins_for_subscription(bulletins, subscription) if has_active_vip else []

    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    title = f"SecLens 订阅 - {subscription.name}"
    base_url = str(request.base_url) if request else "https://seclens.local/"
    ET.SubElement(channel, "title").text = title
    ET.SubElement(channel, "link").text = base_url
    description_parts = ["SecLens 自定义订阅"]
    if channel_slugs:
        description_parts.append(f"渠道: {', '.join(channel_slugs)}")
    if subscription.keyword_filter:
        description_parts.append(f"关键词: {subscription.keyword_filter}")
    if not has_active_vip:
        description_parts.append("状态: 当前账户无有效的订阅服务，请激活 VIP 后再访问。")
    ET.SubElement(channel, "description").text = " | ".join(description_parts)
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(datetime.now(timezone.utc))

    for bulletin in filtered:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = bulletin.title
        link = str(bulletin.origin_url) if bulletin.origin_url else f"{base_url.rstrip('/')}/v1/bulletins/{bulletin.id}"
        ET.SubElement(item, "link").text = link
        summary = bulletin.summary or (bulletin.body_text[:400] if bulletin.body_text else "")
        if summary:
            ET.SubElement(item, "description").text = summary
        if bulletin.published_at:
            ET.SubElement(item, "pubDate").text = format_datetime(to_display_tz(bulletin.published_at))
        guid = ET.SubElement(item, "guid")
        guid.text = f"seclens:subscription:{subscription.id}:{bulletin.id}"
        guid.set("isPermaLink", "false")

    xml_bytes = ET.tostring(rss, encoding="utf-8", xml_declaration=True)
    return Response(content=xml_bytes, media_type="application/rss+xml; charset=utf-8")
