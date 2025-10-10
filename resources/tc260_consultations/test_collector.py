from datetime import datetime, timezone
from pathlib import Path

import pytest

from resources.tc260_consultations.collector import (
    FetchParams,
    TC260ConsultationCollector,
)

SAMPLES = Path(__file__).resolve().parent / "samples"
LIST_URL = "https://www.tc260.org.cn/front/bzzqyjList.html"
DETAIL_URL = "https://www.tc260.org.cn/front/bzzqyjDetail.html?id=20250827154251&norm_id=20250708125141&recode_id=59758"


class MockResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if not (200 <= self.status_code < 300):
            raise RuntimeError(f"HTTP status {self.status_code}")


class FakeSession:
    def __init__(self, mapping: dict[str, MockResponse]) -> None:
        self._mapping = mapping
        self.headers: dict[str, str] = {}

    def get(self, url: str, timeout: int = 30):  # noqa: D401
        try:
            return self._mapping[url]
        except KeyError as exc:  # pragma: no cover
            raise AssertionError(f"Unexpected URL: {url}") from exc


@pytest.fixture()
def fake_session() -> FakeSession:
    mapping = {
        f"{LIST_URL}?start=0&length=10": MockResponse((SAMPLES / "list.html").read_text(encoding="utf-8")),
        DETAIL_URL: MockResponse((SAMPLES / "detail_match.html").read_text(encoding="utf-8")),
    }
    return FakeSession(mapping)


def test_collect_tc260_consultations(fake_session: FakeSession) -> None:
    collector = TC260ConsultationCollector(session=fake_session)
    params = FetchParams(list_url=LIST_URL, limit=1)
    bulletins = collector.collect(params=params)

    assert len(bulletins) == 1
    bulletin = bulletins[0]
    assert bulletin.source.source_slug == "tc260_consultations"
    assert bulletin.content.title == "关于《网络安全技术 AAA 标准》征求意见稿征求意见的通知"
    assert bulletin.topics == ["policy-compliance"]
    assert bulletin.content.published_at is not None
    assert bulletin.content.published_at.tzinfo == timezone.utc
    assert bulletin.extra.get("deadline") == "[截至日期:2025-10-26]"
    assert "AAA 标准" in (bulletin.content.body_text or "")
