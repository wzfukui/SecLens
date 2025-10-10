"""Tests for the Chrome Stable Updates collector."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from resources.chrome_stable_updates.collector import (
    LIST_URL,
    ChromeStableUpdatesCollector,
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
        except KeyError as exc:  # pragma: no cover - guard against unexpected URLs
            raise AssertionError(f"Unexpected request URL: {url}") from exc


@pytest.fixture()
def listing_html() -> str:
    return (FIXTURE_DIR / "listing_sample.html").read_text(encoding="utf-8")


def test_collect_parses_listing(listing_html: str):
    session = FakeSession({LIST_URL: MockResponse(text=listing_html)})
    collector = ChromeStableUpdatesCollector(session=session)

    bulletins = collector.collect(params=FetchParams(limit=5))

    assert len(bulletins) == 2

    first = bulletins[0]
    assert first.source.source_slug == "chrome_stable_updates"
    assert first.source.external_id == "5717564716853837531"
    assert str(first.source.origin_url) == "https://chromereleases.googleblog.com/2025/10/stable-channel-update-for-chromeos.html"
    assert first.content.title == "Stable Channel Update for ChromeOS / ChromeOS Flex"
    assert first.content.language == "en"
    assert first.content.published_at == datetime(2025, 10, 9, 0, 0, tzinfo=timezone.utc)
    assert first.content.summary.startswith("The ChromeOS Stable channel is being updated")
    assert first.content.body_text and "File a bug" in first.content.body_text
    assert "vendor:google" in first.labels
    assert "channel:stable" in first.labels
    assert "blog-label:chromeos" in first.labels
    assert "blog-label:stable-updates" in first.labels
    assert first.topics == ["vendor-update"]
    assert first.extra is not None
    assert first.extra.get("blog_labels") == ["ChromeOS", "ChromeOS Flex", "Stable updates"]
    time_meta = first.extra.get("time_meta")
    assert time_meta is not None
    assert time_meta.get("applied_timezone") == "UTC"

    second = bulletins[1]
    assert second.source.external_id == "7094715678479795160"
    assert second.content.summary and "141.0.7390.76" in second.content.summary
    assert "blog-label:desktop" in second.labels


def test_collect_respects_limit(listing_html: str):
    session = FakeSession({LIST_URL: MockResponse(text=listing_html)})
    collector = ChromeStableUpdatesCollector(session=session)

    bulletins = collector.collect(params=FetchParams(limit=1))

    assert len(bulletins) == 1
    assert bulletins[0].source.external_id == "5717564716853837531"

