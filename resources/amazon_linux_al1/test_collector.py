"""Tests for the Amazon Linux 1 ALAS collector."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from resources.amazon_linux_al1.collector import (
    FEED_URL,
    AmazonLinux1Collector,
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
    def content(self) -> bytes:
        return self._text.encode("utf-8")


class FakeSession:
    def __init__(self, responses: dict[str, MockResponse]):
        self._responses = responses
        self.headers: dict[str, str] = {}

    def get(self, url: str, timeout: int = 30) -> MockResponse:
        try:
            return self._responses[url]
        except KeyError as exc:  # pragma: no cover - guard
            raise AssertionError(f"Unexpected request URL: {url}") from exc


@pytest.fixture()
def feed_xml() -> str:
    return (FIXTURE_DIR / "rss_sample.xml").read_text(encoding="utf-8")


def test_collect_normalizes_entries(feed_xml: str):
    session = FakeSession({FEED_URL: MockResponse(text=feed_xml)})
    collector = AmazonLinux1Collector(session=session)

    bulletins = collector.collect(FetchParams(limit=5))

    assert len(bulletins) == 2
    first = bulletins[0]
    assert first.source.external_id == "ALAS-2025-1981"
    assert first.content.title.startswith("ALAS-2025-1981")
    assert first.content.summary == "CVE-2025-40909"
    assert first.content.published_at == datetime(2025, 6, 9, 22, 19, tzinfo=timezone.utc)
    assert "distribution:al1" in first.labels
    assert "severity:medium" in first.labels
    assert "component:perl" in first.labels
    assert "cve:cve-2025-40909" in first.labels

    second = bulletins[1]
    assert second.source.external_id == "ALAS-2025-1983"
    assert "severity:important" in second.labels


def test_collect_honors_limit(feed_xml: str):
    session = FakeSession({FEED_URL: MockResponse(text=feed_xml)})
    collector = AmazonLinux1Collector(session=session)

    bulletins = collector.collect(FetchParams(limit=1))

    assert len(bulletins) == 1
    assert bulletins[0].source.external_id == "ALAS-2025-1981"

