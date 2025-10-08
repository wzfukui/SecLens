from collectors.hackernews import HackerNewsCollector


def test_normalize_hackernews_item():
    html_body = "<p>Security update released.</p>"
    sample = {
        "title": "Critical Vulnerability Patched",
        "link": "https://thehackernews.com/2025/07/critical-vulnerability-patched.html",
        "description": "Summary of the vulnerability fix.",
        "content_encoded": html_body,
        "guid": "https://thehackernews.com/2025/07/critical-vulnerability-patched.html",
        "guid_attributes": {"isPermaLink": "true"},
        "pub_date": "Wed, 09 Jul 2025 10:00:00 GMT",
        "categories": ["Security", "Vulnerabilities"],
    }

    collector = HackerNewsCollector()
    bulletin = collector.normalize(sample)

    assert bulletin.source.source_slug == "the_hacker_news"
    assert bulletin.source.external_id == sample["guid"]
    assert bulletin.content.title == sample["title"]
    assert bulletin.content.body_text == html_body
    assert bulletin.content.published_at is not None
    assert bulletin.labels == ["category:security", "category:vulnerabilities"]
    assert bulletin.topics == ["security-news"]
