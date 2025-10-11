"""CNNVD (China National Vulnerability Database) announcement collector plugin."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List, Sequence
import json
import logging
import os
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from app.schemas import BulletinCreate, ContentInfo, SourceInfo
from app.time_utils import resolve_published_at


LIST_API_URL = "https://www.cnnvd.org.cn/web/homePage/vulWarnList"
DETAIL_API_URL = "https://www.cnnvd.org.cn/web/homePage/vulWarnDetail"
USER_AGENT = "SecLensCNNVDAnnouncementCollector/1.0"
DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://www.cnnvd.org.cn",
    "Referer": "https://www.cnnvd.org.cn/home/warn",
    "User-Agent": USER_AGENT,
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}


@dataclass
class FetchParams:
    """Parameters for fetching CNNVD announcement data."""
    
    page_index: int = 1
    page_size: int = 20  # Recommended size from the requirement
    keyword: str = ""
    report_type: int = 1  # Report type 1 for announcements
    begin_time: str = ""
    end_time: str = ""
    date_type: str = ""


class CNNVDAnnouncementCollector:
    """Fetch and normalize CNNVD announcement data."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        # Create a cache directory in the plugin's directory to store processed warnId values
        self.cache_dir = Path(__file__).parent / ".cache"
        self.cache_dir.mkdir(exist_ok=True)
        self.cache_file = self.cache_dir / "processed_warn_ids.json"

    def _load_cache(self) -> set:
        """Load processed warnId cache from file."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return set(data.get('warn_ids', []))
            except (json.JSONDecodeError, KeyError):
                return set()
        return set()

    def _save_cache(self, warn_ids: set) -> None:
        """Save processed warnId cache to file."""
        with open(self.cache_file, 'w', encoding='utf-8') as f:
            json.dump({'warn_ids': list(warn_ids)}, f, ensure_ascii=False)

    def _is_processed(self, warn_id: str) -> bool:
        """Check if a warnId has already been processed."""
        cache = self._load_cache()
        return warn_id in cache

    def _mark_processed(self, warn_id: str) -> None:
        """Mark a warnId as processed in the cache."""
        cache = self._load_cache()
        cache.add(warn_id)
        self._save_cache(cache)

    def fetch_list(self, params: FetchParams) -> Sequence[dict]:
        """Fetch announcement list from CNNVD."""
        payload = {
            "pageIndex": params.page_index,
            "pageSize": params.page_size,
            "keyword": params.keyword,
            "reportType": params.report_type,
            "beginTime": params.begin_time,
            "endTime": params.end_time,
            "dateType": params.date_type,
            "begin": None,
            "end": None
        }
        
        response = self.session.post(LIST_API_URL, json=payload, timeout=30)
        response.raise_for_status()
        body = response.json()
        
        if body.get("code") != 200:
            logging.warning(f"CNNVD announcement API returned non-200 code: {body.get('code')}")
            return []
        
        data = body.get("data")
        if not data:
            return []
        
        records = data.get("records", [])
        if not isinstance(records, list):
            return []
        
        return records

    def fetch_detail(self, warn_id: str) -> dict | None:
        """Fetch detailed announcement information using multipart form data."""
        # Create multipart form data manually to match the required format
        boundary = "----WebKitFormBoundaryKNzU6jcmBYhNIOmn"
        body = (
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"warnId\"\r\n\r\n"
            f"{warn_id}\r\n"
            f"--{boundary}--\r\n"
        )
        
        # Update headers for multipart form data
        headers = self.session.headers.copy()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        
        try:
            response = self.session.post(
                DETAIL_API_URL, 
                data=body, 
                headers=headers, 
                timeout=30
            )
            response.raise_for_status()
            body = response.json()
            
            if body.get("code") != 200:
                logging.warning(f"CNNVD announcement detail API returned non-200 code: {body.get('code')} for warn_id {warn_id}")
                return None
            
            data = body.get("data", {})
            return data
        except Exception as e:
            logging.warning(f"Failed to fetch detail for announcement {warn_id}: {e}")
            return None

    def normalize(self, item: dict) -> BulletinCreate:
        """Normalize announcement data to BulletinCreate model."""
        fetched_at = datetime.now(timezone.utc)
        
        # Extract basic info from list item
        warn_id = item.get("warnId")
        warn_name = item.get("warnName", "")
        publish_time = item.get("publishTime")
        create_uname = item.get("createUname")
        
        # Only process if we haven't seen this warnId before
        if self._is_processed(warn_id):
            # If already processed, return a minimal bulletin that will likely be filtered
            # This is a way to indicate this item should be skipped
            return BulletinCreate(
                source=SourceInfo(
                    source_slug="cnnvd_announcement",
                    external_id=warn_id,
                    origin_url=None,
                ),
                content=ContentInfo(
                    title=f"SKIPPED: {warn_name}",
                    summary="Skipped duplicate announcement",
                    body_text="",
                    published_at=fetched_at,
                    language="zh-CN",
                ),
                severity=None,
                fetched_at=fetched_at,
                labels=["cnnvd", "duplicate"],
                topics=["official_bulletin", "vulnerability_alert", "cnnvd_announcement"],
                extra={"warn_id": warn_id, "skipped": True},
                raw=item,
            )
        
        # Fetch detailed information
        detail_data = None
        enclosure_content = ""
        if warn_id:
            detail_data = self.fetch_detail(warn_id)
            if detail_data:
                enclosure_content = detail_data.get("enclosureContent", "")
        
        # Parse HTML content to extract text for summary
        summary = ""
        if enclosure_content:
            soup = BeautifulSoup(enclosure_content, 'html.parser')
            # Get first 200 characters of text content as summary
            text_content = soup.get_text()
            summary = text_content[:200].strip()
        
        # Determine publication time - prioritize publishTime from detail if available
        published_at, time_meta = resolve_published_at(
            "cnnvd_announcement",
            [
                (detail_data.get("publishTime") if detail_data else None, "detail.publishTime"),
                (publish_time, "item.publishTime"),
            ],
            fetched_at=fetched_at,
        )
        
        # Mark this warnId as processed after successful normalization
        self._mark_processed(warn_id)
        
        # Create origin URL for the announcement
        origin_url = f"https://www.cnnvd.org.cn/home/warn"  # The general warnings page
        
        source_info = SourceInfo(
            source_slug="cnnvd_announcement",
            external_id=warn_id,
            origin_url=origin_url,
        )
        
        content_info = ContentInfo(
            title=warn_name,
            summary=summary if summary else warn_name[:200],
            body_text=enclosure_content,  # Keep the HTML content as provided
            published_at=published_at,
            language="zh-CN",
        )
        
        # Build labels
        labels = ["cnnvd", "cnnvd_announcement"]
        # Extract any CVE numbers from the title or content
        cve_pattern = r'CVE-\d{4}-\d{4,7}'
        title_cves = re.findall(cve_pattern, warn_name)
        content_cves = re.findall(cve_pattern, enclosure_content)
        all_cves = set(title_cves + content_cves)
        for cve in all_cves:
            labels.append(f"cve:{cve}")
        
        # Build topics
        topics = ["official_bulletin", "vulnerability_alert", "cnnvd_announcement"]
        
        extra: dict[str, object] = {
            "warn_id": warn_id,
            "create_uname": create_uname,
            "warn_name": warn_name,
            "publish_time": publish_time,
        }
        
        if detail_data:
            extra.update({
                "detailed_publish_time": detail_data.get("publishTime"),
                "detailed_warn_name": detail_data.get("warnName"),
                "detailed_create_user": detail_data.get("createUname"),
            })
        
        if time_meta:
            extra["time_meta"] = time_meta

        raw = dict(item)
        if detail_data:
            raw["detail"] = detail_data

        return BulletinCreate(
            source=source_info,
            content=content_info,
            severity="info",  # Default severity for announcements
            fetched_at=fetched_at,
            labels=labels,
            topics=topics,
            extra=extra,
            raw=raw,
        )

    def collect(self, params: FetchParams | None = None) -> List[BulletinCreate]:
        """Collect and normalize CNNVD announcement data."""
        params = params or FetchParams()
        items = self.fetch_list(params)
        bulletins = []
        
        for item in items:
            bulletin = self.normalize(item)
            # Only add bulletins that were not skipped as duplicates
            if not bulletin.extra.get("skipped", False):
                bulletins.append(bulletin)
        
        return bulletins


def run(
    ingest_url: str | None = None,
    token: str | None = None,
    params: FetchParams | None = None,
) -> tuple[list[BulletinCreate], dict | None]:
    """Entry point for scheduler execution."""
    
    collector = CNNVDAnnouncementCollector()
    bulletins = collector.collect(params=params)
    
    # Filter out any bulletin that was marked as skipped
    bulletins = [b for b in bulletins if not b.extra.get("skipped", False)]
    
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


__all__ = ["CNNVDAnnouncementCollector", "FetchParams", "run"]