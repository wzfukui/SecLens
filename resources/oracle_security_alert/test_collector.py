"""Tests for the Oracle Security Alert collector."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from resources.oracle_security_alert.collector import (
    FEED_URL,
    OracleSecurityCollector,
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

    def get(self, url: str, timeout: int = 30, headers: dict[str, str] | None = None) -> MockResponse:
        try:
            return self._responses[url]
        except KeyError as exc:  # pragma: no cover - guard against unexpected URLs
            raise AssertionError(f"Unexpected request URL: {url}") from exc


@pytest.fixture()
def feed_text() -> str:
    return (FIXTURE_DIR / "rss_sample.xml").read_text(encoding="utf-8")


@pytest.fixture()
def cpu_article_html() -> str:
    return (FIXTURE_DIR / "article_sample.html").read_text(encoding="utf-8")


@pytest.fixture()
def alert_article_html() -> str:
    return (FIXTURE_DIR / "article_alert.html").read_text(encoding="utf-8")


def test_collect_normalizes_entries(tmp_path, feed_text, cpu_article_html, alert_article_html):
    state_path = tmp_path / "cursor.txt"
    responses = {
        FEED_URL: MockResponse(text=feed_text),
        "https://www.oracle.com/security-alerts/cpuoct2025.html": MockResponse(text=cpu_article_html),
        "https://www.oracle.com/security-alerts/alert-cve-2025-61882.html": MockResponse(text=alert_article_html),
    }
    session = FakeSession(responses)
    collector = OracleSecurityCollector(session=session, state_path=state_path)

    bulletins = collector.collect(force=True)

    assert len(bulletins) == 2
    first = bulletins[-1]
    assert first.source.source_slug == "oracle_security_alert"
    assert first.source.external_id == "cpuoct2025"
    assert str(first.source.origin_url) == "https://www.oracle.com/security-alerts/cpuoct2025.html"
    assert first.content.published_at == datetime(2025, 10, 14, 18, 0, tzinfo=timezone.utc)
    assert first.content.title.startswith("Oracle Critical Patch Update Advisory")
    assert "vendor-update" in first.topics
    assert "vendor:oracle" in first.labels
    assert first.extra == {
        "guid": "cpuoct2025",
        "link": "https://www.oracle.com/security-alerts/cpuoct2025.html",
    }
    assert first.content.body_text and "Oracle Security Alert" in first.content.body_text
    assert first.content.summary == first.content.body_text
    assert "Skip to content" not in first.content.summary
    assert "Footer navigation" not in first.content.body_text
    second = bulletins[0]
    assert second.source.external_id == "alert-cve-2025-61882"
    assert second.content.body_text and "CVE-2025-61882" in second.content.body_text
    assert second.content.summary == second.content.body_text
    assert "Skip to content" not in second.content.summary
    assert "footer" not in second.content.body_text.lower()


def test_cursor_prevents_duplicate_processing(tmp_path, feed_text, cpu_article_html, alert_article_html):
    state_path = tmp_path / "cursor.txt"
    responses = {
        FEED_URL: MockResponse(text=feed_text),
        "https://www.oracle.com/security-alerts/cpuoct2025.html": MockResponse(text=cpu_article_html),
        "https://www.oracle.com/security-alerts/alert-cve-2025-61882.html": MockResponse(text=alert_article_html),
    }
    session_one = FakeSession(responses)
    collector_one = OracleSecurityCollector(session=session_one, state_path=state_path)
    first_run = collector_one.collect(force=False)
    assert len(first_run) == 2
    assert state_path.exists()

    session_two = FakeSession(responses)
    collector_two = OracleSecurityCollector(session=session_two, state_path=state_path)
    second_run = collector_two.collect(force=False)
    assert second_run == []


def test_collect_deduplicates_by_external_id(tmp_path, feed_text, cpu_article_html, alert_article_html):
    first_item = feed_text.split("<item>", 2)[1]
    duplicated_feed = feed_text.replace("</item>", "</item>\n    <item>" + first_item, 1)
    responses = {
        FEED_URL: MockResponse(text=duplicated_feed),
        "https://www.oracle.com/security-alerts/cpuoct2025.html": MockResponse(text=cpu_article_html),
        "https://www.oracle.com/security-alerts/alert-cve-2025-61882.html": MockResponse(text=alert_article_html),
    }
    session = FakeSession(responses)
    collector = OracleSecurityCollector(session=session, state_path=tmp_path / "cursor.txt")
    bulletins = collector.collect(force=True)
    external_ids = [bulletin.source.external_id for bulletin in bulletins]
    assert len(external_ids) == len(set(external_ids))
