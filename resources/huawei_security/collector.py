"""Huawei security advisory collector plugin."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List, Sequence

import requests

from app.schemas import BulletinCreate, ContentInfo, SourceInfo

API_URL = "https://securitybulletin.huawei.com/vdmsapi/services/vdmsapi/rest/v1/enterprise/advisories"
USER_AGENT = "SecLensCollector/0.1"
DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    "Content-Type": "application/json",
    "Origin": "https://securitybulletin.huawei.com",
    "Referer": "https://securitybulletin.huawei.com/enterprise/en/security-advisory",
    "User-Agent": USER_AGENT,
}


@dataclass
class FetchParams:
    page_index: int = 1
    page_size: int = 20
    sort: int = 1
    sort_field: str = "publish_date"
    keyword: str = ""
    publish_date_from: str = ""
    publish_date_to: str = ""
    product_line: str = ""
    range: int = 1


def _parse_datetime(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        try:
            # API returns milliseconds since epoch.
            if value > 10_000_000_000:
                value = value / 1000
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            return None
    if isinstance(value, str):
        text = value.strip()
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(text, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except ValueError:
                continue
    return None


class HuaweiCollector:
    """Fetch and normalize Huawei enterprise security advisories."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def fetch(self, params: FetchParams) -> Sequence[dict]:
        payload = {
            "keyword": params.keyword,
            "publishDateFrom": params.publish_date_from,
            "publishDateTo": params.publish_date_to,
            "products": [],
            "sort": params.sort,
            "sortField": params.sort_field,
            "vulId": "",
            "cveId": "",
            "cvssFrom": None,
            "cvssTo": None,
            "severity": [],
            "productVersionsMsg": [],
            "productLine": params.product_line,
            "range": params.range,
        }
        query = {"pageIndex": params.page_index, "pageSize": params.page_size}
        response = self.session.post(API_URL, params=query, json=payload, timeout=30)
        response.raise_for_status()
        body = response.json()
        data = body.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            records = (
                data.get("records")
                or data.get("rows")
                or data.get("list")
                or data.get("data")
            )
            if isinstance(records, list):
                return records
        return []

    def normalize(self, item: dict) -> BulletinCreate:
        title = (
            item.get("advisoryTitle")
            or item.get("title")
            or item.get("name")
            or item.get("sasnTitle")
            or ""
        )
        origin_url = item.get("advisoryUrl") or item.get("url") or item.get("allPath")
        summary = item.get("summary") or item.get("overview") or item.get("description")
        body_text = item.get("content") or item.get("details") or summary
        published_at = (
            _parse_datetime(item.get("publishTime"))
            or _parse_datetime(item.get("pubTime"))
            or _parse_datetime(item.get("publishDate"))
            or _parse_datetime(item.get("releaseTime"))
            or _parse_datetime(item.get("releaseDate"))
        )
        severity = item.get("severity") or item.get("level")
        labels: list[str] = []
        advisory_type = item.get("advisoryType") or item.get("type")
        if advisory_type:
            labels.append(str(advisory_type))
        topics = ["official_bulletin"]
        cve_ids = item.get("cveIds") or item.get("cveList")
        if not cve_ids and isinstance(item.get("vul"), list):
            cve_ids = [entry.get("cveId") for entry in item["vul"] if entry.get("cveId")]
        if isinstance(cve_ids, str):
            cve_ids = [c.strip() for c in cve_ids.split(",") if c.strip()]
        if not isinstance(cve_ids, list):
            cve_ids = []

        external_id = (
            item.get("advisoryNo")
            or item.get("id")
            or item.get("docId")
            or item.get("sasnNo")
        )
        if external_id is not None:
            external_id = str(external_id).strip() or None

        source_info = SourceInfo(
            source_slug="huawei_security",
            external_id=external_id,
            origin_url=origin_url,
        )
        content = ContentInfo(
            title=title,
            summary=summary,
            body_text=body_text,
            published_at=published_at,
            language=item.get("lang") or item.get("language") or "en",
        )
        normalized_labels = [label for label in labels if label]
        if cve_ids:
            topics.append("cve")
        if severity:
            normalized_labels.append(str(severity))

        extra: dict[str, object] = {
            "sasn_no": item.get("sasnNo"),
            "sasn_version": item.get("sasnVersion"),
            "severity": severity,
            "language": item.get("lang") or item.get("language"),
        }
        hw_ids = [entry.get("hwPsirtId") for entry in item.get("vul", []) if isinstance(entry, dict) and entry.get("hwPsirtId")]
        if hw_ids:
            extra["hw_psirt_ids"] = hw_ids
        if item.get("vul"):
            extra["vulnerabilities"] = item.get("vul")

        raw = dict(item)
        if cve_ids:
            raw.setdefault("cveIds", cve_ids)

        return BulletinCreate(
            source=source_info,
            content=content,
            severity=str(severity) if severity else None,
            fetched_at=datetime.now(timezone.utc),
            labels=normalized_labels,
            topics=topics,
            extra=extra,
            raw=raw,
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
    collector = HuaweiCollector()
    bulletins = collector.collect(params=params)
    response_data = None
    if ingest_url:
        session = requests.Session()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        session.headers.update(headers)
        payload = [bulletin.model_dump(mode="json") for bulletin in bulletins]
        response = session.post(ingest_url, json=payload, timeout=30)
        response.raise_for_status()
        response_data = response.json()
    return bulletins, response_data


__all__ = ["HuaweiCollector", "FetchParams", "run"]
