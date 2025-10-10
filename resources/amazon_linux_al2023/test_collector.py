"""Tests for the Amazon Linux 2023 ALAS collector."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from resources.amazon_linux_al2023.collector import (
    FEED_URL,
    AmazonLinux2023Collector,
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
    collector = AmazonLinux2023Collector(session=session)

    bulletins = collector.collect(FetchParams(limit=5))

    assert len(bulletins) == 2
    first = bulletins[0]
    assert first.source.source_slug == "amazon_linux_al2023"
    assert first.source.external_id == "ALAS2023-2025-1191"
    assert str(first.source.origin_url) == "https://alas.aws.amazon.com/AL2023/ALAS2023-2025-1191.html"
    assert first.content.title == "ALAS2023-2025-1191 (medium): binutils"
    assert first.content.summary == "CVE-2025-7546"
    assert first.content.published_at == datetime(2025, 9, 29, 19, 20, tzinfo=timezone.utc)
    assert "vendor:aws" in first.labels
    assert "distribution:al2023" in first.labels
    assert "severity:medium" in first.labels
    assert "component:binutils" in first.labels
    assert "cve:cve-2025-7546" in first.labels
    assert first.extra is not None and first.extra.get("bulletin_id") == "ALAS2023-2025-1191"

    second = bulletins[1]
    assert second.source.external_id == "ALAS2023-2025-1196"
    assert "severity:important" in second.labels


def test_collect_honors_limit(feed_xml: str):
    session = FakeSession({FEED_URL: MockResponse(text=feed_xml)})
    collector = AmazonLinux2023Collector(session=session)

    bulletins = collector.collect(FetchParams(limit=1))

    assert len(bulletins) == 1
    assert bulletins[0].source.external_id == "ALAS2023-2025-1191"

