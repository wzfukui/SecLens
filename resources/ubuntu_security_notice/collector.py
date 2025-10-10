"""Ubuntu security notices collector plugin."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Sequence
import json
import logging
import xml.etree.ElementTree as ET

import requests

from app.schemas import BulletinCreate, ContentInfo, SourceInfo
from app.time_utils import resolve_published_at

LOGGER = logging.getLogger(__name__)
USER_AGENT = "SecLensUbuntuCollector/1.0"
DEFAULT_LIMIT = 20
SOURCE_FILE = Path(__file__).resolve().with_name("source.txt")
STATE_FILE_NAME = ".cursor"


@dataclass
class FeedEntry:
    notice_id: str
    title: str
    link: str
    summary: str | None
    published_at: datetime
    guid: str | None
    fetched_at: datetime
    time_meta: dict | None
    raw_pub_date: str | None


def _load_feed_url() -> str:
    try:
        text = SOURCE_FILE.read_text(encoding="utf-8").strip()
        if text:
            return text
    except FileNotFoundError:
        pass
    return "https://ubuntu.com/security/notices/rss.xml"


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(value.split()).strip() or None


class UbuntuSecurityCollector:
    """Encapsulates fetch, normalize, and cursor persistence for Ubuntu USN notices."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        feed_url: str | None = None,
        state_path: Path | None = None,
    ) -> None:
        self.session = session or requests.Session()
        self.feed_url = feed_url or _load_feed_url()
        self.state_path = state_path or Path(__file__).resolve().with_name(STATE_FILE_NAME)
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "application/rss+xml, application/json, text/xml;q=0.9, */*;q=0.8",
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
            dt = datetime.fromisoformat(raw)
        except ValueError:
            LOGGER.warning("Invalid cursor value '%s'; ignoring", raw)
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def save_cursor(self, value: datetime) -> None:
        value = value.astimezone(timezone.utc)
        self.state_path.write_text(value.isoformat(), encoding="utf-8")

    # --- Fetch ----------------------------------------------------------
    def fetch_feed(self) -> Sequence[FeedEntry]:
        response = self.session.get(self.feed_url, timeout=30)
        response.raise_for_status()
        text = response.text.lstrip()
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise ValueError("Failed to parse Ubuntu RSS feed") from exc

        entries: list[FeedEntry] = []
        for item in root.findall("./channel/item"):
            link = (item.findtext("link") or "").strip()
            if not link:
                continue
            notice_id = self._extract_notice_id(link)
            title = _clean_text(item.findtext("title")) or notice_id
            summary = _clean_text(item.findtext("description"))
            fetched_at = datetime.now(timezone.utc)
            raw_pub_date = item.findtext("pubDate")
            pub_date, time_meta = resolve_published_at(
                "ubuntu_security",
                [(raw_pub_date, "item.pubDate")],
                fetched_at=fetched_at,
            )
            guid = _clean_text(item.findtext("guid"))
            entries.append(
                FeedEntry(
                    notice_id=notice_id,
                    title=title,
                    link=link,
                    summary=summary,
                    published_at=pub_date or fetched_at,
                    guid=guid,
                    fetched_at=fetched_at,
                    time_meta=time_meta if time_meta else None,
                    raw_pub_date=raw_pub_date.strip() if isinstance(raw_pub_date, str) else None,
                )
            )
        return entries

    def fetch_detail(self, notice_id: str, link: str) -> dict:
        detail_url = f"{link}.json" if not link.endswith(".json") else link
        response = self.session.get(detail_url, timeout=30)
        response.raise_for_status()
        return response.json()

    # --- Normalize ------------------------------------------------------
    def normalize(self, entry: FeedEntry, detail: dict) -> BulletinCreate:
        summary = _clean_text(detail.get("summary")) or entry.summary
        body_text = detail.get("description") or summary
        published = detail.get("published")
        candidates = [
            (published, "detail.published"),
            (entry.published_at, "entry.published_at"),
            (entry.raw_pub_date, "feed.pubDate"),
        ]
        published_at, time_meta = resolve_published_at(
            "ubuntu_security",
            candidates,
            fetched_at=entry.fetched_at,
        )

        source = SourceInfo(
            source_slug="ubuntu_security",
            external_id=entry.notice_id,
            origin_url=entry.link,
        )
        content = ContentInfo(
            title=entry.title,
            summary=summary,
            body_text=body_text,
            published_at=published_at,
            language="en",
        )

        notice_type = detail.get("type")
        labels: list[str] = []
        if notice_type:
            labels.append(str(notice_type))
        releases = detail.get("releases") or []
        if isinstance(releases, list):
            for release in releases:
                codename = release.get("codename") if isinstance(release, dict) else None
                if codename:
                    labels.append(f"release:{codename}")

        cve_ids: list[str] = []
        if isinstance(detail.get("cves_ids"), list):
            cve_ids = [str(cve) for cve in detail["cves_ids"] if cve]
        elif isinstance(detail.get("cves"), list):
            for item in detail["cves"]:
                if isinstance(item, dict) and item.get("id"):
                    cve_ids.append(str(item["id"]))

        topics = ["official_bulletin"]
        if cve_ids:
            topics.append("cve")

        extra: dict[str, object] = {}
        for key in ("instructions", "references", "release_packages", "releases"):
            value = detail.get(key)
            if value:
                extra[key] = value
        if cve_ids:
            extra["cve_ids"] = cve_ids
        if entry.guid:
            extra["guid"] = entry.guid
        if entry.time_meta:
            extra.setdefault("time_meta_feed", entry.time_meta)
        if time_meta:
            extra["time_meta"] = time_meta
        if entry.raw_pub_date:
            extra.setdefault("raw_pub_date", entry.raw_pub_date)

        return BulletinCreate(
            source=source,
            content=content,
            severity=None,
            fetched_at=entry.fetched_at,
            labels=labels,
            topics=topics,
            extra=extra or None,
            raw={"detail": detail},
        )

    # --- Collection -----------------------------------------------------
    def collect(self, *, limit: int | None = None, force: bool = False) -> List[BulletinCreate]:
        limit = limit or DEFAULT_LIMIT
        cursor = None if force else self.load_cursor()
        entries = list(self.fetch_feed())
        entries.sort(key=lambda item: item.published_at)

        selected: list[FeedEntry] = []
        for entry in entries:
            if cursor and entry.published_at <= cursor:
                continue
            selected.append(entry)
        if limit is not None and limit > 0:
            selected = selected[-limit:]

        bulletins: list[BulletinCreate] = []
        latest = cursor
        for entry in selected:
            detail = self.fetch_detail(entry.notice_id, entry.link)
            bulletin = self.normalize(entry, detail)
            bulletins.append(bulletin)
            if latest is None or entry.published_at > latest:
                latest = entry.published_at

        if latest and not force and bulletins:
            self.save_cursor(latest)
        return bulletins

    # --- Helpers --------------------------------------------------------
    @staticmethod
    def _extract_notice_id(link: str) -> str:
        segment = link.rstrip("/").split("/")[-1]
        return segment.upper()


def run(
    ingest_url: str | None = None,
    token: str | None = None,
    *,
    limit: int | None = None,
    force: bool = False,
) -> tuple[list[BulletinCreate], dict | None]:
    """Entrypoint for the Ubuntu security notices plugin."""

    collector = UbuntuSecurityCollector()
    bulletins = collector.collect(limit=limit, force=force)
    response_data = None
    if ingest_url and bulletins:
        session = requests.Session()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        session.headers.update(headers)
        payload = [b.model_dump(mode="json") for b in bulletins]
        response = session.post(ingest_url, json=payload, timeout=30)
        response.raise_for_status()
        try:
            response_data = response.json()
        except json.JSONDecodeError:
            response_data = {"status_code": response.status_code}
    return bulletins, response_data


__all__ = ["UbuntuSecurityCollector", "FeedEntry", "run"]
