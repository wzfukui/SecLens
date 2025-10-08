"""Tencent Cloud security announcement collector plugin."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, List, Sequence
import json
import logging
import re

import requests

from app.schemas import BulletinCreate, ContentInfo, SourceInfo

LOGGER = logging.getLogger(__name__)
USER_AGENT = "SecLensTencentCloudCollector/1.0"
DEFAULT_LIST_URL = "https://cloud.tencent.com/announce/?categorys=21"
DETAIL_URL_TEMPLATE = "https://cloud.tencent.com/announce/detail/{announce_id}"
DEFAULT_LIMIT = 20
STATE_FILE_NAME = ".cursor"
CHINA_TZ = timezone(timedelta(hours=8))


ASYNC_DATA_PATTERN = re.compile(r"window\['__ASYNC_DATA__'\]\s*=\s*(\[[\s\S]*\])", re.MULTILINE)


@dataclass
class AnnouncementSummary:
    announce_id: str
    title: str
    begin_time: datetime
    end_time: datetime | None
    add_time: datetime | None
    is_important: bool
    announce_type: str | None


@dataclass
class AnnouncementDetail:
    summary: AnnouncementSummary
    content_html: str | None


class _HTMLStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._buffer: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self._buffer.append(data.strip())

    def get_text(self) -> str | None:
        if not self._buffer:
            return None
        return " ".join(self._buffer)


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(value.split()).strip() or None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        dt = dt.replace(tzinfo=CHINA_TZ)
        return dt.astimezone(timezone.utc)
    except ValueError:
        LOGGER.warning("Failed to parse datetime '%s'", value)
        return None


def _html_to_text(html_content: str | None) -> str | None:
    if not html_content:
        return None
    stripped = unescape(html_content)
    parser = _HTMLStripper()
    parser.feed(stripped)
    return _clean_text(parser.get_text())


def _extract_async_payload(html: str) -> list:
    match = ASYNC_DATA_PATTERN.search(html)
    if match:
        payload_raw = match.group(1)
    else:
        marker = "window['__ASYNC_DATA__']"
        idx = html.find(marker)
        if idx == -1:
            raise ValueError("Async payload not found in response")
        eq_idx = html.find('=', idx)
        if eq_idx == -1:
            raise ValueError("Async payload not found in response")
        snippet = html[eq_idx + 1:]
        end_idx = snippet.find('</script>')
        if end_idx != -1:
            snippet = snippet[:end_idx]
        payload_raw = snippet.strip()
    if payload_raw.endswith(';'):
        payload_raw = payload_raw[:-1].strip()
    try:
        return json.loads(payload_raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Failed to decode async payload") from exc


def _iter_containers(data: list) -> Iterable[dict]:
    for item in data:
        if isinstance(item, dict):
            for value in item.values():
                if isinstance(value, list):
                    for element in value:
                        if isinstance(element, dict):
                            yield element


def _parse_announcements(html: str) -> list[AnnouncementSummary]:
    payload = _extract_async_payload(html)
    summaries: list[AnnouncementSummary] = []
    for container in _iter_containers(payload):
        announcements = container.get("announcements")
        if not isinstance(announcements, list):
            continue
        for item in announcements:
            if not isinstance(item, dict):
                continue
            announce_id = str(item.get("announceId"))
            if not announce_id:
                continue
            title = _clean_text(item.get("title")) or announce_id
            begin_time = _parse_datetime(item.get("beginTime"))
            if begin_time is None:
                begin_time = datetime.now(timezone.utc)
            end_time = _parse_datetime(item.get("endTime"))
            add_time = _parse_datetime(item.get("addTime"))
            is_important = str(item.get("isImportant", "0")) == "1"
            announce_type = _clean_text(item.get("type"))
            summaries.append(
                AnnouncementSummary(
                    announce_id=announce_id,
                    title=title,
                    begin_time=begin_time,
                    end_time=end_time,
                    add_time=add_time,
                    is_important=is_important,
                    announce_type=announce_type,
                )
            )
    summaries.sort(key=lambda entry: entry.begin_time)
    return summaries


def _parse_detail(html: str, summary: AnnouncementSummary) -> AnnouncementDetail:
    payload = _extract_async_payload(html)
    content_html: str | None = None
    for container in _iter_containers(payload):
        detail = container.get("detail")
        if isinstance(detail, dict) and str(detail.get("announceId")) == summary.announce_id:
            raw_content = detail.get("content")
            if isinstance(raw_content, str):
                content_html = raw_content
            break
    return AnnouncementDetail(summary=summary, content_html=content_html)


class TencentCloudCollector:
    """Encapsulates fetch, normalize, and cursor persistence for Tencent Cloud announcements."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        list_url: str | None = None,
        state_path: Path | None = None,
    ) -> None:
        self.session = session or requests.Session()
        self.list_url = list_url or DEFAULT_LIST_URL
        self.state_path = state_path or Path(__file__).resolve().with_name(STATE_FILE_NAME)
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )

    # --- Cursor helpers -------------------------------------------------
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
            LOGGER.warning("Invalid cursor value '%s'; ignoring", raw)
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def save_cursor(self, value: datetime) -> None:
        value = value.astimezone(timezone.utc)
        self.state_path.write_text(value.isoformat(), encoding="utf-8")

    # --- Fetch ----------------------------------------------------------
    def fetch_summaries(self) -> Sequence[AnnouncementSummary]:
        response = self.session.get(self.list_url, timeout=30)
        response.raise_for_status()
        html = response.text
        summaries = _parse_announcements(html)
        return summaries

    def fetch_detail(self, summary: AnnouncementSummary) -> AnnouncementDetail:
        detail_url = DETAIL_URL_TEMPLATE.format(announce_id=summary.announce_id)
        response = self.session.get(detail_url, timeout=30)
        response.raise_for_status()
        html = response.text
        return _parse_detail(html, summary)

    # --- Normalize ------------------------------------------------------
    def normalize(self, detail: AnnouncementDetail) -> BulletinCreate:
        summary = detail.summary
        content_html = detail.content_html
        body_text = _html_to_text(content_html)
        origin_url = DETAIL_URL_TEMPLATE.format(announce_id=summary.announce_id)

        source = SourceInfo(
            source_slug="tencent_cloud_security",
            external_id=summary.announce_id,
            origin_url=origin_url,
        )
        content = ContentInfo(
            title=summary.title,
            summary=body_text or summary.title,
            body_text=body_text,
            published_at=summary.begin_time,
            language="zh",
        )

        labels: list[str] = []
        if summary.is_important:
            labels.append("important")
        if summary.announce_type:
            labels.append(f"type:{summary.announce_type}")

        topics = ["official_bulletin", "cloud_security"]

        extra: dict[str, object] = {
            "begin_time": summary.begin_time.isoformat(),
        }
        if summary.end_time:
            extra["end_time"] = summary.end_time.isoformat()
        if summary.add_time:
            extra["add_time"] = summary.add_time.isoformat()
        extra["is_important"] = summary.is_important
        if summary.announce_type:
            extra["announce_type"] = summary.announce_type
        if content_html:
            extra["content_html"] = unescape(content_html)

        return BulletinCreate(
            source=source,
            content=content,
            severity=None,
            fetched_at=datetime.now(timezone.utc),
            labels=labels,
            topics=topics,
            extra=extra,
            raw={
                "summary": {
                    "announce_id": summary.announce_id,
                    "title": summary.title,
                },
                "detail_html": content_html,
            },
        )

    # --- Collection -----------------------------------------------------
    def collect(self, *, limit: int | None = None, force: bool = False) -> List[BulletinCreate]:
        limit = limit or DEFAULT_LIMIT
        cursor = None if force else self.load_cursor()
        summaries = list(self.fetch_summaries())

        selected: list[AnnouncementSummary] = []
        for summary in summaries:
            if cursor and summary.begin_time <= cursor:
                continue
            selected.append(summary)
        if limit is not None and limit > 0:
            selected = selected[-limit:]

        bulletins: list[BulletinCreate] = []
        latest = cursor
        for summary in selected:
            detail = self.fetch_detail(summary)
            bulletin = self.normalize(detail)
            bulletins.append(bulletin)
            if latest is None or summary.begin_time > latest:
                latest = summary.begin_time

        if latest and not force and bulletins:
            self.save_cursor(latest)
        return bulletins


def run(
    ingest_url: str | None = None,
    token: str | None = None,
    *,
    limit: int | None = None,
    force: bool = False,
) -> tuple[list[BulletinCreate], dict | None]:
    """Entrypoint for the Tencent Cloud security announcements plugin."""

    collector = TencentCloudCollector()
    bulletins = collector.collect(limit=limit, force=force)
    response_data = None
    if ingest_url and bulletins:
        session = requests.Session()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        session.headers.update(headers)
        payload = [b.model_dump(mode="json") for b in bulletins]
        response = session.post(ingest_url, json=payload, timeout=30)
        response.raise_for_status()
        try:
            response_data = response.json()
        except json.JSONDecodeError:
            response_data = {"status_code": response.status_code}
    return bulletins, response_data


__all__ = [
    "TencentCloudCollector",
    "AnnouncementSummary",
    "AnnouncementDetail",
    "run",
    "DEFAULT_LIST_URL",
]
