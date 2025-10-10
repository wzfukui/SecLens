"""Collector for Amazon Linux 1 ALAS RSS feed."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Sequence
import logging
import re
import unicodedata
import xml.etree.ElementTree as ET

import requests
from email.utils import parsedate_to_datetime

from app.schemas import BulletinCreate, ContentInfo, SourceInfo
from app.time_utils import resolve_published_at


LOGGER = logging.getLogger(__name__)

FEED_URL = "https://alas.aws.amazon.com/alas.rss"
USER_AGENT = "SecLensAmazonLinuxCollector/1.0"
REQUEST_HEADERS = {
    "Accept": "application/rss+xml,application/xml;q=0.9,text/xml;q=0.8,*/*;q=0.7",
    "User-Agent": USER_AGENT,
}

TITLE_PATTERN = re.compile(r"^(?P<bulletin>[A-Z0-9-]+)\s*(?:\((?P<severity>[^)]+)\))?\s*:\s*(?P<component>.+?)\s*$")
CVE_PATTERN = re.compile(r"CVE-\d{4}-\d{4,7}", re.IGNORECASE)


@dataclass
class FetchParams:
    feed_url: str = FEED_URL
    limit: int | None = 10


def _clean_text(value: str | None) -> str | None:
    if not value:
        return None
    normalised = unicodedata.normalize("NFKC", value)
    cleaned = " ".join(normalised.split())
    return cleaned or None


def _parse_pubdate(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _extract_cves(text: str | None) -> list[str]:
    if not text:
        return []
    return sorted({match.upper() for match in CVE_PATTERN.findall(text)})


def _parse_title(title: str | None) -> tuple[str | None, str | None, str | None]:
    if not title:
        return None, None, None
    match = TITLE_PATTERN.match(title.strip())
    if not match:
        return title.strip(), None, None
    return match.group("bulletin"), match.group("severity"), match.group("component")


class AmazonLinux1Collector:
    """Fetch and normalise Amazon Linux 1 security bulletins."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(REQUEST_HEADERS)

    def fetch(self, params: FetchParams) -> Sequence[dict]:
        response = self.session.get(params.feed_url, timeout=30)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        items: list[dict] = []
        for item in root.findall("./channel/item"):
            parsed = self._parse_item(item)
            if not parsed:
                continue
            items.append(parsed)
            if params.limit and len(items) >= params.limit:
                break
        return items

    def _parse_item(self, item: ET.Element) -> dict | None:
        title_raw = item.findtext("title")
        description_raw = item.findtext("description")
        link = _clean_text(item.findtext("link"))
        guid = _clean_text(item.findtext("guid"))
        pub_date = _parse_pubdate(item.findtext("pubDate"))

        if not title_raw and not link:
            return None

        title_clean = _clean_text(title_raw) or link or guid
        description_clean = _clean_text(description_raw)
        bulletin_id, severity, component = _parse_title(title_clean)
        cves = _extract_cves(description_raw or "")

        return {
            "title": title_clean,
            "link": link,
            "guid": guid,
            "pub_date": pub_date,
            "description": description_clean,
            "bulletin_id": bulletin_id or title_clean,
            "severity": severity,
            "component": component,
            "cves": cves,
        }

    def normalize(self, entry: dict) -> BulletinCreate:
        fetched_at = datetime.now(timezone.utc)

        candidates: list[tuple[object, str]] = []
        if entry.get("pub_date"):
            candidates.append((entry["pub_date"], "item.pubDate"))

        published_at, time_meta = resolve_published_at(
            "amazon_linux_al1",
            candidates,
            fetched_at=fetched_at,
        )

        origin_url = entry.get("link") or entry.get("guid")
        external_id = entry.get("bulletin_id") or origin_url

        summary = entry.get("description")
        body_text = entry.get("description")

        labels = ["vendor:aws", "distribution:al1"]
        if entry.get("severity"):
            labels.append(f"severity:{entry['severity'].strip().lower()}")
        if entry.get("component"):
            labels.append(f"component:{entry['component'].strip().lower()}")
        for cve in entry.get("cves") or []:
            labels.append(f"cve:{cve.lower()}")

        labels = [_clean_text(label) for label in labels if _clean_text(label)]

        topics = ["vendor-update", "official_advisory"]

        extra: dict[str, object] = {
            "bulletin_id": entry.get("bulletin_id"),
            "severity": entry.get("severity"),
            "component": entry.get("component"),
            "cves": entry.get("cves"),
        }
        if time_meta:
            extra["time_meta"] = time_meta

        return BulletinCreate(
            source=SourceInfo(
                source_slug="amazon_linux_al1",
                external_id=str(external_id),
                origin_url=origin_url,
            ),
            content=ContentInfo(
                title=entry.get("title") or external_id,
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
        entries = self.fetch(params)
        bulletins: list[BulletinCreate] = []
        for entry in entries:
            try:
                bulletins.append(self.normalize(entry))
            except Exception as exc:  # pragma: no cover
                LOGGER.exception("Failed to normalise Amazon Linux 1 entry: %s", entry, exc_info=exc)
        return bulletins


def run(
    ingest_url: str | None = None,
    token: str | None = None,
    params: FetchParams | None = None,
) -> tuple[list[BulletinCreate], dict | None]:
    collector = AmazonLinux1Collector()
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


__all__ = ["AmazonLinux1Collector", "FetchParams", "run"]

