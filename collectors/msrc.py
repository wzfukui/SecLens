"""Microsoft Security Response Center (MSRC) update guide collector."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Iterable, List, Sequence
import xml.etree.ElementTree as ET

import requests

from app.schemas import BulletinCreate, ContentInfo, SourceInfo

FEED_URL = "https://api.msrc.microsoft.com/update-guide/rss"
USER_AGENT = "SecLensCollector/0.1"
REQUEST_HEADERS = {
    "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
    "User-Agent": USER_AGENT,
}


@dataclass
class FetchParams:
    feed_url: str = FEED_URL
    limit: int | None = None


def _parse_pub_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _get_text(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    text = element.text or ""
    text = text.strip()
    return text or None


def _iter_items(channel: ET.Element) -> Iterable[ET.Element]:
    for item in channel.findall("item"):
        yield item


class MsrcCollector:
    """Collector that normalizes MSRC Security Update Guide RSS items."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(REQUEST_HEADERS)

    def fetch(self, params: FetchParams) -> Sequence[dict]:
        response = self.session.get(params.feed_url, timeout=30)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        channel = root.find("channel")
        if channel is None:
            items_root = root.findall(".//item")
            return [self._serialize_item(item) for item in items_root[: params.limit or None]]

        serialized_items: list[dict] = []
        for item in _iter_items(channel):
            serialized_items.append(self._serialize_item(item))
            if params.limit and len(serialized_items) >= params.limit:
                break
        return serialized_items

    def _serialize_item(self, item: ET.Element) -> dict:
        guid_element = item.find("guid")
        categories = [
            _get_text(category)
            for category in item.findall("category")
            if _get_text(category)
        ]
        serialized = {
            "title": _get_text(item.find("title")),
            "link": _get_text(item.find("link")),
            "description": _get_text(item.find("description")),
            "guid": _get_text(guid_element),
            "guid_attributes": dict(guid_element.attrib) if guid_element is not None else {},
            "pub_date": _get_text(item.find("pubDate")),
            "categories": categories,
            "revision": item.attrib.get("Revision"),
            "raw_xml": ET.tostring(item, encoding="unicode"),
        }
        return serialized

    def normalize(self, item: dict) -> BulletinCreate:
        published_at = _parse_pub_date(item.get("pub_date"))
        title = item.get("title") or ""
        description = item.get("description")
        origin_url = item.get("link")
        categories = item.get("categories") or []
        revision = item.get("revision")
        guid = item.get("guid")

        external_id = guid or origin_url or None
        if external_id and revision:
            external_id = f"{external_id}#rev-{revision}"

        source = SourceInfo(
            source_slug="msrc_update_guide",
            external_id=external_id,
            origin_url=origin_url,
        )
        content = ContentInfo(
            title=title,
            summary=description,
            body_text=description,
            published_at=published_at,
            language="en",
        )

        labels = [category for category in categories if category]
        topics = ["official_bulletin"]
        if any(category.upper() == "CVE" for category in categories if isinstance(category, str)):
            topics.append("cve")

        extra: dict[str, object] = {
            "revision": revision,
            "categories": categories,
            "guid": guid,
            "guid_attributes": item.get("guid_attributes") or {},
        }

        raw_payload = {
            key: value
            for key, value in item.items()
            if key not in {"raw_xml"}
        }
        if item.get("raw_xml"):
            raw_payload["raw_xml"] = item["raw_xml"]

        return BulletinCreate(
            source=source,
            content=content,
            severity=None,
            fetched_at=datetime.now(timezone.utc),
            labels=labels,
            topics=topics,
            extra=extra,
            raw=raw_payload,
        )

    def collect(self, params: FetchParams | None = None) -> List[BulletinCreate]:
        params = params or FetchParams()
        items = self.fetch(params)
        return [self.normalize(item) for item in items]


def run(
    ingest_url: str | None = None,
    token: str | None = None,
    params: FetchParams | None = None,
) -> tuple[list[BulletinCreate], dict | None]:
    collector = MsrcCollector()
    bulletins = collector.collect(params=params)
    response_data = None
    if ingest_url:
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


__all__ = ["MsrcCollector", "FetchParams", "run"]
