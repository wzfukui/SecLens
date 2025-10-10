"""FreeBuf RSS community collector plugin."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Sequence
import logging
import xml.etree.ElementTree as ET

import requests

from app.schemas import BulletinCreate, ContentInfo, SourceInfo
from app.time_utils import resolve_published_at

LOGGER = logging.getLogger(__name__)
USER_AGENT = "SecLensFreeBufCollector/1.0"
DEFAULT_FEED_URL = "https://www.freebuf.com/feed"
STATE_FILE_NAME = ".cursor"
DEFAULT_LIMIT = 40
DEFAULT_TOPIC = "security_news"


@dataclass
class FeedEntry:
    slug: str
    title: str
    link: str
    description: str | None
    categories: list[str]
    published_at: datetime | None
    fetched_at: datetime
    time_meta: dict | None
    raw_pub_date: str | None


class FreeBufCollector:
    """Fetch and normalize FreeBuf RSS entries."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        feed_url: str | None = None,
        state_path: Path | None = None,
    ) -> None:
        self.session = session or requests.Session()
        self.feed_url = feed_url or DEFAULT_FEED_URL
        self.state_path = state_path or Path(__file__).resolve().with_name(STATE_FILE_NAME)
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
            }
        )

    # --- Cursor helpers -------------------------------------------------
    def load_cursor(self) -> datetime | None:
        try:
            raw = self.state_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        if not raw:
            return None
        try:
            value = datetime.fromisoformat(raw)
        except ValueError:
            LOGGER.warning("Invalid cursor '%s'", raw)
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def save_cursor(self, value: datetime) -> None:
        value = value.astimezone(timezone.utc)
        self.state_path.write_text(value.isoformat(), encoding="utf-8")

    # --- Fetch ----------------------------------------------------------
    def fetch_feed(self) -> Sequence[FeedEntry]:
        response = self.session.get(self.feed_url, timeout=30)
        response.raise_for_status()
        text = response.text
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise ValueError("Failed to parse FreeBuf RSS feed") from exc

        entries: list[FeedEntry] = []
        fetched_at = datetime.now(timezone.utc)
        for item in root.findall("./channel/item"):
            link = (item.findtext("link") or "").strip()
            if not link:
                continue
            title = (item.findtext("title") or link).strip()
            desc_node = item.findtext("description")
            description = desc_node.strip() if desc_node else None
            raw_pub_date = item.findtext("pubDate")
            published_at, time_meta = resolve_published_at(
                "freebuf_community",
                [(raw_pub_date, "item.pubDate")],
                fetched_at=fetched_at,
            )
            categories = [
                (cat.text or "").strip()
                for cat in item.findall("category")
                if (cat.text or "").strip()
            ]
            slug = link.rstrip("/").rsplit("/", 1)[-1]
            entries.append(
                FeedEntry(
                    slug=slug or link,
                    title=title,
                    link=link,
                    description=description,
                    categories=categories,
                    published_at=published_at,
                    fetched_at=fetched_at,
                    time_meta=time_meta if time_meta else None,
                    raw_pub_date=raw_pub_date.strip() if isinstance(raw_pub_date, str) else None,
                )
            )
        return entries

    # --- Normalize ------------------------------------------------------
    def normalize(self, entry: FeedEntry) -> BulletinCreate:
        source = SourceInfo(
            source_slug="freebuf_community",
            external_id=entry.slug,
            origin_url=entry.link,
        )
        content = ContentInfo(
            title=entry.title,
            summary=entry.description,
            body_text=entry.description,
            published_at=entry.published_at,
            language="zh",
        )

        labels = [f"category:{cat.lower()}" for cat in entry.categories]
        topics = [DEFAULT_TOPIC]

        extra: dict[str, object] = {}
        if entry.categories:
            extra["categories"] = entry.categories
        if entry.time_meta:
            extra["time_meta"] = entry.time_meta
        if entry.raw_pub_date:
            extra["raw_pub_date"] = entry.raw_pub_date

        return BulletinCreate(
            source=source,
            content=content,
            severity=None,
            fetched_at=entry.fetched_at,
            labels=labels,
            topics=topics,
            extra=extra or None,
            raw={
                "feed_entry": {
                    "title": entry.title,
                    "link": entry.link,
                    "description": entry.description,
                    "categories": entry.categories,
                    "published_at": entry.published_at.isoformat() if entry.published_at else None,
                }
            },
        )

    # --- Collection -----------------------------------------------------
    def collect(self, *, limit: int | None = None, force: bool = False) -> List[BulletinCreate]:
        limit = limit or DEFAULT_LIMIT
        cursor = None if force else self.load_cursor()
        entries = list(self.fetch_feed())
        entries.sort(key=lambda item: item.published_at or datetime.min.replace(tzinfo=timezone.utc))

        selected: list[FeedEntry] = []
        for entry in entries:
            if cursor and entry.published_at and entry.published_at <= cursor:
                continue
            selected.append(entry)
        selected = selected[-limit:]

        bulletins = [self.normalize(entry) for entry in selected]
        if bulletins and selected[-1].published_at:
            self.save_cursor(selected[-1].published_at)
        return bulletins


def run(
    ingest_url: str | None = None,
    token: str | None = None,
    *,
    force: bool = False,
) -> tuple[list[BulletinCreate], dict | None]:
    collector = FreeBufCollector()
    bulletins = collector.collect(force=force)
    response_data = None
    if ingest_url and bulletins:
        session = requests.Session()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        session.headers.update(headers)
        payload = [item.model_dump(mode="json") for item in bulletins]
        response = session.post(ingest_url, json=payload, timeout=30)
        response.raise_for_status()
        response_data = response.json()
    return bulletins, response_data


__all__ = ["FreeBufCollector", "run", "FreeBufCollector"]
