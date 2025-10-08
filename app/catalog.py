"""Static catalog configuration for homepage sections."""

HOME_SECTIONS: list[dict[str, object]] = [
    {
        "slug": "vendor_updates",
        "title": "厂商发布",
        "description": "厂商对产品安全、配置或策略的更新说明。",
        "topics": [
            {"topic": "vendor-update", "title": "厂商更新动态"},
        ],
    },
    {
        "slug": "security_news",
        "title": "安全新闻",
        "description": "媒体与安全团队对热点事件的报道。",
        "topics": [
            {"topic": "security-news", "title": "新闻聚焦"},
        ],
    },
    {
        "slug": "community_updates",
        "title": "社区更新",
        "description": "社区、开源项目或团队的安全实践分享。",
        "topics": [
            {"topic": "community-update", "title": "社区动态"},
        ],
    },
    {
        "slug": "security_events",
        "title": "安全活动",
        "description": "安全会议、活动与培训信息。",
        "topics": [
            {"topic": "security-event", "title": "会议与培训"},
        ],
    },
    {
        "slug": "security_funding",
        "title": "安全融资",
        "description": "安全企业投融资与战略合作动态。",
        "labels": [
            {"label": "funding", "title": "融资快讯"},
            {"label": "merger", "title": "并购整合"},
        ],
    },
    {
        "slug": "threat_intelligence",
        "title": "威胁情报",
        "description": "全球威胁情报、攻击态势与应急提示。",
        "topics": [
            {"topic": "threat-intel", "title": "情报快报"},
            {"topic": "incident", "title": "事件通报"},
        ],
    },
    {
        "slug": "security_research",
        "title": "安全研究",
        "description": "研究报告、漏洞分析与技术白皮书。",
        "topics": [
            {"topic": "research", "title": "研究洞察"},
        ],
    },
    {
        "slug": "tool_updates",
        "title": "工具与产品",
        "description": "安全工具、平台与产品的更新动态。",
        "labels": [
            {"label": "tooling", "title": "工具更新"},
            {"label": "product", "title": "产品发布"},
        ],
    },
    {
        "slug": "policy_regulation",
        "title": "政策合规",
        "description": "安全相关的政策法规、标准合规信息。",
        "labels": [
            {"label": "policy", "title": "政策要点"},
            {"label": "compliance", "title": "合规指南"},
        ],
    },
]

__all__ = ["HOME_SECTIONS"]
