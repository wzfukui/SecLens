# Lenovo Security Advisory Plugin

This plugin collects security advisories from Lenovo's official security bulletin system.

## Source Information
- **Publisher**: Lenovo
- **Homepage**: https://newsupport.lenovo.com.cn/SecurityPolicy.html
- **API Endpoint**: https://newsupport.lenovo.com.cn/api/SafeNotice/SafeNoticeListInfo
- **Detail Endpoint**: https://iknow.lenovo.com.cn/knowledgeapi/api/knowledge/knowledgeDetails

## Data Collected
- Security advisory titles, numbers, and descriptions
- Associated CVE IDs
- Publication dates
- Detailed HTML content for each advisory
- Product categories and classifications

## Fields Mapped
- `notice_number`: Advisory number (e.g., LEN-123456)
- `notice_name`: Advisory title
- `notice_cves`: Comma-separated CVE identifiers
- `publish_at`: Publication timestamp
- `notice_link`: Link to detailed advisory page
- Detailed content fetched from the knowledge API

## UI Configuration
- Group: `vendor_updates` (厂商公告)
- Title: `联想产品安全公告`
- Order: 10 (within vendor updates group)

## Schedule
- Polls every 3600 seconds (1 hour)

## Time Policy
- Default timezone: Asia/Shanghai
- Naive strategy: assume_default