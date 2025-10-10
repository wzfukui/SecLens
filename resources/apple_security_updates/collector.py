"""Collector for Apple security releases."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Sequence
from urllib.parse import urljoin, urlparse
import logging
import unicodedata

import requests
from bs4 import BeautifulSoup, Tag

from app.schemas import BulletinCreate, ContentInfo, SourceInfo
from app.time_utils import resolve_published_at

LOGGER = logging.getLogger(__name__)

LIST_URL = "https://support.apple.com/en-us/100100"
BASE_URL = "https://support.apple.com"
USER_AGENT = "SecLensAppleSecurityCollector/1.0"
REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "User-Agent": USER_AGENT,
}


@dataclass
class FetchParams:
    """Parameters controlling Apple security releases fetching."""

    list_url: str = LIST_URL
    limit: int | None = 20


def _clean_text(value: str | None) -> str | None:
    if not value:
        return None
    normalised = unicodedata.normalize("NFKC", value)
    collapsed = " ".join(normalised.split())
    return collapsed or None


def _slugify(text: str | None) -> str:
    if not text:
        return "entry"
    normalised = unicodedata.normalize("NFKD", text)
    result: list[str] = []
    for char in normalised:
        if char.isalnum():
            result.append(char.lower())
        elif char in {" ", "-", "_", "/", "."}:
            result.append("-")
    slug = "".join(result).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "entry"


def _parse_release_date(text: str | None) -> datetime | None:
    if not text:
        return None
    candidate = _clean_text(text)
    if not candidate:
        return None
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(candidate, fmt)
        except ValueError:
            continue
    return None


def _extract_notes(cell: Tag) -> list[str]:
    notes: list[str] = []
    for note in cell.select(".note"):
        text = _clean_text(note.get_text(" ", strip=True))
        if text:
            notes.append(text)
    return notes


def _primary_cell_text(cell: Tag) -> str | None:
    for paragraph in cell.find_all("p", class_="gb-paragraph"):
        parent = paragraph.parent
        classes = parent.get("class", []) if isinstance(parent, Tag) else []
        if any(cls for cls in classes if "note" in cls):
            continue
        text = _clean_text(paragraph.get_text(" ", strip=True))
        if text:
            return text
    text = _clean_text(cell.get_text(" ", strip=True))
    return text


def _dedupe_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _external_id(detail_url: str | None, title: str | None) -> str:
    if detail_url:
        parsed = urlparse(detail_url)
        fragment = parsed.path.rstrip("/").rsplit("/", 1)[-1]
        if fragment:
            return fragment
    return _slugify(title)


class AppleSecurityUpdatesCollector:
    """Fetch and normalise Apple security update listings."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(REQUEST_HEADERS)

    def fetch(self, params: FetchParams) -> Sequence[dict]:
        return self._fetch_listing(params.list_url, params.limit)

    def _fetch_listing(self, list_url: str, limit: int | None) -> list[dict]:
        response = self.session.get(list_url, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        table = soup.select_one("div.table-wrapper.gb-table table.gb-table")
        if not table:
            LOGGER.warning("Apple security releases table not found at %s", list_url)
            return []

        entries: list[dict] = []
        seen_ids: set[str] = set()
        for row in table.find_all("tr")[1:]:
            cells = row.find_all("td")
            if len(cells) != 3:
                continue
            parsed = self._parse_row(cells, base_url=list_url)
            if not parsed:
                continue
            identifier = parsed.get("external_id")
            if identifier and identifier in seen_ids:
                continue
            if identifier:
                seen_ids.add(identifier)
            entries.append(parsed)
            if limit and len(entries) >= limit:
                break
        return entries

    def _parse_row(self, cells: list[Tag], *, base_url: str) -> dict | None:
        name_cell, availability_cell, released_cell = cells

        anchor = name_cell.find("a", href=True)
        detail_url = None
        title = None
        if anchor:
            href = anchor.get("href")
            detail_url = urljoin(BASE_URL, href)
            title = _clean_text(anchor.get_text(" ", strip=True))
        if not title:
            title = _primary_cell_text(name_cell)
        if not title:
            return None

        notes = _extract_notes(name_cell)

        available_for = _clean_text(availability_cell.get_text(" ", strip=True))
        release_text = _clean_text(released_cell.get_text(" ", strip=True))

        external_id = _external_id(detail_url, title)
        origin_url = detail_url or f"{base_url}#{external_id}"

        return {
            "external_id": external_id,
            "title": title,
            "origin_url": origin_url,
            "detail_url": detail_url,
            "available_for": available_for,
            "release_text": release_text,
            "notes": notes,
        }

    def normalize(self, entry: dict) -> BulletinCreate:
        fetched_at = datetime.now(timezone.utc)

        release_text = entry.get("release_text")
        parsed_date = _parse_release_date(release_text)

        candidates: list[tuple[object, str]] = []
        if parsed_date:
            candidates.append((parsed_date, "table.release_date_parsed"))
        if release_text:
            candidates.append((release_text, "table.release_date_text"))

        published_at, time_meta = resolve_published_at(
            "apple_security_updates",
            candidates,
            fetched_at=fetched_at,
        )

        notes: list[str] = entry.get("notes") or []
        available_for = entry.get("available_for")

        summary_parts: list[str] = []
        if available_for:
            summary_parts.append(available_for)
        if notes:
            summary_parts.append("; ".join(notes))
        summary = " | ".join(summary_parts) or None

        body_lines: list[str] = []
        if available_for:
            body_lines.append(f"Available for: {available_for}")
        for note in notes:
            body_lines.append(note)
        if release_text:
            body_lines.append(f"Release date: {release_text}")
        body_text = "\n".join(body_lines) or None

        title = entry.get("title") or entry.get("origin_url")

        labels = ["vendor:apple"]
        if title:
            labels.append(f"product:{_slugify(title)}")
        for note in notes:
            if "no published cve" in note.lower():
                labels.append("note:no-cve")

        labels = _dedupe_order(label for label in labels if label)

        topics = ["vendor-update", "official_advisory"]

        extra: dict[str, object] = {
            "available_for": available_for,
            "notes": notes,
            "release_date_text": release_text,
            "detail_url": entry.get("detail_url"),
        }
        if time_meta:
            extra["time_meta"] = time_meta

        bulletin = BulletinCreate(
            source=SourceInfo(
                source_slug="apple_security_updates",
                external_id=str(entry.get("external_id")),
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
        return bulletin

    def collect(self, params: FetchParams | None = None) -> list[BulletinCreate]:
        params = params or FetchParams()
        items = self.fetch(params)
        bulletins: list[BulletinCreate] = []
        for item in items:
            try:
                bulletins.append(self.normalize(item))
            except Exception as exc:
                LOGGER.exception("Failed to normalise Apple security entry: %s", item, exc_info=exc)
        return bulletins


def run(
    ingest_url: str | None = None,
    token: str | None = None,
    params: FetchParams | None = None,
) -> tuple[list[BulletinCreate], dict | None]:
    collector = AppleSecurityUpdatesCollector()
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


__all__ = ["AppleSecurityUpdatesCollector", "FetchParams", "run"]
