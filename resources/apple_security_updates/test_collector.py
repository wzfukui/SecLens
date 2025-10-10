"""Tests for the Apple security updates collector."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from resources.apple_security_updates.collector import (
    LIST_URL,
    AppleSecurityUpdatesCollector,
    FetchParams,
)

FIXTURE_DIR = Path(__file__).resolve().parent


class MockResponse:
    def __init__(self, *, text: str, status_code: int = 200):
        self._text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if not (200 <= self.status_code < 300):
            raise RuntimeError(f"HTTP status {self.status_code}")

    @property
    def text(self) -> str:
        return self._text


class FakeSession:
    def __init__(self, responses: dict[str, MockResponse]):
        self._responses = responses
        self.headers: dict[str, str] = {}

    def get(self, url: str, timeout: int = 30) -> MockResponse:
        try:
            return self._responses[url]
        except KeyError as exc:  # pragma: no cover - guard rail
            raise AssertionError(f"Unexpected request URL: {url}") from exc


@pytest.fixture()
def table_html() -> str:
    return (FIXTURE_DIR / "table_sample.html").read_text(encoding="utf-8")


def test_collect_normalizes_entries(table_html: str):
    session = FakeSession({LIST_URL: MockResponse(text=table_html)})
    collector = AppleSecurityUpdatesCollector(session=session)

    bulletins = collector.collect(FetchParams(limit=10))

    assert len(bulletins) == 3
    first = bulletins[0]
    assert first.source.source_slug == "apple_security_updates"
    assert first.source.external_id == "125001"
    assert str(first.source.origin_url) == "https://support.apple.com/en-us/125001"
    assert first.content.title == "iOS 18.6.2 and iPadOS 18.6.2"
    assert first.content.published_at == datetime(2025, 8, 20, tzinfo=timezone.utc)
    assert first.content.summary is not None and "iPhone XS" in first.content.summary
    assert first.content.body_text is not None and "Available for" in first.content.body_text
    assert "vendor:apple" in first.labels
    assert "product:ios-18-6-2-and-ipados-18-6-2" in first.labels
    assert first.topics == ["vendor-update", "official_advisory"]
    extra = first.extra or {}
    assert extra.get("available_for", "").startswith("iPhone XS")
    assert extra.get("detail_url") == "https://support.apple.com/en-us/125001"
    time_meta = extra.get("time_meta")
    assert time_meta is not None
    assert time_meta.get("applied_timezone") == "UTC"

    second = bulletins[1]
    assert second.source.external_id == "watchos-11-6-1"
    assert str(second.source.origin_url).endswith("#watchos-11-6-1")
    assert "note:no-cve" in second.labels
    assert "This update has no published CVE entries." in (second.content.body_text or "")


def test_collect_honors_limit(table_html: str):
    session = FakeSession({LIST_URL: MockResponse(text=table_html)})
    collector = AppleSecurityUpdatesCollector(session=session)

    bulletins = collector.collect(FetchParams(limit=2))

    assert len(bulletins) == 2
    assert [b.source.external_id for b in bulletins] == ["125001", "watchos-11-6-1"]
