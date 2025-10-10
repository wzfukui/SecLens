"""Tests for the AWS Security Bulletins collector."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from resources.aws_security_bulletins.collector import (
    FEED_URL,
    AwsSecurityBulletinsCollector,
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
    collector = AwsSecurityBulletinsCollector(session=session)

    bulletins = collector.collect(FetchParams(limit=5))

    assert len(bulletins) == 2
    first = bulletins[0]
    assert first.source.source_slug == "aws_security_bulletins"
    assert first.source.external_id == "aws-2025-022"
    assert str(first.source.origin_url) == "https://aws.amazon.com/security/security-bulletins/rss/aws-2025-022/"
    assert first.content.title.startswith("CVE-2025-11573")
    assert first.content.published_at == datetime(2025, 10, 9, 18, 11, 44, tzinfo=timezone.utc)
    assert first.content.summary and "Amazon.IonDotnet" in first.content.summary
    assert first.content.body_text and "Affected versions" in first.content.body_text
    assert "vendor:aws" in first.labels
    assert "severity:important-requires-attention" in first.labels
    assert "bulletin:aws-2025-022" in first.labels
    assert first.topics == ["official_advisory", "vulnerability_alert"]
    extra = first.extra or {}
    assert extra.get("bulletin_id") == "AWS-2025-022"
    assert extra.get("author") == "aws@amazon.com"
    time_meta = extra.get("time_meta")
    assert time_meta is not None
    assert time_meta.get("applied_timezone") == "UTC"

    second = bulletins[1]
    assert second.source.external_id == "aws-2025-021"
    assert second.content.summary and "Instance Metadata Service" in second.content.summary


def test_collect_honors_limit(feed_xml: str):
    session = FakeSession({FEED_URL: MockResponse(text=feed_xml)})
    collector = AwsSecurityBulletinsCollector(session=session)

    bulletins = collector.collect(FetchParams(limit=1))

    assert len(bulletins) == 1
    assert bulletins[0].source.external_id == "aws-2025-022"

