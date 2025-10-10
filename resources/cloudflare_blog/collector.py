"""Collector for the Cloudflare technical blog."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List, Sequence
from urllib.parse import urljoin, urlparse
import logging
import unicodedata

import requests
from bs4 import BeautifulSoup, Tag

from app.schemas import BulletinCreate, ContentInfo, SourceInfo
from app.time_utils import resolve_published_at

logger = logging.getLogger(__name__)

DEFAULT_LIST_URL = "https://blog.cloudflare.com/"
USER_AGENT = "SecLensCollector/0.1"
REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "User-Agent": USER_AGENT,
}


@dataclass
class FetchParams:
    list_url: str = DEFAULT_LIST_URL
    limit: int | None = 10


def _clean_text(value: str | None) -> str | None:
    if not value:
        return None
    normalised = unicodedata.normalize("NFKC", value)
    collapsed = " ".join(normalised.split())
    return collapsed or None


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _looks_like_date(text: str | None) -> bool:
    if not text:
        return False
    if len(text) != 10:
        return False
    if text[4] != "-" or text[7] != "-":
        return False
    year, month, day = text[:4], text[5:7], text[8:]
    return year.isdigit() and month.isdigit() and day.isdigit()


def _slug_from_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if not path:
        return None
    slug = path.rsplit("/", 1)[-1]
    return slug or None


class CloudflareBlogCollector:
    """Fetch and normalise Cloudflare blog entries."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(REQUEST_HEADERS)

    def fetch(self, params: FetchParams) -> Sequence[dict]:
        listing = self._fetch_listing(params.list_url, params.limit)
        entries: list[dict] = []
        for item in listing:
            detail = self._fetch_detail(item["url"])
            merged = {
                "listing": item,
                "detail": detail,
            }
            entries.append(merged)
        return entries

    def _fetch_listing(self, list_url: str, limit: int | None) -> list[dict]:
        response = self.session.get(list_url, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        articles = soup.find_all("article")
        items: list[dict] = []
        for article in articles:
            parsed = self._parse_listing_article(article, base_url=list_url)
            if not parsed:
                continue
            items.append(parsed)
            if limit and len(items) >= limit:
                break
        return items

    def _parse_listing_article(self, article: Tag, base_url: str) -> dict | None:
        title_anchor = article.find("a", attrs={"data-testid": "post-title"})
        if not title_anchor:
            title_anchor = article.find("a", href=True)
        if not title_anchor:
            return None
        href = title_anchor.get("href")
        if not href:
            return None
        origin_url = urljoin(base_url, href)
        heading = title_anchor.find(["h1", "h2", "h3"])
        title = _clean_text(heading.get_text()) if heading else _clean_text(title_anchor.get_text())
        if not title:
            return None

        date_node = article.find(attrs={"data-testid": "post-date"})
        published_hint = None
        if date_node:
            published_hint = _clean_text(date_node.get("datetime") or date_node.get_text())
        if not published_hint:
            time_node = article.find("time")
            if time_node:
                published_hint = _clean_text(time_node.get("datetime") or time_node.get_text())

        summary_node = article.find(attrs={"data-testid": "post-content"})
        summary = _clean_text(summary_node.get_text()) if summary_node else None
        if not summary:
            for paragraph in article.find_all("p"):
                candidate = _clean_text(paragraph.get_text())
                if not candidate or _looks_like_date(candidate):
                    continue
                summary = candidate
                break

        authors: list[str] = []
        for anchor in article.select("ul.author-lists a"):
            name = _clean_text(anchor.get_text())
            if not name:
                continue
            authors.append(name)

        image = None
        img = article.find("img")
        if img and img.get("src"):
            image = urljoin(base_url, img["src"])

        return {
            "title": title,
            "url": origin_url,
            "summary": summary,
            "published_hint": published_hint,
            "authors": _unique(authors),
            "image": image,
        }

    def _fetch_detail(self, url: str) -> dict:
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        article = soup.find("article", class_=lambda value: value and "post-full" in value.split())
        if not article:
            article = soup.find("article")

        title = None
        title_meta = soup.find("meta", attrs={"property": "og:title"})
        if title_meta and title_meta.get("content"):
            title = _clean_text(title_meta["content"])
        if not title and article:
            heading = article.find(["h1", "h2"])
            if heading:
                title = _clean_text(heading.get_text())

        summary = None
        summary_meta = soup.find("meta", attrs={"property": "og:description"})
        if summary_meta and summary_meta.get("content"):
            summary = _clean_text(summary_meta["content"])
        if not summary:
            description_meta = soup.find("meta", attrs={"name": "description"})
            if description_meta and description_meta.get("content"):
                summary = _clean_text(description_meta["content"])

        canonical = None
        canonical_link = soup.find("link", attrs={"rel": "canonical"})
        if canonical_link and canonical_link.get("href"):
            canonical = canonical_link["href"]

        published_time = None
        published_meta = soup.find("meta", attrs={"property": "article:published_time"})
        if published_meta and published_meta.get("content"):
            published_time = _clean_text(published_meta["content"])

        modified_time = None
        modified_meta = soup.find("meta", attrs={"property": "article:modified_time"})
        if modified_meta and modified_meta.get("content"):
            modified_time = _clean_text(modified_meta["content"])

        tags: list[str] = []
        for tag_meta in soup.find_all("meta", attrs={"property": "article:tag"}):
            content = _clean_text(tag_meta.get("content"))
            if content:
                tags.append(content)

        authors = []
        if article:
            for anchor in article.select("ul.author-lists a"):
                name = _clean_text(anchor.get_text())
                if name:
                    authors.append(name)
        if not authors:
            author_meta = soup.find("meta", attrs={"name": "twitter:data1"})
            if author_meta and author_meta.get("content"):
                for part in author_meta["content"].split(","):
                    name = _clean_text(part)
                    if name:
                        authors.append(name)

        authors = _unique(authors)
        tags = _unique(tags)

        body_text = None
        body_html = None
        if article:
            paragraphs: list[str] = []
            for paragraph in article.find_all("p"):
                text = _clean_text(paragraph.get_text())
                if not text or _looks_like_date(text):
                    continue
                paragraphs.append(text)
            if paragraphs:
                body_text = "\n\n".join(paragraphs)
            body_html = article.decode_contents()

        hero_image = None
        og_image = soup.find("meta", attrs={"property": "og:image"})
        if og_image and og_image.get("content"):
            hero_image = og_image["content"]

        return {
            "title": title,
            "summary": summary,
            "canonical_url": canonical,
            "published_time": published_time,
            "modified_time": modified_time,
            "tags": tags,
            "authors": authors,
            "body_text": body_text,
            "body_html": body_html,
            "hero_image": hero_image,
        }

    def normalize(self, entry: dict) -> BulletinCreate:
        listing = entry.get("listing") or {}
        detail = entry.get("detail") or {}
        origin_url: str | None = listing.get("url") or detail.get("canonical_url")

        title = detail.get("title") or listing.get("title") or origin_url or ""
        summary = detail.get("summary") or listing.get("summary")
        body_text = detail.get("body_text")

        fetched_at = datetime.now(timezone.utc)
        published_at, time_meta = resolve_published_at(
            "cloudflare_blog",
            [
                (detail.get("published_time"), "detail.article:published_time"),
                (listing.get("published_hint"), "listing.post_date"),
            ],
            fetched_at=fetched_at,
        )

        canonical_url = detail.get("canonical_url") or origin_url
        external_id = _slug_from_url(canonical_url or origin_url) or canonical_url or origin_url

        source = SourceInfo(
            source_slug="cloudflare_blog",
            external_id=external_id,
            origin_url=canonical_url,
        )
        content = ContentInfo(
            title=title,
            summary=summary,
            body_text=body_text,
            published_at=published_at,
            language="en",
        )

        tags = detail.get("tags") or []
        authors = detail.get("authors") or listing.get("authors") or []

        def _label(prefix: str, values: Iterable[str]) -> list[str]:
            result: list[str] = []
            for value in values:
                cleaned = _clean_text(value)
                if not cleaned:
                    continue
                lowered = " ".join(cleaned.lower().split())
                result.append(f"{prefix}:{lowered}")
            return result

        labels = _label("tag", tags) + _label("author", authors)

        topics = ["tech-blog"]

        extra: dict[str, object] = {
            "tags": tags,
            "authors": authors,
            "listing_image": listing.get("image"),
            "hero_image": detail.get("hero_image"),
            "modified_time": detail.get("modified_time"),
        }
        if time_meta:
            extra["time_meta"] = time_meta

        raw = {
            "listing": listing,
            "detail": detail,
        }

        return BulletinCreate(
            source=source,
            content=content,
            severity=None,
            fetched_at=fetched_at,
            labels=labels,
            topics=topics,
            extra=extra,
            raw=raw,
        )

    def collect(self, params: FetchParams | None = None) -> List[BulletinCreate]:
        params = params or FetchParams()
        entries = self.fetch(params)
        return [self.normalize(entry) for entry in entries]


def run(
    ingest_url: str | None = None,
    token: str | None = None,
    params: FetchParams | None = None,
) -> tuple[list[BulletinCreate], dict | None]:
    collector = CloudflareBlogCollector()
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


__all__ = ["CloudflareBlogCollector", "FetchParams", "run"]
