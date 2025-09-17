from datetime import datetime, timezone

from collectors.huawei import HuaweiCollector


def test_normalize_huawei_record():
    sample = {
        "title": "Spring WebFlux Static Resource Authorization Bypass Vulnerability",
        "sasnNo": "huawei-sa-SWSRABViSHP-75187840",
        "summary": "Example summary",
        "publishDate": "2025-09-10",
        "severity": "Critical",
        "advisoryType": "Security Advisory",
        "vul": [
            {"hwPsirtId": "HWPSIRT-2024-78363", "cveId": "CVE-2024-38821"},
        ],
        "lang": "en",
    }

    collector = HuaweiCollector()
    bulletin = collector.normalize(sample)

    assert bulletin.source.source_slug == "huawei_security"
    assert bulletin.source.external_id == "huawei-sa-SWSRABViSHP-75187840"
    assert bulletin.content.title == sample["title"]
    assert bulletin.content.published_at is not None
    assert bulletin.labels and "Critical" in bulletin.labels
    assert bulletin.topics and "official_bulletin" in bulletin.topics
    assert bulletin.extra and bulletin.extra.get("sasn_no") == sample["sasnNo"]
