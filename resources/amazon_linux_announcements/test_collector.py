"""Tests for the Amazon Linux announcements collector."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from resources.amazon_linux_announcements.collector import (
    LIST_URL,
    AmazonLinuxAnnouncementsCollector,
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
        except KeyError as exc:  # pragma: no cover - guard
            raise AssertionError(f"Unexpected request URL: {url}") from exc


@pytest.fixture()
def announcements_html() -> str:
    return (FIXTURE_DIR / "announcements_sample.html").read_text(encoding="utf-8")


def test_collect_normalizes_rows(announcements_html: str):
    session = FakeSession({LIST_URL: MockResponse(text=announcements_html)})
    collector = AmazonLinuxAnnouncementsCollector(session=session)

    bulletins = collector.collect(FetchParams(limit=5))

    assert len(bulletins) == 2
    first = bulletins[0]
    assert first.source.source_slug == "amazon_linux_announcements"
    assert first.source.external_id == "2025-013"
    assert str(first.source.origin_url) == "https://alas.aws.amazon.com/announcements/2025-013.html"
    assert first.content.title == "End of Support for java-1.7.0-openjdk package in Amazon Linux 2 Core"
    assert first.content.summary.startswith("2025-013")
    assert first.content.published_at == datetime(2025, 10, 3, 21, 29, tzinfo=timezone.utc)
    assert "vendor:aws" in first.labels
    assert "announcement" in first.labels
    assert "announcement:2025-013" in first.labels
    extra = first.extra or {}
    assert extra.get("announcement_id") == "2025-013"
    time_meta = extra.get("time_meta")
    assert time_meta is not None
    assert time_meta.get("applied_timezone") == "UTC"

    second = bulletins[1]
    assert second.source.external_id == "2025-012"
    assert "Amazon Linux 2023 kernel update" in (second.content.title or "")


def test_collect_honors_limit(announcements_html: str):
    session = FakeSession({LIST_URL: MockResponse(text=announcements_html)})
    collector = AmazonLinuxAnnouncementsCollector(session=session)

    bulletins = collector.collect(FetchParams(limit=1))

    assert len(bulletins) == 1
    assert bulletins[0].source.external_id == "2025-013"

