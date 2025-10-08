from collectors.linuxsecurity import LinuxSecurityCollector


def test_normalize_linuxsecurity_hybrid_item():
    html_body = "<p>Linux vendor released new patches.</p>"
    sample = {
        "title": "Important Kernel Advisory",
        "link": "https://linuxsecurity.com/advisories/vendor/12345",
        "description": "Summary of the advisory",
        "content_encoded": html_body,
        "guid": "vendor-12345",
        "guid_attributes": {"isPermaLink": "false"},
        "pub_date": "Wed, 08 Jan 2025 15:30:00 GMT",
        "categories": ["Advisories", "Kernel"],
    }

    collector = LinuxSecurityCollector()
    bulletin = collector.normalize(sample)

    assert bulletin.source.source_slug == "linuxsecurity_hybrid"
    assert bulletin.source.external_id == sample["guid"]
    assert bulletin.content.title == sample["title"]
    assert bulletin.content.body_text == html_body
    assert bulletin.content.published_at is not None
    assert "category:advisories" in bulletin.labels
    assert bulletin.topics == ["security-news"]
