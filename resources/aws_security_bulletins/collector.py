"""Collector for AWS Security Bulletins RSS feed."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Sequence
from urllib.parse import urlparse
import logging
import unicodedata
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup, NavigableString, Tag
from email.utils import parsedate_to_datetime

from app.schemas import BulletinCreate, ContentInfo, SourceInfo
from app.time_utils import resolve_published_at


LOGGER = logging.getLogger(__name__)

FEED_URL = "https://aws.amazon.com/security/security-bulletins/rss/feed/"
USER_AGENT = "SecLensAwsSecurityCollector/1.0"
REQUEST_HEADERS = {
    "Accept": "application/rss+xml,application/xml;q=0.9,text/xml;q=0.8,*/*;q=0.7",
    "User-Agent": USER_AGENT,
}


@dataclass
class FetchParams:
    feed_url: str = FEED_URL
    limit: int | None = 20


def _clean_text(value: str | None) -> str | None:
    if not value:
        return None
    normalised = unicodedata.normalize("NFKC", value)
    collapsed = " ".join(normalised.split())
    return collapsed or None


def _slugify(value: str | None) -> str:
    if not value:
        return "value"
    normalised = unicodedata.normalize("NFKD", value)
    chars: list[str] = []
    for char in normalised:
        if char.isalnum():
            chars.append(char.lower())
        elif char in {" ", "-", "_", "/", ":", "."}:
            chars.append("-")
    slug = "".join(chars).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "value"


def _parse_pub_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _harvest_label_values(paragraph: Tag) -> dict[str, str]:
    result: dict[str, str] = {}
    current_label: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal current_label, buffer
        if current_label and buffer:
            value = _clean_text(" ".join(buffer))
            if value:
                result[current_label] = value
        current_label = None
        buffer = []

    for child in paragraph.children:
        if isinstance(child, Tag) and child.name == "b":
            flush()
            label = _clean_text(child.get_text(" ", strip=True))
            if label:
                current_label = label.rstrip(":")
        elif isinstance(child, Tag) and child.name == "br":
            flush()
        else:
            text: str | None = None
            if isinstance(child, NavigableString):
                text = _clean_text(str(child))
            elif isinstance(child, Tag):
                text = _clean_text(child.get_text(" ", strip=True))
            if text:
                buffer.append(text)

    flush()
    return result


def _parse_description(description_html: str | None) -> tuple[dict[str, str], list[str]]:
    if not description_html:
        return {}, []
    soup = BeautifulSoup(description_html, "html.parser")
    details: dict[str, str] = {}
    paragraphs: list[str] = []

    for paragraph in soup.find_all("p"):
        harvested = _harvest_label_values(paragraph)
        if harvested:
            for key, value in harvested.items():
                details[key] = value
        paragraph_text = _clean_text(paragraph.get_text(" ", strip=True))
        if paragraph_text:
            paragraphs.append(paragraph_text)
    return details, paragraphs


def _first_meaningful_paragraph(paragraphs: Iterable[str]) -> str | None:
    for text in paragraphs:
        lowered = text.lower()
        if lowered.startswith("bulletin id:"):
            continue
        if lowered.startswith("scope:"):
            continue
        if lowered.startswith("content type:"):
            continue
        if lowered.startswith("publication date:"):
            continue
        if lowered.startswith("description:"):
            continue
        if lowered.startswith("affected"):
            continue
        return text
    return next(iter(paragraphs), None) if hasattr(paragraphs, "__iter__") else None


class AwsSecurityBulletinsCollector:
    """Fetch and normalise AWS security bulletin RSS entries."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(REQUEST_HEADERS)

    def fetch(self, params: FetchParams) -> Sequence[dict]:
        response = self.session.get(params.feed_url, timeout=30)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        entries: list[dict] = []
        for item in root.findall("./channel/item"):
            parsed = self._parse_item(item)
            if not parsed:
                continue
            entries.append(parsed)
            if params.limit and len(entries) >= params.limit:
                break
        return entries

    def _parse_item(self, item: ET.Element) -> dict | None:
        title = _clean_text(item.findtext("title"))
        link = _clean_text(item.findtext("link"))
        guid = _clean_text(item.findtext("guid"))
        description = item.findtext("description")
        pub_date = _parse_pub_date(item.findtext("pubDate"))
        author = _clean_text(item.findtext("author"))

        if not title and not link:
            return None

        details, paragraphs = _parse_description(description)

        return {
            "title": title,
            "link": link,
            "guid": guid,
            "pub_date": pub_date,
            "author": author,
            "details": details,
            "paragraphs": paragraphs,
            "description_html": description,
        }

    def normalize(self, entry: dict) -> BulletinCreate:
        fetched_at = datetime.now(timezone.utc)

        candidates: list[tuple[object, str]] = []
        if entry.get("pub_date"):
            candidates.append((entry["pub_date"], "item.pubDate"))
        publication_detail = entry.get("details", {}).get("Publication Date")
        if publication_detail:
            candidates.append((publication_detail, "item.details.Publication Date"))

        published_at, time_meta = resolve_published_at(
            "aws_security_bulletins",
            candidates,
            fetched_at=fetched_at,
        )

        link = entry.get("link")
        external_id = None
        if link:
            parsed = urlparse(link)
            external_id = parsed.path.rstrip("/").rsplit("/", 1)[-1]
        if not external_id:
            external_id = entry.get("guid") or _slugify(entry.get("title"))

        paragraphs: list[str] = entry.get("paragraphs") or []
        summary = _first_meaningful_paragraph(paragraphs)
        body_text = "\n\n".join(paragraphs) if paragraphs else None

        details = entry.get("details") or {}

        labels = ["vendor:aws"]
        bulletin_id = details.get("Bulletin ID")
        if bulletin_id:
            labels.append(f"bulletin:{_slugify(bulletin_id)}")
        content_type = details.get("Content Type")
        if content_type:
            labels.append(f"severity:{_slugify(content_type)}")

        labels = [label for label in labels if label]

        topics = ["official_advisory", "vulnerability_alert"]

        extra: dict[str, object] = {
            "bulletin_id": bulletin_id,
            "scope": details.get("Scope"),
            "content_type": content_type,
            "publication_detail": publication_detail,
            "author": entry.get("author"),
            "details": details,
        }
        if time_meta:
            extra["time_meta"] = time_meta

        bulletin = BulletinCreate(
            source=SourceInfo(
                source_slug="aws_security_bulletins",
                external_id=str(external_id),
                origin_url=link,
            ),
            content=ContentInfo(
                title=entry.get("title") or (link or str(external_id)),
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
        return bulletin

    def collect(self, params: FetchParams | None = None) -> list[BulletinCreate]:
        params = params or FetchParams()
        entries = self.fetch(params)
        bulletins: list[BulletinCreate] = []
        for entry in entries:
            try:
                bulletins.append(self.normalize(entry))
            except Exception as exc:  # pragma: no cover - defensive guard
                LOGGER.exception("Failed to normalise AWS bulletin entry: %s", entry, exc_info=exc)
        return bulletins


def run(
    ingest_url: str | None = None,
    token: str | None = None,
    params: FetchParams | None = None,
) -> tuple[list[BulletinCreate], dict | None]:
    collector = AwsSecurityBulletinsCollector()
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


__all__ = ["AwsSecurityBulletinsCollector", "FetchParams", "run"]

