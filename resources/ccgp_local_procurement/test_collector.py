from datetime import datetime, timezone
from pathlib import Path

import pytest

from resources.ccgp_local_procurement.collector import CCGPLocalCollector, FetchParams

SAMPLES = Path(__file__).resolve().parent / "samples"
LIST_URL = "https://www.ccgp.gov.cn/cggg/dfgg/"
DETAIL_MATCH = "https://www.ccgp.gov.cn/cggg/dfgg/zbgg/202510/t20251010_10000001.htm"
DETAIL_NON_MATCH = "https://www.ccgp.gov.cn/cggg/dfgg/zbgg/202510/t20251010_10000002.htm"


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


def test_collect_filters_and_parses(fake_session: FakeSession) -> None:
    collector = CCGPLocalCollector(session=fake_session)
    bulletins = collector.collect(params=FetchParams(limit=None, list_url=LIST_URL))

    assert len(bulletins) == 1
    bulletin = bulletins[0]
    assert bulletin.source.source_slug == "ccgp_local_procurement"
    assert bulletin.content.title == "某地网络安全监测平台采购项目中标公告"
    assert bulletin.extra is not None
    assert bulletin.extra.get("region") == "北京"
    assert "policy_compliance" in bulletin.topics

    assert bulletin.content.published_at is not None
    assert bulletin.content.published_at.tzinfo == timezone.utc
    fetched_at = bulletin.fetched_at
    assert fetched_at is not None and fetched_at.tzinfo == timezone.utc
    assert bulletin.extra.get("time_meta") is not None

    # Ensure keyword filter works by confirming the non-match detail was skipped
    assert all("办公用品" not in b.content.title for b in bulletins)
