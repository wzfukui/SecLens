"""Doonsec WeChat RSS collector."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import html
import re
from typing import List, Sequence
import xml.etree.ElementTree as ET

import requests

from app.schemas import BulletinCreate, ContentInfo, SourceInfo
from app.time_utils import resolve_published_at

DEFAULT_FEED_URL = "https://wechat.doonsec.com/rss.xml"
USER_AGENT = "SecLensCollector/0.1"
REQUEST_HEADERS = {
    "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
    "User-Agent": USER_AGENT,
}

_HEX_ESCAPE_RE = re.compile(r"\\x([0-9A-Fa-f]{2})")
_UNICODE_ESCAPE_RE = re.compile(r"\\u([0-9A-Fa-f]{4})")


@dataclass
class FetchParams:
    feed_url: str = DEFAULT_FEED_URL
    limit: int | None = None


def _trim(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = text.strip()
    return cleaned or None


def _clean_text(value: str | None) -> str | None:
    """Normalize backslash-escaped characters and HTML entities."""

    if value is None:
        return None

    cleaned = value
    if "\\" in cleaned:
        cleaned = cleaned.replace('\\"', '"').replace("\\'", "'")

        def _hex_repl(match: re.Match[str]) -> str:
            try:
                return chr(int(match.group(1), 16))
            except ValueError:
                return match.group(0)

        def _unicode_repl(match: re.Match[str]) -> str:
            try:
                return chr(int(match.group(1), 16))
            except ValueError:
                return match.group(0)

        cleaned = _HEX_ESCAPE_RE.sub(_hex_repl, cleaned)
        cleaned = _UNICODE_ESCAPE_RE.sub(_unicode_repl, cleaned)
        cleaned = cleaned.replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "\r")
        cleaned = cleaned.replace("\\\\", "\\")

    return html.unescape(cleaned)


class DoonsecCollector:
    """Collect and normalize Doonsec WeChat feed entries."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(REQUEST_HEADERS)

    def fetch(self, params: FetchParams) -> Sequence[dict]:
        response = self.session.get(params.feed_url, timeout=30)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        channel = root.find("channel")
        items = channel.findall("item") if channel is not None else root.findall(".//item")

        serialized: list[dict] = []
        for item in items:
            serialized.append(self._serialize_item(item))
            if params.limit and len(serialized) >= params.limit:
                break
        return serialized

    def _serialize_item(self, item: ET.Element) -> dict:
        return {
            "title": _trim(item.findtext("title")) or "",
            "link": _trim(item.findtext("link")),
            "description": _trim(item.findtext("description")),
            "author": _trim(item.findtext("author")),
            "category": _trim(item.findtext("category")),
            "pub_date": _trim(item.findtext("pubDate")),
            "raw_xml": ET.tostring(item, encoding="unicode"),
        }

    def normalize(self, item: dict) -> BulletinCreate:
        fetched_at = datetime.now(timezone.utc)
        published_at, time_meta = resolve_published_at(
            "doonsec_wechat",
            [(item.get("pub_date"), "item.pubDate")],
            fetched_at=fetched_at,
        )
        origin_url = _clean_text(item.get("link"))
        title = _clean_text(item.get("title")) or (origin_url or "")
        description = _clean_text(item.get("description"))
        author = _clean_text(item.get("author"))
        category = _clean_text(item.get("category"))

        external_id = origin_url or item.get("link")
        source = SourceInfo(
            source_slug="doonsec_wechat",
            external_id=external_id,
            origin_url=origin_url,
        )
        content = ContentInfo(
            title=title,
            summary=description,
            body_text=description,
            published_at=published_at,
            language="zh",
        )

        labels: list[str] = []
        if category:
            labels.append(f"category:{category.lower()}")
        if author:
            labels.append(f"author:{author.lower()}")
        topics = ["security-news"]

        extra = {
            "author": author,
            "category": category,
        }
        if time_meta:
            extra["time_meta"] = time_meta
        raw_payload = {k: v for k, v in item.items() if k != "raw_xml"}
        if item.get("raw_xml"):
            raw_payload["raw_xml"] = item["raw_xml"]

        return BulletinCreate(
            source=source,
            content=content,
            severity=None,
            fetched_at=fetched_at,
            labels=labels,
            topics=topics,
            extra=extra,
            raw=raw_payload,
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
    collector = DoonsecCollector()
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


__all__ = ["DoonsecCollector", "FetchParams", "run"]
