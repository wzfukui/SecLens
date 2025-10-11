"""NVIDIA security bulletin collector plugin."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, List, Sequence
import json
import logging
import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from app.schemas import BulletinCreate, ContentInfo, SourceInfo
from app.time_utils import resolve_published_at

API_BASE_URL = "https://www.nvidia.com/content/dam/en-zz/Solutions/product-security/product-security.json"
USER_AGENT = "SecLensNVIDIACollector/1.0"
STATE_FILE_NAME = ".nvidia_cursor"
LOGGER = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "accept": "application/json, text/javascript, */*; q=0.01",
    "accept-language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    "cache-control": "no-cache",
    "pragma": "no-cache",
    "dnt": "1",
    "sec-ch-ua": '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": USER_AGENT,
    "x-requested-with": "XMLHttpRequest"
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
        text = soup.get_text(separator=" ", strip=True)
        
        # Clean up extra whitespace
        clean_text = ' '.join(text.split())
        
        return clean_text
    except Exception as e:
        logging.warning(f"Failed to clean HTML content: {e}")
        # Fallback to original HTML if cleaning fails
        return html_content


def _extract_url_from_html_link(html_link: str) -> str | None:
    """Extract URL from HTML anchor tag."""
    try:
        soup = BeautifulSoup(html_link, "html.parser")
        link_tag = soup.find("a")
        if link_tag and link_tag.get("href"):
            return link_tag["href"]
    except Exception as e:
        LOGGER.warning(f"Failed to extract URL from HTML link: {e}")
    return None


def _extract_cve_ids(cve_str: str | None) -> list[str]:
    """Extract CVE IDs from a string containing CVE identifiers."""
    if not cve_str:
        return []
    
    # Split by comma, semicolon, or other separators and clean up
    cve_candidates = re.split(r'[,;，；]', cve_str)
    cve_ids = []
    
    for cve_candidate in cve_candidates:
        cve_candidate = cve_candidate.strip()
        if cve_candidate.upper().startswith('CVE-'):
            cve_ids.append(cve_candidate.upper())
    
    return cve_ids


class NVIDIACollector:
    """Fetch and normalize NVIDIA security bulletins."""

    def __init__(self, session: requests.Session | None = None, state_path: Path | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.state_path = state_path or Path(__file__).resolve().with_name(STATE_FILE_NAME)

    def load_cursor(self) -> set[str] | None:
        """Load previously seen bulletin IDs from state file."""
        try:
            content = self.state_path.read_text(encoding="utf-8").strip()
            if content:
                return set(json.loads(content))
        except FileNotFoundError:
            pass
        except Exception as e:
            LOGGER.warning(f"Invalid cursor file content: {e}")
        return set()

    def save_cursor(self, bulletin_ids: set[str]) -> None:
        """Save current set of bulletin IDs to state file."""
        try:
            self.state_path.write_text(json.dumps(list(bulletin_ids)), encoding="utf-8")
        except Exception as e:
            LOGGER.error(f"Failed to save cursor file: {e}")

    def fetch_list(self) -> Sequence[dict]:
        """Fetch the list of security bulletins from NVIDIA API."""
        response = self.session.get(API_BASE_URL, timeout=30)
        response.raise_for_status()
        body = response.json()
        
        data = body.get("data")
        if isinstance(data, list):
            # Return only the first 10 records as specified
            return data[:10]
                
        return []

    def fetch_github_detail(self, bulletin_id: str, publish_date: str) -> tuple[str, str] | None:
        """
        Fetch detailed content from NVIDIA GitHub repository.
        Format: github.com/NVIDIA/product-security/blob/main/YYYY/bulletin_id/bulletin_id.md
        """
        try:
            # Extract year from publish date (format: "09 Oct 2025")
            date_parts = publish_date.split()
            if len(date_parts) >= 3:
                year = date_parts[2]
            else:
                # Default to current year if parsing fails
                year = str(datetime.now().year)
            
            url = f"https://raw.githubusercontent.com/NVIDIA/product-security/main/{year}/{bulletin_id}/{bulletin_id}.md"
            response = self.session.get(url, timeout=30)
            
            if response.status_code == 200:
                content = response.text
                # Extract title from the markdown content if present
                title_match = re.search(r'^# (.+)', content, re.MULTILINE)
                title = title_match.group(1) if title_match else f"NVIDIA Security Bulletin {bulletin_id}"
                return title, content
        except Exception as e:
            LOGGER.debug(f"GitHub detail fetch failed for bulletin {bulletin_id}: {e}")
        
        return None

    def fetch_custhelp_detail(self, url: str) -> tuple[str, str] | None:
        """Fetch detailed content from nvidia.custhelp.com."""
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, "html.parser")
            main_content_div = soup.find("div", id="rn_MainColumn", attrs={"role": "main"})
            
            if main_content_div:
                # Extract the text content from the main div
                content = _clean_html_content(str(main_content_div))
                
                # Try to extract title from the page
                title_tag = soup.find("title")
                title = title_tag.get_text().strip() if title_tag else f"Security Bulletin Details"
                
                return title, content
        except Exception as e:
            LOGGER.debug(f"Customer help detail fetch failed for {url}: {e}")
        
        return None

    def normalize(self, item: dict) -> BulletinCreate:
        """Normalize API response item to BulletinCreate model."""
        fetched_at = datetime.now(timezone.utc)
        
        bulletin_id = item.get("bulletin id", "")
        title_html = item.get("title", "")
        severity = item.get("severity", "")
        cve_identifiers = item.get("cve identifier(s)", "")
        publish_date = item.get("publish date", "")
        last_updated = item.get("last updated", "")
        
        # Extract URL from the title HTML
        origin_url = _extract_url_from_html_link(title_html)
        
        # Extract actual title from HTML
        try:
            soup = BeautifulSoup(title_html, "html.parser")
            actual_title = soup.get_text().strip()
        except:
            actual_title = title_html.strip()
        
        # Parse publication time
        published_at, time_meta = resolve_published_at(
            "nvidia_security_bulletin",
            [
                (publish_date, "item.publish_date"),
                (last_updated, "item.last_updated"),
            ],
            fetched_at=fetched_at,
        )
        
        # Parse CVE IDs
        cve_ids = _extract_cve_ids(cve_identifiers)
        
        # Get detailed content from GitHub first, fallback to custhelp
        detail_title = ""
        detail_content = ""
        
        if bulletin_id:
            # Try GitHub first
            github_detail = self.fetch_github_detail(bulletin_id, publish_date)
            if github_detail:
                detail_title, detail_content = github_detail
            elif origin_url:
                # Fallback to custhelp.com
                custhelp_detail = self.fetch_custhelp_detail(origin_url)
                if custhelp_detail:
                    detail_title, detail_content = custhelp_detail
        
        # Use detail title if available, otherwise use the actual title from HTML
        final_title = detail_title if detail_title else actual_title
        
        # Clean up detail content
        clean_content = _clean_html_content(detail_content)
        
        # Determine severity level
        severity_level = None
        if severity:
            severity_lower = severity.lower()
            if "critical" in severity_lower:
                severity_level = "critical"
            elif "high" in severity_lower:
                severity_level = "high"
            elif "medium" in severity_lower or "moderate" in severity_lower:
                severity_level = "medium"
            elif "low" in severity_lower:
                severity_level = "low"
        
        source_info = SourceInfo(
            source_slug="nvidia_security_bulletin",
            external_id=bulletin_id,
            origin_url=origin_url,
        )
        
        content_info = ContentInfo(
            title=final_title,
            summary=clean_content[:500] if clean_content else actual_title,  # First 500 chars as summary
            body_text=clean_content,
            published_at=published_at,
            language="en",
        )
        
        labels: list[str] = []
        if bulletin_id:
            labels.append(f"bulletin_id:{bulletin_id}")
        if cve_ids:
            labels.extend([f"cve:{cve_id}" for cve_id in cve_ids])
        
        topics = ["official_bulletin"]
        if cve_ids:
            topics.append("cve")
        
        extra: dict[str, Any] = {
            "bulletin_id": bulletin_id,
            "severity_raw": severity,
            "cve_identifiers_raw": cve_identifiers,
            "publish_date_raw": publish_date,
            "last_updated_raw": last_updated,
            "title_html": title_html,
            "origin_url": origin_url,
        }
        
        if time_meta:
            extra["time_meta"] = time_meta

        raw = dict(item)

        return BulletinCreate(
            source=source_info,
            content=content_info,
            severity=severity_level,
            fetched_at=fetched_at,
            labels=labels,
            topics=topics,
            extra=extra,
            raw=raw,
        )

    def collect(self) -> List[BulletinCreate]:
        """Collect and normalize NVIDIA security bulletins."""
        items = self.fetch_list()
        
        # Load previously seen bulletin IDs
        seen_ids = self.load_cursor()
        if seen_ids is None:
            seen_ids = set()
        
        # Filter out already seen bulletins
        new_items = [item for item in items if item.get("bulletin id", "") not in seen_ids]
        
        # Process new items
        bulletins = []
        new_ids = set()
        
        for item in new_items:
            bulletin = self.normalize(item)
            bulletins.append(bulletin)
            new_ids.add(bulletin.source.external_id)
        
        # Add new IDs to seen set and save
        all_seen_ids = seen_ids.union(new_ids)
        self.save_cursor(all_seen_ids)
        
        return bulletins


def run(
    ingest_url: str | None = None,
    token: str | None = None,
) -> tuple[list[BulletinCreate], dict | None]:
    """Entry point for scheduler execution."""
    
    collector = NVIDIACollector()
    bulletins = collector.collect()
    response_data = None
    if ingest_url and bulletins:
        session = requests.Session()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        session.headers.update(headers)
        payload = [bulletin.model_dump(mode="json") for bulletin in bulletins]
        api_response = session.post(ingest_url, json=payload, timeout=30)
        api_response.raise_for_status()
        try:
            response_data = api_response.json()
        except json.JSONDecodeError:
            response_data = {"status_code": api_response.status_code}
    return bulletins, response_data


__all__ = ["NVIDIACollector", "run"]