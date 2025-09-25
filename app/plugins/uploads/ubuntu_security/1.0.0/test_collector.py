"""Tests for the Ubuntu security notice collector plugin."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from resources.ubuntu_security_notice.collector import UbuntuSecurityCollector

FIXTURE_DIR = Path(__file__).resolve().parent
FEED_URL = "https://ubuntu.com/security/notices/rss.xml"
DETAIL_URL = "https://ubuntu.com/security/notices/USN-7758-4.json"


class MockResponse:
    def __init__(self, *, text: str | None = None, json_data: dict | None = None, status_code: int = 200):
        self._text = text
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if not (200 <= self.status_code < 300):
            raise RuntimeError(f"HTTP status {self.status_code}")

    @property
    def text(self) -> str:
        return self._text or ""

    def json(self) -> dict:
        if self._json is None:
            raise RuntimeError("JSON requested but not available")
        # return a deep copy-safe structure
        return json.loads(json.dumps(self._json))


class FakeSession:
    def __init__(self, responses: dict[str, MockResponse]):
        self._responses = responses
        self.headers: dict[str, str] = {}

    def get(self, url: str, timeout: int = 30) -> MockResponse:
        try:
            return self._responses[url]
        except KeyError as exc:
            raise AssertionError(f"Unexpected request URL: {url}") from exc


@pytest.fixture()
def feed_text() -> str:
    return (FIXTURE_DIR / "rss.xml").read_text(encoding="utf-8")


@pytest.fixture()
def detail_payload() -> dict:
    return json.loads((FIXTURE_DIR / "detail.json").read_text(encoding="utf-8"))


def test_collect_normalizes_entries(tmp_path, feed_text, detail_payload):
    session = FakeSession(
        {
            FEED_URL: MockResponse(text=feed_text),
            DETAIL_URL: MockResponse(json_data=detail_payload),
        }
    )
    state_path = tmp_path / "cursor.txt"
    collector = UbuntuSecurityCollector(session=session, state_path=state_path)

    bulletins = collector.collect(limit=1, force=True)

    assert len(bulletins) == 1
    bulletin = bulletins[0]
    assert bulletin.source.source_slug == "ubuntu_security"
    assert bulletin.source.external_id == "USN-7758-4"
    assert str(bulletin.source.origin_url) == "https://ubuntu.com/security/notices/USN-7758-4"
    assert bulletin.content.title.startswith("USN-7758-4")
    assert "official_bulletin" in bulletin.topics
    assert any(label.startswith("release:") for label in bulletin.labels)
    assert bulletin.extra is not None
    assert "release_packages" in bulletin.extra


def test_cursor_prevents_duplicate_fetches(tmp_path, feed_text, detail_payload):
    state_path = tmp_path / "cursor.txt"
    session_first = FakeSession(
        {
            FEED_URL: MockResponse(text=feed_text),
            DETAIL_URL: MockResponse(json_data=detail_payload),
        }
    )
    collector_first = UbuntuSecurityCollector(session=session_first, state_path=state_path)
    first_run = collector_first.collect(limit=1, force=False)
    assert first_run
    assert state_path.exists() and state_path.read_text().strip()

    session_second = FakeSession({FEED_URL: MockResponse(text=feed_text)})
    collector_second = UbuntuSecurityCollector(session=session_second, state_path=state_path)
    second_run = collector_second.collect(limit=1, force=False)
    assert second_run == []
