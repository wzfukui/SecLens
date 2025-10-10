from datetime import datetime, timezone

from resources.doonsec_wechat.collector import DoonsecCollector


def test_normalize_doonsec_item():
    sample = {
        "title": "测试标题",
        "link": "https://wechat.doonsec.com/test",
        "description": "摘要内容",
        "author": "安全团队",
        "category": "Doonsec",
        "pub_date": "2025-10-08T20:30:00",
    }

    collector = DoonsecCollector()
    bulletin = collector.normalize(sample)

    assert bulletin.source.source_slug == "doonsec_wechat"
    assert bulletin.source.external_id == sample["link"]
    assert bulletin.content.title == sample["title"]
    assert bulletin.content.published_at == datetime(2025, 10, 8, 12, 30, tzinfo=timezone.utc)
    assert "security-news" in bulletin.topics
    assert "category:doonsec" in bulletin.labels
    assert "author:安全团队".lower() in [label.lower() for label in bulletin.labels]
    assert bulletin.extra is not None
    time_meta = bulletin.extra.get("time_meta")
    assert time_meta is not None
    assert time_meta.get("applied_timezone") == "Asia/Shanghai"
    assert not time_meta.get("fallback", False)
