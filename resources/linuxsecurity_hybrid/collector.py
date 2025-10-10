"""LinuxSecurity.com hybrid RSS collector."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Sequence
import xml.etree.ElementTree as ET

import requests

from app.schemas import BulletinCreate, ContentInfo, SourceInfo
from app.time_utils import resolve_published_at

DEFAULT_FEED_URL = "https://linuxsecurity.com/linuxsecurity_hybrid.xml"
USER_AGENT = "SecLensCollector/0.1"
REQUEST_HEADERS = {
    "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
    "User-Agent": USER_AGENT,
}


@dataclass
class FetchParams:
    feed_url: str = DEFAULT_FEED_URL
    limit: int | None = None


def _trim(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = text.strip()
    return cleaned or None


def _find_encoded(node: ET.Element) -> str | None:
    for child in node:
        if child.tag.lower().endswith("encoded"):
            return _trim(child.text)
    return None


class LinuxSecurityCollector:
    """Fetch and normalize LinuxSecurity.com RSS entries."""

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
        guid_node = item.find("guid")
        categories = [
            _trim(cat.text)
            for cat in item.findall("category")
            if _trim(cat.text)
        ]
        description = _trim(item.findtext("description"))
        encoded = _find_encoded(item)
        return {
            "title": _trim(item.findtext("title")) or "",
            "link": _trim(item.findtext("link")),
            "description": description,
            "content_encoded": encoded,
            "guid": _trim(guid_node.text if guid_node is not None else None),
            "guid_attributes": dict(guid_node.attrib) if guid_node is not None else {},
            "pub_date": _trim(item.findtext("pubDate")),
            "categories": categories,
            "raw_xml": ET.tostring(item, encoding="unicode"),
        }

    def normalize(self, item: dict) -> BulletinCreate:
        fetched_at = datetime.now(timezone.utc)
        published_at, time_meta = resolve_published_at(
            "linuxsecurity_hybrid",
            [(item.get("pub_date"), "item.pubDate")],
            fetched_at=fetched_at,
        )
        origin_url = item.get("link")
        description = item.get("description")
        body_text = item.get("content_encoded") or description

        external_id = item.get("guid") or origin_url
        source = SourceInfo(
            source_slug="linuxsecurity_hybrid",
            external_id=external_id,
            origin_url=origin_url,
        )
        content = ContentInfo(
            title=item.get("title") or (origin_url or ""),
            summary=description,
            body_text=body_text,
            published_at=published_at,
            language="en",
        )

        categories = item.get("categories") or []
        labels = [f"category:{category.lower()}" for category in categories]
        topics = ["security-news"]

        extra: dict[str, object] = {
            "categories": categories,
            "guid": item.get("guid"),
            "guid_attributes": item.get("guid_attributes") or {},
        }
        if time_meta:
            extra["time_meta"] = time_meta

        raw_payload = {
            key: value
            for key, value in item.items()
            if key != "raw_xml"
        }
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
        return [self.normalize(item) for item in entries]


def run(
    ingest_url: str | None = None,
    token: str | None = None,
    params: FetchParams | None = None,
) -> tuple[list[BulletinCreate], dict | None]:
    collector = LinuxSecurityCollector()
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


__all__ = ["LinuxSecurityCollector", "FetchParams", "run"]
