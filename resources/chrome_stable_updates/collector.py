"""Collector for Chrome Stable Updates entries."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Sequence
from urllib.parse import urljoin
import logging
import unicodedata

import requests
from bs4 import BeautifulSoup, Tag

from app.schemas import BulletinCreate, ContentInfo, SourceInfo
from app.time_utils import resolve_published_at

LOGGER = logging.getLogger(__name__)

LIST_URL = "https://chromereleases.googleblog.com/search/label/Stable%20updates"
USER_AGENT = "SecLensChromeStableCollector/1.0"
REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "User-Agent": USER_AGENT,
}


@dataclass
class FetchParams:
    """Parameters controlling fetch behaviour for Chrome Stable updates."""

    list_url: str = LIST_URL
    limit: int | None = 10


def _clean_text(value: str | None) -> str | None:
    if not value:
        return None
    normalised = unicodedata.normalize("NFKC", value)
    collapsed = " ".join(normalised.split())
    return collapsed or None


def _parse_date(text: str | None) -> datetime | None:
    if not text:
        return None
    candidate = _clean_text(text)
    if not candidate:
        return None
    for fmt in ("%A, %B %d, %Y", "%a, %B %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(candidate, fmt)
        except ValueError:
            continue
    return None


def _slugify(text: str) -> str:
    normalised = unicodedata.normalize("NFKD", text)
    result_chars: list[str] = []
    for char in normalised:
        if char.isalnum():
            result_chars.append(char.lower())
        elif char in {" ", "-", "_", "/"}:
            result_chars.append("-")
    slug = "".join(result_chars).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "label"


def _extract_body_text(html: str | None) -> tuple[str | None, str | None]:
    if not html:
        return None, None
    soup = BeautifulSoup(html, "html.parser")
    chunks: list[str] = []
    seen: set[str] = set()
    for element in soup.find_all(["p", "li"]):
        text = _clean_text(element.get_text(" ", strip=True))
        if not text:
            continue
        if text in seen:
            continue
        seen.add(text)
        chunks.append(text)
    if not chunks:
        fallback = _clean_text(soup.get_text(" ", strip=True))
        if fallback:
            chunks.append(fallback)
    if not chunks:
        return None, None
    summary = chunks[0]
    body_text = "\n\n".join(chunks)
    return summary, body_text


class ChromeStableUpdatesCollector:
    """Fetch and normalise Chrome Stable update bulletins."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(REQUEST_HEADERS)

    def fetch(self, params: FetchParams) -> Sequence[dict]:
        listing = self._fetch_listing(params.list_url, params.limit)
        return listing

    def _fetch_listing(self, list_url: str, limit: int | None) -> list[dict]:
        response = self.session.get(list_url, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        container = soup.select_one("div.section#main div.widget.Blog")
        if not container:
            LOGGER.warning("Unable to locate Blog container on %s", list_url)
            return []

        items: list[dict] = []
        for post in container.find_all("div", class_=lambda value: value and "post" in value.split(), recursive=False):
            parsed = self._parse_post(post, base_url=list_url)
            if not parsed:
                continue
            items.append(parsed)
            if limit and len(items) >= limit:
                break
        return items

    def _parse_post(self, post: Tag, *, base_url: str) -> dict | None:
        if not isinstance(post, Tag):
            return None

        post_id = post.get("data-id")
        title_anchor = post.select_one("h2.title a")
        if not title_anchor or not title_anchor.get("href"):
            return None
        origin_url = urljoin(base_url, title_anchor["href"])
        title = _clean_text(title_anchor.get_text())
        if not title:
            title = origin_url

        publish_node = post.select_one(".post-header .publishdate")
        published_text = publish_node.get_text() if publish_node else None

        script_tag = post.select_one("div.post-content script[type='text/template']")
        body_html = None
        if script_tag and script_tag.string:
            body_html = script_tag.string
        elif script_tag:
            body_html = script_tag.get_text()
        if not body_html:
            noscript = post.select_one("div.post-content noscript")
            if noscript:
                body_html = noscript.decode_contents()

        summary, body_text = _extract_body_text(body_html)

        label_nodes = post.select("div.label-footer span.labels a.label")
        blog_labels: list[str] = []
        for node in label_nodes:
            label_text = _clean_text(node.get_text())
            if label_text:
                blog_labels.append(label_text)

        return {
            "post_id": post_id,
            "title": title,
            "origin_url": origin_url,
            "published_text": published_text,
            "body_html": body_html,
            "summary": summary,
            "body_text": body_text,
            "blog_labels": blog_labels,
        }

    def normalize(self, entry: dict) -> BulletinCreate:
        origin_url = entry.get("origin_url")
        if not origin_url:
            raise ValueError("origin_url missing in entry")

        fetched_at = datetime.now(timezone.utc)

        candidates: list[tuple[object, str]] = []
        parsed_date = _parse_date(entry.get("published_text"))
        if parsed_date:
            candidates.append((parsed_date, "post.publishdate_parsed"))
        published_text = entry.get("published_text")
        if published_text:
            candidates.append((published_text, "post.publishdate_text"))

        published_at, time_meta = resolve_published_at(
            "chrome_stable_updates",
            candidates,
            fetched_at=fetched_at,
        )

        external_id = entry.get("post_id") or origin_url.rsplit("/", 1)[-1]

        labels = ["vendor:google", "channel:stable"]
        for label in entry.get("blog_labels") or []:
            slug = _slugify(label)
            labels.append(f"blog-label:{slug}")

        topics = ["vendor-update"]

        extra: dict[str, object] = {
            "blog_labels": entry.get("blog_labels"),
            "body_html": entry.get("body_html"),
            "published_text": entry.get("published_text"),
        }
        if time_meta:
            extra["time_meta"] = time_meta

        bulletin = BulletinCreate(
            source=SourceInfo(
                source_slug="chrome_stable_updates",
                external_id=str(external_id),
                origin_url=origin_url,
            ),
            content=ContentInfo(
                title=entry.get("title") or origin_url,
                summary=entry.get("summary"),
                body_text=entry.get("body_text"),
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
            except Exception as exc:
                LOGGER.exception("Failed to normalise Chrome Stable entry: %s", entry, exc_info=exc)
        return bulletins


def run(
    ingest_url: str | None = None,
    token: str | None = None,
    params: FetchParams | None = None,
) -> tuple[list[BulletinCreate], dict | None]:
    collector = ChromeStableUpdatesCollector()
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


__all__ = ["ChromeStableUpdatesCollector", "FetchParams", "run"]

