"""Antiy SafeInfo collector plugin for security announcements."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List, Sequence
import json
import logging
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from app.schemas import BulletinCreate, ContentInfo, SourceInfo
from app.time_utils import resolve_published_at


DETAIL_API_URL_TEMPLATE = "https://www.antiycloud.com/api/dailyDetail/{daily_time}"
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
    
    daily_time: str | None = None  # If None, will fetch the latest


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
        """Load processed item IDs cache from file."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return set(data.get('ids', []))
            except (json.JSONDecodeError, KeyError):
                return set()
        return set()

    def _save_cache(self, ids: set) -> None:
        """Save processed item IDs cache to file."""
        with open(self.cache_file, 'w', encoding='utf-8') as f:
            json.dump({'ids': list(ids)}, f, ensure_ascii=False)

    def _is_processed(self, item_id: str) -> bool:
        """Check if an item has already been processed."""
        cache = self._load_cache()
        return item_id in cache

    def _mark_processed(self, item_id: str) -> None:
        """Mark an item as processed in the cache."""
        cache = self._load_cache()
        cache.add(item_id)
        self._save_cache(cache)

    def fetch_detail(self, daily_time: str) -> dict | None:
        """Fetch detailed content from the daily detail API."""
        detail_api_url = DETAIL_API_URL_TEMPLATE.format(daily_time=daily_time)
        
        try:
            response = self.session.post(detail_api_url, json=None, timeout=30)  # The API expects null in the body
            response.raise_for_status()
            body = response.json()
            
            if body.get("status") == "success":
                return body
            else:
                logging.warning(f"Antiy detail API returned non-success status: {body.get('status')}")
                return None
        except Exception as e:
            logging.warning(f"Failed to fetch detail for {daily_time}: {e}")
            return None

    def normalize(self, item: dict, daily_time: str) -> BulletinCreate | None:
        """Normalize security announcement data to BulletinCreate model."""
        fetched_at = datetime.now(timezone.utc)
        
        # Extract basic info from the item
        title = item.get("title", "")
        description = item.get("description", "")
        tags = item.get("tags", [])
        refer = item.get("refer", [])
        event_time = item.get("event_time", "")
        
        # Create a unique ID based on title and date for deduplication
        item_id = f"{title[:50]}_{daily_time}" if title else f"entry_{daily_time}"
        
        # Only process if we haven't seen this item before
        if self._is_processed(item_id):
            return None  # Skip duplicates
        
        # Mark this item as processed after successful normalization
        self._mark_processed(item_id)
        
        # Create proper title with prefix
        full_title = f"安天威胁情报中心-{title}" if title else f"安天威胁情报中心-安全简讯 {daily_time}"
        
        # Parse the event_time for published_at
        published_at, time_meta = resolve_published_at(
            "antiy_safeinfor",
            [
                (event_time, "item.event_time"),
                (f"{daily_time} 06:00", "daily_time with default time"),
            ],
            fetched_at=fetched_at,
        )
        
        # Create origin URL for the specific daily report
        origin_url = f"https://www.antiycloud.com/#/dailydetail/{daily_time}?keyword=" if daily_time else None
        
        source_info = SourceInfo(
            source_slug="antiy_safeinfor",
            external_id=item_id,
            origin_url=origin_url,
        )
        
        content_info = ContentInfo(
            title=full_title,
            summary=description[:200] if description else full_title[:200],
            body_text=description,
            published_at=published_at,
            language="zh-CN",
        )
        
        # Build labels
        labels = ["antiy", "security_announcement"]
        labels.extend([f"tag:{tag}" for tag in tags if tag])
        if daily_time:
            labels.append(f"daily:{daily_time}")
        
        # Build topics
        topics = ["official_bulletin", "security_announcement"]
        
        extra: dict[str, object] = {
            "daily_time": daily_time,
            "tags": tags,
            "refer": refer,
            "event_time": event_time,
            "original_title": title,
        }
        
        if time_meta:
            extra["time_meta"] = time_meta

        raw = dict(item)
        raw["daily_time"] = daily_time

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
        
        # If no daily_time is specified, use today's date in YYYYMMDD format
        daily_time = params.daily_time
        if not daily_time:
            daily_time = datetime.now().strftime("%Y%m%d")
        
        data = self.fetch_detail(daily_time)
        if not data:
            return []
        
        items = data.get("data", {}).get("content", [])
        if not isinstance(items, list):
            return []
        
        bulletins = []
        for item in items:
            if isinstance(item, dict):
                bulletin = self.normalize(item, daily_time)
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