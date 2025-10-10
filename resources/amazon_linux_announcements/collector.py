"""Collector for Amazon Linux security announcements HTML table."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence
from urllib.parse import urljoin
import logging
import unicodedata

import requests
from bs4 import BeautifulSoup, Tag

from app.schemas import BulletinCreate, ContentInfo, SourceInfo
from app.time_utils import resolve_published_at


LOGGER = logging.getLogger(__name__)

LIST_URL = "https://alas.aws.amazon.com/announcements.html"
BASE_URL = "https://alas.aws.amazon.com/"
USER_AGENT = "SecLensAmazonLinuxCollector/1.0"
REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "User-Agent": USER_AGENT,
}


@dataclass
class FetchParams:
    list_url: str = LIST_URL
    limit: int | None = 10


def _clean_text(value: str | None) -> str | None:
    if not value:
        return None
    normalised = unicodedata.normalize("NFKC", value)
    cleaned = " ".join(normalised.split())
    return cleaned or None


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    candidate = _clean_text(value)
    if not candidate:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(candidate, fmt)
        except ValueError:
            continue
    return None


class AmazonLinuxAnnouncementsCollector:
    """Fetch and normalise Amazon Linux security announcements."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(REQUEST_HEADERS)

    def fetch(self, params: FetchParams) -> Sequence[dict]:
        response = self.session.get(params.list_url, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        table = soup.select_one("div.aws-table table#ALAStable tbody")
        if not table:
            LOGGER.warning("Announcements table not found at %s", params.list_url)
            return []

        items: list[dict] = []
        for row in table.find_all("tr"):
            parsed = self._parse_row(row, base_url=params.list_url)
            if not parsed:
                continue
            items.append(parsed)
            if params.limit and len(items) >= params.limit:
                break
        return items

    def _parse_row(self, row: Tag, *, base_url: str) -> dict | None:
        cells = row.find_all("td")
        if len(cells) != 3:
            return None
        published_text = _clean_text(cells[0].get_text(" ", strip=True))
        updated_text = _clean_text(cells[1].get_text(" ", strip=True))
        announcement_cell = cells[2]

        links = announcement_cell.find_all("a", href=True)
        if not links:
            return None
        announcement_id = _clean_text(links[0].get_text(" ", strip=True))
        title = _clean_text(links[-1].get_text(" ", strip=True))
        href = links[-1]["href"]
        origin_url = urljoin(base_url, href)

        published_dt = _parse_timestamp(published_text)
        updated_dt = _parse_timestamp(updated_text)

        return {
            "announcement_id": announcement_id,
            "title": title,
            "origin_url": origin_url,
            "published_text": published_text,
            "updated_text": updated_text,
            "published_dt": published_dt,
            "updated_dt": updated_dt,
        }

    def normalize(self, entry: dict) -> BulletinCreate:
        fetched_at = datetime.now(timezone.utc)

        candidates = []
        if entry.get("published_dt"):
            candidates.append((entry["published_dt"], "table.published_datetime"))
        if entry.get("published_text"):
            candidates.append((entry["published_text"], "table.published_text"))

        published_at, time_meta = resolve_published_at(
            "amazon_linux_announcements",
            candidates,
            fetched_at=fetched_at,
        )

        announcement_id = entry.get("announcement_id") or entry.get("title")
        title = entry.get("title") or announcement_id or entry.get("origin_url")

        summary_parts = []
        if entry.get("announcement_id"):
            summary_parts.append(entry["announcement_id"])
        if entry.get("title") and entry.get("announcement_id") != entry.get("title"):
            summary_parts.append(entry["title"])
        summary = " - ".join(summary_parts) or entry.get("title")

        body_lines = []
        if entry.get("published_text"):
            body_lines.append(f"Published: {entry['published_text']}")
        if entry.get("updated_text"):
            body_lines.append(f"Last Updated: {entry['updated_text']}")
        if entry.get("title"):
            body_lines.append(entry["title"])
        body_text = "\n".join(body_lines) or None

        labels = ["vendor:aws", "distribution:amazon-linux", "announcement"]
        if announcement_id:
            labels.append(f"announcement:{announcement_id.lower()}")

        labels = [_clean_text(label) for label in labels if _clean_text(label)]

        topics = ["vendor-update", "official_advisory"]

        extra: dict[str, object] = {
            "announcement_id": announcement_id,
            "published_text": entry.get("published_text"),
            "updated_text": entry.get("updated_text"),
        }
        if entry.get("updated_dt"):
            extra["updated_at"] = entry["updated_dt"].isoformat()
        if time_meta:
            extra["time_meta"] = time_meta

        return BulletinCreate(
            source=SourceInfo(
                source_slug="amazon_linux_announcements",
                external_id=str(announcement_id or entry.get("origin_url")),
                origin_url=entry.get("origin_url"),
            ),
            content=ContentInfo(
                title=title,
                summary=summary,
                body_text=body_text,
                published_at=published_at,
                language="en",
            ),
            severity=None,
            fetched_at=fetched_at,
            labels=labels,
            topics=topics,
            extra={k: v for k, v in extra.items() if v},
            raw=entry,
        )

    def collect(self, params: FetchParams | None = None) -> list[BulletinCreate]:
        params = params or FetchParams()
        rows = self.fetch(params)
        bulletins: list[BulletinCreate] = []
        for entry in rows:
            try:
                bulletins.append(self.normalize(entry))
            except Exception as exc:  # pragma: no cover
                LOGGER.exception("Failed to normalise Amazon Linux announcement: %s", entry, exc_info=exc)
        return bulletins


def run(
    ingest_url: str | None = None,
    token: str | None = None,
    params: FetchParams | None = None,
) -> tuple[list[BulletinCreate], dict | None]:
    collector = AmazonLinuxAnnouncementsCollector()
    bulletins = collector.collect(params=params)
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
        response_data = response.json()
    return bulletins, response_data


__all__ = ["AmazonLinuxAnnouncementsCollector", "FetchParams", "run"]

