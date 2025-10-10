"""Collector for CCGP local government procurement announcements."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import ClassVar, List, Sequence
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.schemas import BulletinCreate, ContentInfo, SourceInfo
from app.time_utils import resolve_published_at

DEFAULT_LOCAL_LIST_URL = "https://www.ccgp.gov.cn/cggg/dfgg/"
DEFAULT_CENTRAL_LIST_URL = "https://www.ccgp.gov.cn/cggg/zygg/"
DEFAULT_TOPIC = "policy_compliance"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
REQUEST_HEADERS = {
    "User-Agent": USER_AGENT,
    "Referer": "https://www.ccgp.gov.cn/",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
KEYWORDS = (
    "网安",
    "网络安全",
    "信息安全",
    "提示感知",
    "态势感知",
    "等级保护",
    "防火墙",
)


def _norm_rel(value: str | list[str] | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return value[0] if value else None
    return value


@dataclass
class FetchParams:
    limit: int | None = None
    list_url: str | None = None


class CCGPProcurementCollector:
    """Shared logic for CCGP procurement collectors."""

    slug: ClassVar[str] = "ccgp_procurement"
    list_url: ClassVar[str] = DEFAULT_LOCAL_LIST_URL
    topics: ClassVar[list[str]] = [DEFAULT_TOPIC]

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(REQUEST_HEADERS)

    # ---- Fetch ---------------------------------------------------------
    def fetch(self, params: FetchParams) -> Sequence[dict]:
        list_url = params.list_url or self.list_url
        response = self.session.get(list_url, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        base_for_detail = list_url if params.list_url else self.list_url

        items: list[dict] = []
        for li in soup.select("ul.c_list_bid li"):
            anchor = li.find("a")
            if not anchor or not anchor.get("href"):
                continue
            title = anchor.get("title") or anchor.get_text(strip=True)
            link = urljoin(base_for_detail, anchor["href"])

            ems = li.find_all("em")
            bulletin_type = None
            published_raw = None
            region = None
            purchaser = None
            order_index = 0
            for em in ems:
                rel = _norm_rel(em.get("rel"))
                text_value = em.get_text(strip=True)
                if rel == "bxlx":
                    bulletin_type = text_value
                    continue
                if order_index == 0:
                    published_raw = text_value
                elif order_index == 1:
                    region = text_value
                elif order_index == 2:
                    purchaser = text_value
                order_index += 1

            summary = anchor.get_text(strip=True)
            items.append(
                {
                    "title": title,
                    "summary": summary,
                    "detail_url": link,
                    "published_raw": published_raw,
                    "bulletin_type": bulletin_type,
                    "region": region,
                    "purchaser": purchaser,
                }
            )
            if params.limit and len(items) >= params.limit:
                break
        return items

    # ---- Detail --------------------------------------------------------
    def _fetch_detail(self, url: str) -> BeautifulSoup | None:
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        return BeautifulSoup(response.text, "html.parser")

    # ---- Normalize -----------------------------------------------------
    def _contains_keyword(self, text: str | None) -> bool:
        if not text:
            return False
        return any(keyword in text for keyword in KEYWORDS)

    def normalize(self, item: dict) -> BulletinCreate | None:
        fetched_at = datetime.now(timezone.utc)
        detail_soup = self._fetch_detail(item["detail_url"])
        if detail_soup is None:
            return None
        content_node = detail_soup.select_one("div.vF_detail_content")
        if content_node is None:
            return None

        body_text = content_node.get_text("\n", strip=True)
        text_for_filter = f"{item['title']}\n{body_text}"
        if not self._contains_keyword(text_for_filter):
            return None

        published_at, time_meta = resolve_published_at(
            self.slug,
            [(item.get("published_raw"), "list.published_at")],
            fetched_at=fetched_at,
        )

        summary = body_text[:280] if body_text else item.get("summary")
        source = SourceInfo(
            source_slug=self.slug,
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

        labels: list[str] = []
        if item.get("bulletin_type"):
            labels.append(f"type:{item['bulletin_type']}")
        if item.get("region"):
            labels.append(f"region:{item['region']}")
        if item.get("purchaser"):
            labels.append(f"buyer:{item['purchaser']}")

        extra: dict[str, object] = {
            "bulletin_type": item.get("bulletin_type"),
            "region": item.get("region"),
            "purchaser": item.get("purchaser"),
        }
        if time_meta:
            extra["time_meta"] = time_meta

        raw_payload = dict(item)

        return BulletinCreate(
            source=source,
            content=content,
            severity=None,
            fetched_at=fetched_at,
            labels=labels,
            topics=self.topics,
            extra=extra,
            raw=raw_payload,
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


class CCGPLocalCollector(CCGPProcurementCollector):
    slug = "ccgp_local_procurement"
    list_url = DEFAULT_LOCAL_LIST_URL
    topics = [DEFAULT_TOPIC]


def run(
    ingest_url: str | None = None,
    token: str | None = None,
    params: FetchParams | None = None,
) -> tuple[list[BulletinCreate], dict | None]:
    collector = CCGPLocalCollector()
    bulletins = collector.collect(params=params)
    response_data = None
    if ingest_url and bulletins:
        session = requests.Session()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        session.headers.update(headers)
        payload = [b.model_dump(mode="json") for b in bulletins]
        resp = session.post(ingest_url, json=payload, timeout=30)
        resp.raise_for_status()
        response_data = resp.json()
    return bulletins, response_data


__all__ = ["CCGPLocalCollector", "FetchParams", "run", "CCGPProcurementCollector"]
