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
from bs4 import BeautifulSoup

from app.schemas import BulletinCreate, ContentInfo, SourceInfo

LOGGER = logging.getLogger(__name__)
FEED_URL = "https://www.oracle.com/ocom/groups/public/@otn/documents/webcontent/rss-otn-sec.xml"
STATE_FILE_NAME = ".cursor"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
ARTICLE_ACCEPT = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"


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
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

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
        external_id = self._derive_external_id(entry, origin_url)
        source = SourceInfo(
            source_slug="oracle_security_alert",
            external_id=external_id,
            origin_url=origin_url,
        )
        article_text = self._fetch_article_body(origin_url)
        summary = None
        if article_text:
            summary = self._generate_summary(article_text, limit=500)
        elif entry.description:
            summary = self._clean_summary(entry.description)
        content = ContentInfo(
            title=entry.title,
            summary=summary,
            body_text=article_text or entry.description,
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

    def _derive_external_id(self, entry: FeedEntry, origin_url: str | None) -> str | None:
        candidates: list[str] = []
        if entry.guid:
            candidates.append(entry.guid)
        if origin_url:
            parsed = urlparse(origin_url)
            slug = Path(parsed.path).stem
            if slug:
                candidates.append(slug)
        if entry.link:
            candidates.append(entry.link)
        if entry.title:
            candidates.append(entry.title)
        for candidate in candidates:
            cleaned = candidate.strip()
            if cleaned:
                return cleaned
        return None

    def _fetch_article_body(self, url: str | None) -> str | None:
        if not self._is_valid_url(url):
            return None
        try:
            response = self.session.get(url, timeout=30, headers={"Accept": ARTICLE_ACCEPT})
            response.raise_for_status()
        except requests.RequestException as exc:
            LOGGER.debug("Failed to fetch article %s: %s", url, exc)
            return None

        return self._extract_text(response.text)

    @staticmethod
    def _extract_text(html: str) -> str | None:
        soup = BeautifulSoup(html, "html.parser")
        OracleSecurityCollector._remove_tracked_sections(soup, marker="header")
        OracleSecurityCollector._remove_tracked_sections(soup, marker="footer")
        paragraphs = OracleSecurityCollector._collect_paragraphs(
            soup.select_one("article")
            or soup.select_one(".content")
            or soup.select_one("#content")
            or soup.select_one(".main-content")
            or soup.body
            or soup
        )
        if not paragraphs:
            fallback = soup.get_text(separator="\n\n", strip=True)
            text = OracleSecurityCollector._strip_noise_lines(fallback)
            return text or None
        text = "\n\n".join(paragraphs).strip()
        return text or None

    @staticmethod
    def _collect_paragraphs(root) -> list[str]:
        if root is None:
            return []
        paragraphs: list[str] = []
        seen: set[str] = set()
        for element in root.find_all(["p", "li"]):
            text = " ".join(element.stripped_strings)
            if not text:
                continue
            if OracleSecurityCollector._is_noise_text(text):
                continue
            if text in seen:
                continue
            seen.add(text)
            paragraphs.append(text)
        return paragraphs

    @staticmethod
    def _clean_summary(value: str | None) -> str | None:
        if not value:
            return None
        soup = BeautifulSoup(value, "html.parser")
        text = soup.get_text(" ", strip=True)
        return text or None

    @staticmethod
    def _is_noise_text(value: str) -> bool:
        normalized = value.strip().lower()
        return normalized in {"skip to content", "skip to main content"}

    @staticmethod
    def _strip_noise_lines(text: str) -> str:
        if not text:
            return text
        lines = []
        for line in text.splitlines():
            cleaned = line.strip()
            if not cleaned:
                continue
            if OracleSecurityCollector._is_noise_text(cleaned):
                continue
            lines.append(cleaned)
        return "\n\n".join(lines)

    @staticmethod
    def _generate_summary(body: str, *, limit: int) -> str | None:
        text = body.strip()
        if not text:
            return None
        if len(text) <= limit:
            return text
        truncated = text[:limit].rstrip()
        if not truncated:
            return text[:limit]
        return f"{truncated}..."

    @staticmethod
    def _remove_tracked_sections(soup: BeautifulSoup, *, marker: str) -> None:
        for element in soup.select(f'[data-trackas="{marker}"]'):
            element.decompose()


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
        except ValueError:  # pragma: no cover
            response_data = {"status_code": response.status_code}
    return bulletins, response_data


__all__ = ["OracleSecurityCollector", "run", "FEED_URL"]
