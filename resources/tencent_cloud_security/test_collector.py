"""Tests for the Tencent Cloud security announcement plugin."""
from __future__ import annotations

from pathlib import Path

import pytest

from resources.tencent_cloud_security.collector import (
    DEFAULT_LIST_URL,
    DETAIL_URL_TEMPLATE,
    TencentCloudCollector,
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
        except KeyError as exc:
            raise AssertionError(f"Unexpected request URL: {url}") from exc


@pytest.fixture()
def list_html() -> str:
    return (FIXTURE_DIR / "list.html").read_text(encoding="utf-8")


@pytest.fixture()
def detail_html_3001() -> str:
    return (FIXTURE_DIR / "detail_3001.html").read_text(encoding="utf-8")


@pytest.fixture()
def detail_html_3000() -> str:
    return (FIXTURE_DIR / "detail_3000.html").read_text(encoding="utf-8")


def test_collect_normalizes_latest_entry(tmp_path, list_html, detail_html_3001):
    detail_url_3001 = DETAIL_URL_TEMPLATE.format(announce_id="3001")
    session = FakeSession(
        {
            DEFAULT_LIST_URL: MockResponse(text=list_html),
            detail_url_3001: MockResponse(text=detail_html_3001),
        }
    )
    collector = TencentCloudCollector(session=session, state_path=tmp_path / "cursor.txt")

    bulletins = collector.collect(limit=1, force=True)

    assert len(bulletins) == 1
    bulletin = bulletins[0]
    assert bulletin.source.source_slug == "tencent_cloud_security"
    assert bulletin.source.external_id == "3001"
    assert str(bulletin.source.origin_url) == detail_url_3001
    assert bulletin.content.title == "【安全通告】测试公告"
    assert bulletin.content.summary.startswith("这里是公告内容")
    assert bulletin.content.language == "zh"
    assert "official_bulletin" in bulletin.topics
    assert "cloud_security" in bulletin.topics
    assert "important" in bulletin.labels
    assert "type:console" in bulletin.labels
    assert bulletin.extra is not None and bulletin.extra.get("is_important") is True
    assert "content_html" in bulletin.extra
    assert bulletin.raw is not None and bulletin.raw.get("detail_html")


def test_cursor_prevents_duplicate_processing(tmp_path, list_html, detail_html_3001, detail_html_3000):
    detail_url_3001 = DETAIL_URL_TEMPLATE.format(announce_id="3001")
    detail_url_3000 = DETAIL_URL_TEMPLATE.format(announce_id="3000")
    session_first = FakeSession(
        {
            DEFAULT_LIST_URL: MockResponse(text=list_html),
            detail_url_3001: MockResponse(text=detail_html_3001),
            detail_url_3000: MockResponse(text=detail_html_3000),
        }
    )
    state_path = tmp_path / "cursor.txt"
    collector_first = TencentCloudCollector(session=session_first, state_path=state_path)

    first_run = collector_first.collect(force=False)
    assert len(first_run) == 2
    assert state_path.exists() and state_path.read_text(encoding="utf-8").strip()

    session_second = FakeSession({DEFAULT_LIST_URL: MockResponse(text=list_html)})
    collector_second = TencentCloudCollector(session=session_second, state_path=state_path)
    second_run = collector_second.collect(force=False)
    assert second_run == []
