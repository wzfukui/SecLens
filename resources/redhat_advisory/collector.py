"""Red Hat security advisory collector."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence
import logging

import requests
from bs4 import BeautifulSoup

from app.schemas import BulletinCreate, ContentInfo, SourceInfo
from app.time_utils import resolve_published_at

LOGGER = logging.getLogger(__name__)
API_URL = "https://access.redhat.com/hydra/rest/search/kcs"
DEFAULT_ROWS = 20
USER_AGENT = "SecLensRedHatCollector/1.0"
BASE_QUERY_PARAMS = {
    "q": "*:*",
    "q.orig": "*:*",
    "defType": "edismax",
    "rows": str(DEFAULT_ROWS),
    "start": "0",
    "sort": "portal_update_date desc",
    "hl": "true",
    "hl.fl": "lab_description",
    "hl.simple.pre": "%3Cmark%3E",
    "hl.simple.post": "%3C%2Fmark%3E",
    "facet": "true",
    "facet.mincount": "1",
    "facet.field": ["portal_severity", "portal_advisory_type"],
    "fq": [
        'portal_advisory_type:("Security Advisory") AND documentKind:("Errata")',
        "-documentKind:( ApplicationAttribute )",
        "-accessState:(private OR retired) AND -hasPublishedRevision:false",
        "-doNotDisplay:true",
        "-catalog_visibility:hidden",
        "-documentKind:( ProductLifeCycle )",
        "-archived:true",
    ],
    "fl": "id,portal_severity,portal_product_names,portal_CVE,portal_publication_date,portal_synopsis,view_uri,allTitle,portal_update_date",
}

ARTICLE_SELECTOR = "main#cp-main.portal-content-area"
ARTICLE_ACCEPT = "text/html,application/xhtml+xml"


@dataclass
class FetchParams:
    """Parameters controlling Red Hat advisory API queries."""

    start: int = 0
    rows: int = DEFAULT_ROWS


class RedHatAdvisoryCollector:
    """Collector that fetches and normalizes Red Hat security advisories."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
                "Referer": "https://access.redhat.com/security/security-updates/security-advisories",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            }
        )

    def fetch(self, params: FetchParams) -> Sequence[dict]:
        payload = dict(BASE_QUERY_PARAMS)
        payload["start"] = str(params.start)
        payload["rows"] = str(params.rows)
        response = self.session.get(API_URL, params=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        docs = data.get("response", {}).get("docs", [])
        if not isinstance(docs, Iterable):
            LOGGER.warning("Unexpected Red Hat payload: %s", data)
            return []
        return list(docs)

    def _fetch_article_body(self, url: str | None) -> str | None:
        if not url:
            return None
        try:
            resp = self.session.get(url, timeout=30, headers={"Accept": ARTICLE_ACCEPT})
            resp.raise_for_status()
        except requests.RequestException as exc:
            LOGGER.debug("Failed to fetch Red Hat advisory body %s: %s", url, exc)
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        container = soup.select_one(ARTICLE_SELECTOR) or soup.select_one("main") or soup.body
        if not container:
            return None
        text_parts: list[str] = []
        seen: set[str] = set()
        for element in container.find_all(["p", "li"]):
            text = " ".join(element.stripped_strings)
            if not text:
                continue
            if text.lower() in {"skip to content", "skip to main content"}:
                continue
            if text in seen:
                continue
            seen.add(text)
            text_parts.append(text)
        if text_parts:
            return "\n\n".join(text_parts)
        fallback = container.get_text("\n", strip=True)
        return fallback or None

    def normalize(self, item: dict) -> BulletinCreate:
        external_id = str(item.get("id")) if item.get("id") else None
        origin_url = item.get("view_uri")
        fetched_at = datetime.now(timezone.utc)
        published_at, time_meta = resolve_published_at(
            "redhat_advisory",
            [(item.get("portal_publication_date"), "item.portal_publication_date")],
            fetched_at=fetched_at,
        )
        severity = item.get("portal_severity")
        summary = item.get("portal_synopsis") or item.get("allTitle")
        body_text = self._fetch_article_body(origin_url)
        if not summary and body_text:
            summary = body_text.splitlines()[0][:240]

        labels: list[str] = []
        if severity:
            labels.append(severity)
        products = item.get("portal_product_names") or []
        if isinstance(products, list):
            labels.extend(str(product) for product in products if product)

        topics = ["official_advisory", "redhat"]

        extra: dict[str, object] = {
            "cves": item.get("portal_CVE"),
            "product_names": products,
            "update_date": item.get("portal_update_date"),
        }
        if time_meta:
            extra["time_meta"] = time_meta

        bulletin = BulletinCreate(
            source=SourceInfo(
                source_slug="redhat_advisory",
                external_id=external_id,
                origin_url=origin_url,
            ),
            content=ContentInfo(
                title=item.get("allTitle") or summary or (external_id or ""),
                summary=summary,
                body_text=body_text,
                published_at=published_at,
            ),
            severity=severity,
            fetched_at=fetched_at,
            labels=labels,
            topics=topics,
            extra={k: v for k, v in extra.items() if v},
            raw=item,
        )
        return bulletin

    def collect(self, params: FetchParams | None = None) -> list[BulletinCreate]:
        params = params or FetchParams()
        docs = self.fetch(params)
        bulletins: list[BulletinCreate] = []
        for doc in docs:
            try:
                bulletins.append(self.normalize(doc))
            except Exception as exc:  # pragma: no cover - defensive
                LOGGER.exception("Failed to normalize Red Hat advisory %s", doc, exc_info=exc)
        return bulletins


def run(
    ingest_url: str | None = None,
    token: str | None = None,
    params: FetchParams | None = None,
) -> tuple[list[BulletinCreate], dict | None]:
    collector = RedHatAdvisoryCollector()
    bulletins = collector.collect(params=params)
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
        response_data = api_response.json()
    return bulletins, response_data


__all__ = ["RedHatAdvisoryCollector", "FetchParams", "run"]
