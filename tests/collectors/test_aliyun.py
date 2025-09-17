from datetime import datetime, timezone

from collectors.aliyun import AliyunCollector


def test_normalize_builds_expected_schema():
    sample = {
        "id": 101,
        "title": "示例公告",
        "content": "这里是公告内容",
        "url": "https://www.aliyun.com/notice/101",
        "publishTime": int(datetime(2024, 3, 1, tzinfo=timezone.utc).timestamp() * 1000),
        "language": "zh",
        "bulletinType": "security",
        "bulletinType2": "risk_notice",
    }
    collector = AliyunCollector()
    bulletin = collector.normalize(sample)

    assert bulletin.source.source_slug == "aliyun_security"
    assert bulletin.source.external_id == "101"
    assert bulletin.content.title == sample["title"]
    assert bulletin.content.published_at is not None
    assert bulletin.labels and "security" in bulletin.labels
    assert bulletin.topics == ["official_bulletin"]
    assert bulletin.extra and bulletin.extra.get("bulletin_type") == "security"
