"""Aliyun security bulletin plugin implementation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List, Sequence
import json
import logging

import requests

from app.schemas import BulletinCreate, ContentInfo, SourceInfo

LOGGER = logging.getLogger(__name__)
API_URL = "https://t.aliyun.com/abs/bulletin/bulletinQuery"
DEFAULT_PAGE_SIZE = 50
USER_AGENT = "SecLensAliyunCollector/1.0"


@dataclass(slots=True)
class FetchParams:
    """Pagination and filtering settings for the Aliyun API."""

    page_no: int = 1
    page_size: int = DEFAULT_PAGE_SIZE
    bulletin_type: str = "security"


class AliyunCollector:
    """Encapsulates fetch and normalize logic for Aliyun security bulletins."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://www.aliyun.com",
                "Referer": "https://www.aliyun.com/",
                "User-Agent": USER_AGENT,
            }
        )

    def fetch(self, params: FetchParams) -> Sequence[dict]:
        response = self.session.get(
            API_URL,
            params={
                "pageNo": params.page_no,
                "pageSize": params.page_size,
                "bulletinType": params.bulletin_type,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        info = payload.get("data", {}).get("info", [])
        if not isinstance(info, Iterable):
            LOGGER.warning("Unexpected payload structure from Aliyun: %s", payload)
            return []
        return list(info)

    def normalize(self, item: dict) -> BulletinCreate:
        published_at = None
        publish_time = item.get("publishTime")
        if publish_time:
            try:
                published_at = datetime.fromtimestamp(int(publish_time) / 1000, tz=timezone.utc)
            except (TypeError, ValueError):
                LOGGER.warning("Invalid publishTime %s", publish_time)

        title = item.get("titleFill") or item.get("title") or ""
        origin_url = item.get("url")
        summary = item.get("summary")
        content = item.get("content")
        if not summary and isinstance(content, str):
            summary = content[:280]

        source_info = SourceInfo(
            source_slug="aliyun_security",
            external_id=str(item.get("id")) if item.get("id") is not None else None,
            origin_url=origin_url,
        )
        content_info = ContentInfo(
            title=title,
            summary=summary,
            body_text=content,
            published_at=published_at,
            language=item.get("language"),
        )

        labels: list[str] = []
        for key in ("bulletinType", "bulletinType2", "bulletinType3", "bulletinType4", "bulletinType5"):
            value = item.get(key)
            if value:
                labels.append(value)

        topics = ["official_bulletin"]

        extra: dict[str, object] = {
            "bulletin_type": item.get("bulletinType"),
            "bulletin_type_detail": item.get("bulletinType2"),
            "impact_time": item.get("impactTime"),
            "impact_time_type": item.get("impactTimeType"),
            "status": item.get("status"),
            "product_code": item.get("productCode"),
            "product_info": item.get("productInfo"),
            "language": item.get("language"),
        }
        ext_info = item.get("extInfo")
        if isinstance(ext_info, str):
            try:
                extra["ext_info"] = json.loads(ext_info)
            except json.JSONDecodeError:
                extra["ext_info"] = ext_info
        elif isinstance(ext_info, dict):
            extra["ext_info"] = ext_info

        return BulletinCreate(
            source=source_info,
            content=content_info,
            severity=item.get("securityLevel"),
            fetched_at=datetime.now(timezone.utc),
            labels=labels,
            topics=topics,
            extra=extra,
            raw=item,
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
    """Entry point for scheduler execution.

    Returns normalized bulletins and, if an ingest endpoint is provided, the API response.
    """

    collector = AliyunCollector()
    bulletins = collector.collect(params=params)
    response_data = None
    if ingest_url:
        session = requests.Session()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        session.headers.update(headers)
        payload = [b.model_dump(mode="json") for b in bulletins]
        api_response = session.post(ingest_url, json=payload, timeout=30)
        api_response.raise_for_status()
        response_data = api_response.json()
    return bulletins, response_data


__all__ = ["AliyunCollector", "FetchParams", "run"]
