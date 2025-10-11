"""Collector plugin for MIIT CNVDB vulnerability alerts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List, Sequence
import logging

import requests
from bs4 import BeautifulSoup

from app.schemas import BulletinCreate, ContentInfo, SourceInfo
from app.time_utils import resolve_published_at
from .cnvdb_client import CNVDBClient

LOGGER = logging.getLogger(__name__)
USER_AGENT = "SecLensCNVDBCollector/1.0"
DEFAULT_PAGE_SIZE = 15
DEFAULT_LANGUAGE = "zh"
ORIGIN_URL_TEMPLATE = "https://cnvdb.org.cn/#/policy/detail/{policy_id}"


def _html_to_text(html: str | None) -> str | None:
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    tokens = [segment.strip() for segment in soup.stripped_strings]
    if not tokens:
        return None
    return " ".join(tokens)


def _build_summary(text: str | None, length: int = 280) -> str | None:
    if not text:
        return None
    if len(text) <= length:
        return text
    return text[: length - 1].rstrip() + "…"


@dataclass
class FetchParams:
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE


class CNVDBCollector:
    """Encapsulates fetch and normalisation logic for CNVDB policies."""

    def __init__(self, client: CNVDBClient | None = None) -> None:
        self.client = client or CNVDBClient()
        # Overwrite user agent for ingest requests
        session = getattr(self.client, "session", None)
        if session is not None and hasattr(session, "headers"):
            session.headers.setdefault("User-Agent", USER_AGENT)

    def fetch_records(self, params: FetchParams) -> list[dict]:
        payload = self.client.list_policies(page=params.page, page_size=params.page_size)
        records = payload.get("data", {}).get("records", [])
        if not isinstance(records, Iterable):
            LOGGER.warning("Unexpected list payload from CNVDB: %s", payload)
            return []
        filtered: list[dict] = []
        for item in records:
            if isinstance(item, dict):
                filtered.append(item)
        return filtered

    def fetch_detail(self, policy_id: str) -> dict | None:
        try:
            payload = self.client.get_policy_detail(policy_id)
        except requests.HTTPError:
            LOGGER.exception("Failed to fetch detail for policy %s", policy_id)
            return None
        data = payload.get("data")
        if isinstance(data, dict):
            return data
        LOGGER.warning("Unexpected detail payload for %s: %s", policy_id, payload)
        return None

    def normalize(self, record: dict, detail: dict | None) -> BulletinCreate:
        fetched_at = datetime.now(timezone.utc)

        policy_id: str | None = None
        record_id = record.get("id")
        if record_id:
            policy_id = str(record_id)
        elif detail and detail.get("id"):
            policy_id = str(detail.get("id"))

        published_at, time_meta = resolve_published_at(
            "cnvdb",
            [
                (detail.get("releaseTime") if detail else None, "detail.releaseTime"),
                (detail.get("updateTime") if detail else None, "detail.updateTime"),
                (record.get("releaseTime"), "record.releaseTime"),
            ],
            fetched_at=fetched_at,
        )

        content_html = (detail or {}).get("content")
        body_text = _html_to_text(content_html)
        summary = _build_summary(body_text)
        origin_url = ORIGIN_URL_TEMPLATE.format(policy_id=policy_id) if policy_id else None

        source_info = SourceInfo(
            source_slug="cnvdb",
            external_id=policy_id or None,
            origin_url=origin_url,
        )
        content_info = ContentInfo(
            title=(detail or record).get("title") or "",
            summary=summary,
            body_text=body_text,
            published_at=published_at,
            language=DEFAULT_LANGUAGE,
        )

        extra: dict[str, object] = {
            "origin": (detail or record).get("origin"),
            "system_type": (detail or record).get("systemType"),
            "release_time_raw": (detail or record).get("releaseTime"),
            "content_html": content_html,
        }
        if detail:
            extra.update(
                {
                    "create_time": detail.get("createTime"),
                    "update_time": detail.get("updateTime"),
                    "click_number": detail.get("clickNumber"),
                    "record_type": detail.get("type"),
                }
            )
        if time_meta:
            extra["time_meta"] = time_meta

        labels: list[str] = []
        if record.get("keyword"):
            labels.append(f"keyword:{record['keyword']}")
        if record.get("systemType") is not None:
            labels.append(f"system_type:{record['systemType']}")

        topics = ["official_bulletin", "vulnerability_warning"]

        return BulletinCreate(
            source=source_info,
            content=content_info,
            severity=None,
            fetched_at=fetched_at,
            labels=labels,
            topics=topics,
            extra=extra,
            raw={"summary": record, "detail": detail} if detail else {"summary": record},
        )

    def collect(self, params: FetchParams | None = None) -> List[BulletinCreate]:
        params = params or FetchParams()
        records = self.fetch_records(params)
        bulletins: list[BulletinCreate] = []
        for record in records:
            policy_id = record.get("id")
            detail = self.fetch_detail(str(policy_id)) if policy_id is not None else None
            bulletin = self.normalize(record, detail)
            bulletins.append(bulletin)
        return bulletins


def run(
    ingest_url: str | None = None,
    token: str | None = None,
    params: FetchParams | None = None,
) -> tuple[list[BulletinCreate], dict | None]:
    collector = CNVDBCollector()
    bulletins = collector.collect(params=params)
    response_data = None
    if ingest_url:
        session = requests.Session()
        headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        session.headers.update(headers)
        payload = [bulletin.model_dump(mode="json") for bulletin in bulletins]
        api_response = session.post(ingest_url, json=payload, timeout=30)
        api_response.raise_for_status()
        try:
            response_data = api_response.json()
        except ValueError:
            response_data = {"status_code": api_response.status_code}
    return bulletins, response_data


__all__ = ["CNVDBCollector", "FetchParams", "run"]
