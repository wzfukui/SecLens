# CNNVD Announcement Database Plugin

This plugin collects vulnerability announcement information from China National Vulnerability Database (CNNVD).

## Source Information
- **Publisher**: National Information Security Vulnerability Database (CNNVD)
- **Homepage**: https://www.cnnvd.org.cn
- **List API**: https://www.cnnvd.org.cn/web/homePage/vulWarnList
- **Detail API**: https://www.cnnvd.org.cn/web/homePage/vulWarnDetail

## Data Collected
- Announcement names and warnId identifiers
- Publication times
- Detailed HTML content of announcements
- Creator information

## Fields Mapped
- `warnId`: Unique announcement identifier
- `warnName`: Announcement title
- `publishTime`: Publication timestamp
- `createUname`: Creator username
- `enclosureContent`: HTML content of the announcement

## UI Configuration
- Group: `vulnerability_alerts` (漏洞预警)
- Title: `国家信息安全漏洞库-CNNVD通报`
- Order: 30 (within vulnerability alerts group)

## Schedule
- Polls every 3600 seconds (1 hour)

## Time Policy
- Default timezone: Asia/Shanghai
- Naive strategy: assume_default

## Deduplication
The plugin maintains a cache of processed `warnId` values in a `.cache` directory within the plugin folder to ensure idempotency and avoid reprocessing the same announcements.