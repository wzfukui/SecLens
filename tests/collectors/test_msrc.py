from resources.msrc_update_guide.collector import MsrcCollector


def test_normalize_msrc_item_with_revision():
    description = (
        "The following updates have been made to CVE-2025-59489: 1) In the Security Updates table, "
        "added Microsoft Mesh and Microsoft Mesh for Meta Quest as they affected by this vulnerability."
    )
    sample = {
        "title": "CVE-2025-59489 MITRE: CVE-2025-59489 Unity Gaming Engine Editor vulnerability",
        "link": "https://msrc.microsoft.com/update-guide/vulnerability/CVE-2025-59489",
        "description": description,
        "guid": "CVE-2025-59489",
        "guid_attributes": {"isPermaLink": "false"},
        "pub_date": "Tue, 07 Oct 2025 07:00:00 Z",
        "categories": ["CVE"],
        "revision": "2.0000000000",
    }

    collector = MsrcCollector()
    bulletin = collector.normalize(sample)

    assert bulletin.source.source_slug == "msrc_update_guide"
    assert bulletin.source.external_id.endswith("#rev-2.0000000000")
    assert bulletin.content.title == sample["title"]
    assert bulletin.content.published_at is not None
    assert "CVE" in bulletin.labels
    assert "cve" in bulletin.topics
    assert bulletin.extra and bulletin.extra["revision"] == sample["revision"]
