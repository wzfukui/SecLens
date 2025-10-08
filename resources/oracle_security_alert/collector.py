"""Oracle Security Alert collector plugin."""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import List, Sequence
from urllib.parse import urlparse

import requests

from app.schemas import BulletinCreate, ContentInfo, SourceInfo

LOGGER = logging.getLogger(__name__)
FEED_URL = "https://www.oracle.com/ocom/groups/public/@otn/documents/webcontent/rss-otn-sec.xml"
STATE_FILE_NAME = ".cursor"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class FeedEntry:
    guid: str
    title: str
    link: str
    description: str | None
    published_at: datetime | None


class OracleSecurityCollector:
    """Fetch and normalize Oracle Security Alert RSS entries."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        feed_url: str | None = None,
        state_path: Path | None = None,
    ) -> None:
        self.session = session or requests.Session()
        self.feed_url = feed_url or FEED_URL
        self.state_path = state_path or Path(__file__).resolve().with_name(STATE_FILE_NAME)
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })

    # Cursor helpers --------------------------------------------------
    def load_cursor(self) -> datetime | None:
        try:
            raw = self.state_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            LOGGER.warning("Invalid cursor value '%s'", raw)
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def save_cursor(self, value: datetime) -> None:
        value = value.astimezone(timezone.utc)
        self.state_path.write_text(value.isoformat(), encoding="utf-8")

    # Fetch -----------------------------------------------------------
    def fetch_feed(self) -> Sequence[FeedEntry]:
        response = self.session.get(self.feed_url, timeout=30)
        response.raise_for_status()
        try:
            root = ET.fromstring(response.text)
        except ET.ParseError as exc:
            raise ValueError("Failed to parse Oracle Security Alert RSS feed") from exc

        items: list[FeedEntry] = []
        for item in root.findall("./channel/item"):
            link = (item.findtext("link") or "").strip()
            title = (item.findtext("title") or link).strip()
            description = item.findtext("description") or None
            guid = (item.findtext("guid") or link or title).strip()
            published_at = self._parse_pub_date(item.findtext("pubDate"))
            if not link:
                continue
            items.append(
                FeedEntry(
                    guid=guid or link,
                    title=title or link,
                    link=link,
                    description=description.strip() if description else None,
                    published_at=published_at,
                )
            )
        return items

    @staticmethod
    def _parse_pub_date(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            LOGGER.warning("Invalid pubDate '%s'", value)
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    # Normalize -------------------------------------------------------
    def normalize(self, entry: FeedEntry) -> BulletinCreate:
        origin_url = entry.link if self._is_valid_url(entry.link) else None
        source = SourceInfo(
            source_slug="oracle_security_alert",
            external_id=entry.guid or entry.link,
            origin_url=origin_url,
        )
        content = ContentInfo(
            title=entry.title,
            summary=entry.description,
            body_text=entry.description,
            published_at=entry.published_at,
            language="en",
        )
        topics = ["vendor-update"]
        labels = ["vendor:oracle"]
        extra = {
            "guid": entry.guid,
            "link": entry.link,
        }
        return BulletinCreate(
            source=source,
            content=content,
            severity=None,
            fetched_at=datetime.now(timezone.utc),
            labels=labels,
            topics=topics,
            extra=extra,
            raw={
                "feed_entry": {
                    "title": entry.title,
                    "link": entry.link,
                    "description": entry.description,
                    "published_at": entry.published_at.isoformat() if entry.published_at else None,
                    "guid": entry.guid,
                }
            },
        )

    # Collect ---------------------------------------------------------
    def collect(self, *, limit: int | None = None, force: bool = False) -> List[BulletinCreate]:
        cursor = None if force else self.load_cursor()
        entries = list(self.fetch_feed())
        entries.sort(key=lambda item: item.published_at or datetime.min.replace(tzinfo=timezone.utc))

        selected: list[FeedEntry] = []
        for entry in entries:
            if cursor and entry.published_at and entry.published_at <= cursor:
                continue
            selected.append(entry)
        if limit is not None and limit > 0:
            selected = selected[-limit:]

        dedup: dict[str, BulletinCreate] = {}
        order: list[str] = []
        for entry in selected:
            bulletin = self.normalize(entry)
            external_id = bulletin.source.external_id or bulletin.source.origin_url or bulletin.content.title
            if external_id in dedup:
                dedup[external_id] = bulletin
            else:
                dedup[external_id] = bulletin
                order.append(external_id)

        bulletins = [dedup[key] for key in order]
        if bulletins and selected[-1].published_at and not force:
            self.save_cursor(selected[-1].published_at)
        return bulletins

    @staticmethod
    def _is_valid_url(value: str | None) -> bool:
        if not value:
            return False
        parsed = urlparse(value.strip())
        return bool(parsed.scheme and parsed.netloc)


def run(
    ingest_url: str | None = None,
    token: str | None = None,
    *,
    limit: int | None = None,
    force: bool = False,
) -> tuple[list[BulletinCreate], dict | None]:
    collector = OracleSecurityCollector()
    bulletins = collector.collect(limit=limit, force=force)
    response_data = None
    if ingest_url and bulletins:
        session = requests.Session()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        session.headers.update(headers)
        payload = [bulletin.model_dump(mode="json") for bulletin in bulletins]
        response = session.post(ingest_url, json=payload, timeout=30)
        response.raise_for_status()
        try:
            response_data = response.json()
        except requests.JSONDecodeError:  # pragma: no cover
            response_data = {"status_code": response.status_code}
    return bulletins, response_data


__all__ = ["OracleSecurityCollector", "run", "FEED_URL"]
