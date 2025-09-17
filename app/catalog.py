"""Static catalog configuration for sections and sources."""
from __future__ import annotations

HOME_SECTIONS: list[dict[str, object]] = [
    {
        "slug": "vulnerability_alerts",
        "title": "漏洞预警",
        "description": "官方与权威渠道发布的安全漏洞与补丁通知。",
        "sources": [
            {"slug": "aliyun_security", "title": "阿里云安全公告"},
            {"slug": "huawei_security", "title": "华为安全公告"},
        ],
    },
    {
        "slug": "vendor_updates",
        "title": "厂商发布",
        "description": "厂商对产品安全、配置或策略的更新说明。",
        "sources": [],
    },
    {
        "slug": "security_news",
        "title": "安全新闻",
        "description": "媒体与安全团队对热点事件的报道。",
        "sources": [],
    },
    {
        "slug": "community_updates",
        "title": "社区更新",
        "description": "社区、开源项目或团队的安全实践分享。",
        "sources": [],
    },
    {
        "slug": "security_events",
        "title": "安全活动",
        "description": "安全会议、活动与培训信息。",
        "sources": [],
    },
    {
        "slug": "security_funding",
        "title": "安全融资",
        "description": "安全企业投融资与战略合作动态。",
        "sources": [],
    },
]

__all__ = ["HOME_SECTIONS"]
