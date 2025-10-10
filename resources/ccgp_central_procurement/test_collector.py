from datetime import timezone
from pathlib import Path

import pytest

from resources.ccgp_central_procurement.collector import CCGPCentralCollector, FetchParams

SAMPLES = Path(__file__).resolve().parent / "samples"
LIST_URL = "https://www.ccgp.gov.cn/cggg/zygg/"
DETAIL_MATCH = "https://www.ccgp.gov.cn/cggg/zygg/gkzb/202510/t20251010_20000001.htm"
DETAIL_NON_MATCH = "https://www.ccgp.gov.cn/cggg/zygg/gkzb/202510/t20251010_20000002.htm"


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

    def get(self, url: str, timeout: int = 30):  # noqa: D401 - mimic requests
        try:
            return self._mapping[url]
        except KeyError as exc:  # pragma: no cover - defensive
            raise AssertionError(f"Unexpected URL requested: {url}") from exc


@pytest.fixture()
def fake_session() -> FakeSession:
    mapping = {
        LIST_URL: MockResponse((SAMPLES / "list.html").read_text(encoding="utf-8")),
        DETAIL_MATCH: MockResponse((SAMPLES / "detail_match.html").read_text(encoding="utf-8")),
        DETAIL_NON_MATCH: MockResponse((SAMPLES / "detail_non_match.html").read_text(encoding="utf-8")),
    }
    return FakeSession(mapping)


def test_collect_filters(fake_session: FakeSession) -> None:
    collector = CCGPCentralCollector(session=fake_session)
    bulletins = collector.collect(params=FetchParams(limit=None, list_url=LIST_URL))

    assert len(bulletins) == 1
    bulletin = bulletins[0]
    assert bulletin.source.source_slug == "ccgp_central_procurement"
    assert any(keyword in bulletin.content.title for keyword in ("网络安全", "信息安全"))
    assert bulletin.extra.get("purchaser") == "中央某单位"
    assert bulletin.content.published_at is not None
    assert bulletin.content.published_at.tzinfo == timezone.utc
    assert bulletin.extra.get("time_meta") is not None
