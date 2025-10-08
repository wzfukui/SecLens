from resources.sihou_news.collector import SihouCollector


def test_normalize_sihou_item():
    html_body = "<p>嘶吼发布安全新闻。</p>"
    sample = {
        "title": "重大安全事件分析",
        "link": "https://www.4hou.com/posts/12345",
        "description": "新闻摘要",
        "content_encoded": html_body,
        "guid": "https://www.4hou.com/posts/12345",
        "guid_attributes": {"isPermaLink": "true"},
        "pub_date": "Tue, 08 Jul 2025 12:00:00 GMT",
        "categories": ["安全新闻", "漏洞通告"],
    }

    collector = SihouCollector()
    bulletin = collector.normalize(sample)

    assert bulletin.source.source_slug == "sihou_news"
    assert bulletin.source.external_id == sample["guid"]
    assert bulletin.content.title == sample["title"]
    assert bulletin.content.body_text == html_body
    assert bulletin.content.published_at is not None
    assert "security-news" in bulletin.topics
    assert bulletin.labels == ["category:安全新闻", "category:漏洞通告"]
