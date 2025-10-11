"""Tests for the CNVDB collector plugin."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from resources.cnvdb.collector import CNVDBCollector, FetchParams, ORIGIN_URL_TEMPLATE

FIXTURE_DIR = Path(__file__).resolve().parent


def _load_fixture(name: str) -> dict:
    path = FIXTURE_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


class StubClient:
    def __init__(self, list_payload: dict, detail_map: dict[str, dict]) -> None:
        self._list_payload = list_payload
        self._detail_map = detail_map
        self.list_called_with: tuple[int, int] | None = None
        self.detail_calls: list[str] = []

    def list_policies(self, *, page: int, page_size: int) -> dict:
        self.list_called_with = (page, page_size)
        payload = copy.deepcopy(self._list_payload)
        records = payload.get("data", {}).get("records", [])
        if isinstance(records, list):
            payload["data"]["records"] = records[:page_size]
        return payload

    def get_policy_detail(self, policy_id: str) -> dict:
        self.detail_calls.append(policy_id)
        return self._detail_map.get(policy_id, {"code": 200, "msg": "成功", "data": None})


@pytest.fixture()
def sample_list_payload() -> dict:
    return _load_fixture("sample_list.json")


@pytest.fixture()
def sample_detail_payload() -> dict:
    return _load_fixture("sample_detail.json")


def test_collect_normalizes_records(sample_list_payload, sample_detail_payload) -> None:
    detail_data = sample_detail_payload["data"]
    stub = StubClient(sample_list_payload, {detail_data["id"]: sample_detail_payload})
    collector = CNVDBCollector(client=stub)  # type: ignore[arg-type]

    bulletins = collector.collect(FetchParams(page=1, page_size=1))

    assert stub.list_called_with == (1, 1)
    assert len(bulletins) == 1
    bulletin = bulletins[0]
    assert bulletin.source.source_slug == "cnvdb"
    assert bulletin.source.external_id == detail_data["id"]
    assert str(bulletin.source.origin_url) == ORIGIN_URL_TEMPLATE.format(policy_id=detail_data["id"])
    assert bulletin.content.title == detail_data["title"]
    assert bulletin.content.language == "zh"
    assert bulletin.content.summary is not None and bulletin.content.summary.endswith("…")
    assert bulletin.extra is not None
    assert bulletin.extra["content_html"].startswith("<p")
    assert bulletin.extra["origin"] == detail_data["origin"]
    assert bulletin.raw is not None and "detail" in bulletin.raw
    assert "official_bulletin" in bulletin.topics
    assert "vulnerability_warning" in bulletin.topics


def test_collect_handles_missing_detail(sample_list_payload) -> None:
    records = sample_list_payload["data"]["records"]
    assert len(records) >= 1
    stub = StubClient(sample_list_payload, {})
    collector = CNVDBCollector(client=stub)  # type: ignore[arg-type]

    bulletins = collector.collect(FetchParams(page=1, page_size=1))

    assert len(bulletins) == 1
    bulletin = bulletins[0]
    policy_id = records[0]["id"]
    assert bulletin.source.external_id == policy_id
    assert bulletin.extra is not None and bulletin.extra["content_html"] is None
    assert bulletin.content.summary is None
    assert bulletin.raw is not None and "detail" not in bulletin.raw
