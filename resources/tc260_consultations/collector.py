"""TC260 standard consultation collector."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Sequence
from urllib.parse import urljoin
import re

import requests
from bs4 import BeautifulSoup

from app.schemas import BulletinCreate, ContentInfo, SourceInfo
from app.time_utils import resolve_published_at

DEFAULT_LIST_URL = "https://www.tc260.org.cn/front/bzzqyjList.html"
DETAIL_BASE_URL = "https://www.tc260.org.cn"
USER_AGENT = "SecLensCollector/0.1"
REQUEST_HEADERS = {
    "User-Agent": USER_AGENT,
    "Referer": "https://www.tc260.org.cn/",
}
DEFAULT_TOPIC = "policy-compliance"
PAGE_SIZE = 10


@dataclass
class FetchParams:
    list_url: str = DEFAULT_LIST_URL
    limit: int | None = None


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


class TC260ConsultationCollector:
    """Collector that scrapes TC260 consultation announcements."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(REQUEST_HEADERS)

    def fetch(self, params: FetchParams) -> Sequence[dict]:
        collected: list[dict] = []
        start = 0
        limit = params.limit

        while True:
            page_url = f"{params.list_url}?start={start}&length={PAGE_SIZE}"
            response = self.session.get(page_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            items = soup.select("li.list-group-item.list_title_news")
            if not items:
                break

            for li in items:
                anchor = li.find("a")
                if anchor is None or not anchor.get("href"):
                    continue
                title = anchor.get_text(strip=True)
                detail_url = urljoin(DETAIL_BASE_URL, anchor["href"])
                deadline = _clean_text(li.find(class_="list_time").get_text(strip=True) if li.find(class_="list_time") else None)

                collected.append(
                    {
                        "title": title,
                        "detail_url": detail_url,
                        "deadline": deadline,
                    }
                )
                if limit and len(collected) >= limit:
                    break
            if limit and len(collected) >= limit:
                break
            start += PAGE_SIZE

        return collected

    def _fetch_detail(self, url: str) -> BeautifulSoup | None:
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        return BeautifulSoup(response.text, "html.parser")

    def normalize(self, item: dict) -> BulletinCreate | None:
        fetched_at = datetime.now(timezone.utc)
        detail_soup = self._fetch_detail(item["detail_url"])
        if detail_soup is None:
            return None

        content_node = detail_soup.select_one("div.news_end")
        if content_node is None:
            return None

        lines = [segment.strip() for segment in content_node.get_text("\n", strip=True).split("\n") if segment.strip()]
        if not lines:
            return None

        # Determine published date.
        published_raw = None
        for line in lines:
            match = re.search(r"\d{4}-\d{2}-\d{2}", line)
            if match:
                published_raw = match.group(0)
                break

        published_at, time_meta = resolve_published_at(
            "tc260_consultations",
            [(published_raw, "detail.date")],
            fetched_at=fetched_at,
        )

        body_text = "\n".join(lines)
        summary = "".join(lines[1:3]) if len(lines) > 1 else lines[0]
        summary = summary[:280]

        source = SourceInfo(
            source_slug="tc260_consultations",
            external_id=item["detail_url"],
            origin_url=item["detail_url"],
        )
        content = ContentInfo(
            title=item["title"],
            summary=summary,
            body_text=body_text,
            published_at=published_at,
            language="zh",
        )

        extra: dict[str, object] = {
            "deadline": item.get("deadline"),
        }
        if time_meta:
            extra["time_meta"] = time_meta

        return BulletinCreate(
            source=source,
            content=content,
            severity=None,
            fetched_at=fetched_at,
            labels=[],
            topics=[DEFAULT_TOPIC],
            extra=extra,
            raw={
                "title": item["title"],
                "detail_url": item["detail_url"],
                "deadline": item.get("deadline"),
                "published_raw": published_raw,
            },
        )

    def collect(self, params: FetchParams | None = None) -> List[BulletinCreate]:
        params = params or FetchParams()
        items = self.fetch(params)
        bulletins: list[BulletinCreate] = []
        for item in items:
            try:
                bulletin = self.normalize(item)
            except requests.RequestException:
                continue
            if bulletin:
                bulletins.append(bulletin)
        return bulletins


def run(
    ingest_url: str | None = None,
    token: str | None = None,
    params: FetchParams | None = None,
) -> tuple[list[BulletinCreate], dict | None]:
    collector = TC260ConsultationCollector()
    bulletins = collector.collect(params=params)
    response_data = None
    if ingest_url and bulletins:
        session = requests.Session()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        session.headers.update(headers)
        payload = [bulletin.model_dump(mode="json") for bulletin in bulletins]
        resp = session.post(ingest_url, json=payload, timeout=30)
        resp.raise_for_status()
        response_data = resp.json()
    return bulletins, response_data


__all__ = ["TC260ConsultationCollector", "FetchParams", "run"]
