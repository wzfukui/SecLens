"""Antiy SafeInfo collector plugin for security announcements."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List, Sequence
import json
import logging
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from app.schemas import BulletinCreate, ContentInfo, SourceInfo
from app.time_utils import resolve_published_at


LIST_API_URL = "https://www.antiycloud.com/api/daily/list"
DETAIL_URL_TEMPLATE = "https://www.antiycloud.com/#/dailydetail/{daily_time}?keyword="
USER_AGENT = "SecLensAntiySafeInfoCollector/1.0"
DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json",
    "Origin": "https://www.antiycloud.com",
    "Referer": "https://www.antiycloud.com/",
    "User-Agent": USER_AGENT,
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}


@dataclass
class FetchParams:
    """Parameters for fetching Antiy SafeInfo data."""
    
    page: int = 1
    page_size: int = 10


class AntiySafeInfoCollector:
    """Fetch and normalize Antiy SafeInfo security announcement data."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        # Create a cache directory in the plugin's directory to store processed IDs
        self.cache_dir = Path(__file__).parent / ".cache"
        self.cache_dir.mkdir(exist_ok=True)
        self.cache_file = self.cache_dir / "processed_ids.json"

    def _load_cache(self) -> set:
        """Load processed IDs cache from file."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return set(data.get('ids', []))
            except (json.JSONDecodeError, KeyError):
                return set()
        return set()

    def _save_cache(self, ids: set) -> None:
        """Save processed IDs cache to file."""
        with open(self.cache_file, 'w', encoding='utf-8') as f:
            json.dump({'ids': list(ids)}, f, ensure_ascii=False)

    def _is_processed(self, item_id: int) -> bool:
        """Check if an item has already been processed."""
        cache = self._load_cache()
        return item_id in cache

    def _mark_processed(self, item_id: int) -> None:
        """Mark an item as processed in the cache."""
        cache = self._load_cache()
        cache.add(item_id)
        self._save_cache(cache)

    def fetch_list(self, params: FetchParams) -> Sequence[dict]:
        """Fetch security announcement list from Antiy."""
        payload = {
            "search": {"value": ""},
            "type": "",
            "pagination": {
                "current": params.page,
                "pageSize": params.page_size,
                "total": 0
            },
            "sorter": {
                "field": "abrief_date",
                "order": "descend"
            },
            "dict": {
                "time_range": [],
                "selValue": ""
            }
        }
        
        response = self.session.post(LIST_API_URL, json=payload, timeout=30)
        response.raise_for_status()
        body = response.json()
        
        if body.get("status") != "success":
            logging.warning(f"Antiy API returned non-success status: {body.get('status')}")
            return []
        
        data = body.get("data", {})
        if not data:
            return []
        
        current = data.get("current", [])
        if not isinstance(current, list):
            return []
        
        return current

    def fetch_detail(self, daily_time: str) -> str | None:
        """Fetch detailed security announcement content (in this case, we just use the content provided in the list API)."""
        # The details are already provided in the list API response, so we don't need to fetch separately
        # But if needed for future enhancements to get more detailed content via web scraping, this could be implemented
        return None

    def normalize(self, item: dict) -> BulletinCreate | None:
        """Normalize security announcement data to BulletinCreate model."""
        fetched_at = datetime.now(timezone.utc)
        
        # Extract basic info from list item
        item_id = item.get("id")
        title = item.get("title", "")
        content = item.get("content", "")
        daily_time = item.get("daily_time", "")
        time_str = item.get("time", "")
        status = item.get("status")
        
        # Only process if we haven't seen this item before
        if self._is_processed(item_id):
            return None  # Skip duplicates
        
        # Mark this item as processed after successful normalization
        self._mark_processed(item_id)
        
        # Prepend "安天威胁情报中心-" to the title
        full_title = f"安天威胁情报中心-{title}" if title else "安天威胁情报中心-安全简讯"
        
        # Parse the time_str to extract date for published_at
        published_at, time_meta = resolve_published_at(
            "antiy_safeinfor",
            [
                (time_str, "item.time"),
            ],
            fetched_at=fetched_at,
        )
        
        # Extract text content by removing HTML tags from the content
        soup = BeautifulSoup(content, 'html.parser')
        text_content = soup.get_text()
        
        # Create origin URL for the specific daily report
        origin_url = f"https://www.antiycloud.com/#/dailydetail/{daily_time}?keyword=" if daily_time else None
        
        source_info = SourceInfo(
            source_slug="antiy_safeinfor",
            external_id=str(item_id) if item_id else None,
            origin_url=origin_url,
        )
        
        content_info = ContentInfo(
            title=full_title,
            summary=text_content[:200].strip() if text_content else full_title[:200],
            body_text=text_content,
            published_at=published_at,
            language="zh-CN",
        )
        
        # Build labels
        labels = ["antiy", "security_announcement"]
        if daily_time:
            labels.append(f"daily:{daily_time}")
        
        # Build topics
        topics = ["official_bulletin", "security_announcement"]
        
        extra: dict[str, object] = {
            "item_id": item_id,
            "title": title,
            "daily_time": daily_time,
            "time_str": time_str,
            "status": status,
        }
        
        if time_meta:
            extra["time_meta"] = time_meta

        raw = dict(item)

        return BulletinCreate(
            source=source_info,
            content=content_info,
            severity=None,  # Security announcements are typically informational
            fetched_at=fetched_at,
            labels=labels,
            topics=topics,
            extra=extra,
            raw=raw,
        )

    def collect(self, params: FetchParams | None = None) -> List[BulletinCreate]:
        """Collect and normalize Antiy SafeInfo security announcement data."""
        params = params or FetchParams()
        items = self.fetch_list(params)
        bulletins = []
        
        for item in items:
            bulletin = self.normalize(item)
            if bulletin is not None:
                bulletins.append(bulletin)
        
        return bulletins


def run(
    ingest_url: str | None = None,
    token: str | None = None,
    params: FetchParams | None = None,
) -> tuple[list[BulletinCreate], dict | None]:
    """Entry point for scheduler execution."""
    
    collector = AntiySafeInfoCollector()
    bulletins = collector.collect(params=params)
    response_data = None
    if ingest_url:
        session = requests.Session()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        session.headers.update(headers)
        payload = [bulletin.model_dump(mode="json") for bulletin in bulletins]
        api_response = session.post(ingest_url, json=payload, timeout=30)
        api_response.raise_for_status()
        response_data = api_response.json()
    return bulletins, response_data


__all__ = ["AntiySafeInfoCollector", "FetchParams", "run"]