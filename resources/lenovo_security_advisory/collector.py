"""Lenovo security advisory collector plugin."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List, Sequence
import json
import logging
import re

import requests
from bs4 import BeautifulSoup

from app.schemas import BulletinCreate, ContentInfo, SourceInfo
from app.time_utils import resolve_published_at

API_BASE_URL = "https://newsupport.lenovo.com.cn/api/SafeNotice/SafeNoticeListInfo"
DETAIL_API_URL = "https://iknow.lenovo.com.cn/knowledgeapi/api/knowledge/knowledgeDetails"
USER_AGENT = "SecLensLenovoCollector/1.0"
DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json",
    "Origin": "https://newsupport.lenovo.com.cn",
    "Referer": "https://newsupport.lenovo.com.cn/SecurityPolicy.html",
    "User-Agent": USER_AGENT,
}


def _clean_html_content(html_content: str | None) -> str:
    """Extract clean text from HTML content using BeautifulSoup, with fallback to original HTML."""
    if not html_content:
        return ""
    
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        
        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.decompose()
        
        # Get text and clean it up
        text = soup.get_text(separator="\n", strip=True)
        
        # Clean up extra whitespace
        lines = [line.strip() for line in text.splitlines()]
        clean_text = '\n'.join(line for line in lines if line)
        
        return clean_text
    except Exception as e:
        logging.warning(f"Failed to clean HTML content: {e}")
        # Fallback to original HTML if cleaning fails
        return html_content


@dataclass
class FetchParams:
    """Pagination and filtering settings for the Lenovo API."""
    
    page_index: int = 1
    page_size: int = 20
    order_way: int = 0  # 0 for descending, 1 for ascending


class LenovoCollector:
    """Fetch and normalize Lenovo product security advisories."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def fetch_list(self, params: FetchParams) -> Sequence[dict]:
        """Fetch the list of security advisories from Lenovo API."""
        response = self.session.get(
            API_BASE_URL,
            params={
                "order_way": params.order_way,
                "page_index": params.page_index,
                "page_size": params.page_size,
            },
            timeout=30
        )
        response.raise_for_status()
        body = response.json()
        
        data = body.get("data")
        if isinstance(data, dict):
            items = data.get("data")
            if isinstance(items, list):
                return items
                
        return []

    def fetch_detail(self, knowledge_no: str) -> dict | None:
        """Fetch detailed information for a specific advisory."""
        try:
            response = self.session.get(
                DETAIL_API_URL,
                params={
                    "knowledgeNo": knowledge_no,
                    "keyWord": knowledge_no,
                    "keyWordId": ""
                },
                timeout=30
            )
            response.raise_for_status()
            body = response.json()
            if body.get("code") == 200:
                return body.get("data")
        except Exception as e:
            logging.warning(f"Failed to fetch detail for knowledgeNo {knowledge_no}: {e}")
        
        return None

    def extract_knowledge_no_from_url(self, url: str) -> str | None:
        """Extract knowledge number from the notice_link URL."""
        # Example URL: https://iknow.lenovo.com.cn/detail/431977?type=undefined&keyword=431977&keyWordId=
        match = re.search(r'detail/(\d+)', url)
        if match:
            return match.group(1)
        return None

    def normalize(self, item: dict) -> BulletinCreate:
        """Normalize API response item to BulletinCreate model."""
        fetched_at = datetime.now(timezone.utc)
        
        # Extract knowledge number from notice_link for fetching details
        notice_link = item.get("notice_link", "")
        knowledge_no = self.extract_knowledge_no_from_url(notice_link)
        
        # Get detailed content
        detail_data = None
        content_html = ""
        if knowledge_no:
            detail_data = self.fetch_detail(knowledge_no)
            if detail_data:
                content_html = detail_data.get("content", "")
        
        # Extract title - prefer detailed title if available
        title = detail_data.get("title", "") if detail_data else ""
        if not title:
            title = item.get("notice_name", "") or item.get("title", "") or ""
        
        # Extract summary/digest
        summary = ""
        if detail_data and detail_data.get("digest"):
            summary = detail_data["digest"]
        else:
            summary = item.get("notice_name", "")
        
        # Parse publication time from list API
        published_at, time_meta = resolve_published_at(
            "lenovo_security_advisory",
            [
                (item.get("publish_at"), "item.publish_at"),
                (item.get("created_at"), "item.created_at"),
                (item.get("last_at"), "item.last_at"),
            ],
            fetched_at=fetched_at,
        )
        
        # Fallback to detail API if needed
        if not published_at and detail_data:
            published_at, time_meta = resolve_published_at(
                "lenovo_security_advisory",
                [
                    (detail_data.get("createTime"), "detail.createTime"),
                    (detail_data.get("updateTime"), "detail.updateTime"),
                ],
                fetched_at=fetched_at,
            )
        
        # Parse CVE IDs
        cve_str = item.get("notice_cves", "")
        cve_ids = []
        if cve_str:
            # Split by '、' or ',' and clean up
            cve_candidates = re.split(r'[、,，]', cve_str)
            for cve_candidate in cve_candidates:
                cve_candidate = cve_candidate.strip()
                if cve_candidate.upper().startswith('CVE-'):
                    cve_ids.append(cve_candidate.upper())
        
        # Extract severity from content if available
        severity = None
        if content_html:
            # Look for severity in the HTML content
            if "严重性：高" in content_html or "严重性</a>：高" in content_html:
                severity = "high"
            elif "严重性：中" in content_html or "严重性</a>：中" in content_html:
                severity = "medium"
            elif "严重性：低" in content_html or "严重性</a>：低" in content_html:
                severity = "low"
        
        origin_url = notice_link
        external_id = item.get("notice_number") or item.get("notice_code")
        if external_id is not None:
            external_id = str(external_id).strip() or None

        # Clean the HTML content to extract plain text
        clean_content = _clean_html_content(content_html)

        source_info = SourceInfo(
            source_slug="lenovo_security_advisory",
            external_id=external_id,
            origin_url=origin_url,
        )
        
        content_info = ContentInfo(
            title=title,
            summary=summary,
            body_text=clean_content,
            published_at=published_at,
            language="zh-CN",  # Lenovo security notices are typically in Chinese
        )
        
        labels: list[str] = []
        if item.get("notice_number"):
            labels.append(item["notice_number"])
        
        topics = ["official_bulletin"]
        if cve_ids:
            topics.append("cve")
        
        extra: dict[str, object] = {
            "notice_code": item.get("notice_code"),
            "notice_number": item.get("notice_number"),
            "power_level": item.get("power_level"),
            "created_at": item.get("created_at"),
            "last_at": item.get("last_at"),
            "updated_at": item.get("updated_at"),
            "cves_raw": item.get("notice_cves"),
        }
        
        if detail_data:
            extra.update({
                "knowledge_no": detail_data.get("knowledgeNo"),
                "detail_title": detail_data.get("title"),
                "digest": detail_data.get("digest"),
                "create_time": detail_data.get("createTime"),
                "update_time": detail_data.get("updateTime"),
                "line_category_name": detail_data.get("lineCategoryName"),
                "line_category_names": detail_data.get("lineCategoryNameS"),
                "question_category_name": detail_data.get("questionCategoryName"),
                "first_topic_name": detail_data.get("firstTopicName"),
                "sub_topic_name": detail_data.get("subTopicName"),
                "keywords": detail_data.get("keyWords"),
                "version_no": detail_data.get("versionNo"),
                "html_content": content_html,  # Store original HTML for reference
            })
        
        if time_meta:
            extra["time_meta"] = time_meta

        raw = dict(item)
        if detail_data:
            raw["detail"] = detail_data

        return BulletinCreate(
            source=source_info,
            content=content_info,
            severity=severity,
            fetched_at=fetched_at,
            labels=labels,
            topics=topics,
            extra=extra,
            raw=raw,
        )

    def collect(self, params: FetchParams | None = None) -> List[BulletinCreate]:
        """Collect and normalize Lenovo security advisories."""
        params = params or FetchParams()
        items = self.fetch_list(params)
        return [self.normalize(item) for item in items]


def run(
    ingest_url: str | None = None,
    token: str | None = None,
    params: FetchParams | None = None,
) -> tuple[list[BulletinCreate], dict | None]:
    """Entry point for scheduler execution."""
    
    collector = LenovoCollector()
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


__all__ = ["LenovoCollector", "FetchParams", "run"]