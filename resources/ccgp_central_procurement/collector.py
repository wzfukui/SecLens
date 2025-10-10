"""Collector for CCGP central government procurement announcements."""
from __future__ import annotations

from typing import List

import requests

from app.schemas import BulletinCreate
from resources.ccgp_local_procurement.collector import (
    CCGPProcurementCollector,
    DEFAULT_CENTRAL_LIST_URL,
    FetchParams,
)


class CCGPCentralCollector(CCGPProcurementCollector):
    slug = "ccgp_central_procurement"
    list_url = DEFAULT_CENTRAL_LIST_URL
    topics = ["security_procurement"]


def run(
    ingest_url: str | None = None,
    token: str | None = None,
    params: FetchParams | None = None,
) -> tuple[list[BulletinCreate], dict | None]:
    collector = CCGPCentralCollector()
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


__all__ = ["CCGPCentralCollector", "FetchParams", "run"]
