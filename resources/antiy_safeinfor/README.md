# Antiy SafeInfo Collector Plugin

This plugin collects security announcements from Antiy (安天) daily security briefings.

## Source Information
- **Publisher**: Antiy (安天)
- **Homepage**: https://www.antiycloud.com/#/antiy/safeinfor
- **API Endpoint**: https://www.antiycloud.com/api/daily/list
- **Detail Endpoint**: https://www.antiycloud.com/#/dailydetail/{daily_time}?keyword=

## Data Collected
- Daily security briefings with multiple security news items
- Publication dates and times
- Security content summaries
- Unique identifiers for deduplication

## Fields Mapped
- `id`: Internal item identifier
- `title`: Daily briefing title (prefixed with "安天威胁情报中心-")
- `content`: HTML content of the security briefing
- `daily_time`: Date string in format YYYYMMDD
- `time`: Publication timestamp
- `status`: Publication status

## UI Configuration
- Group: `security_announcement` (安全公告)
- Title: `安天每日安全简讯`
- Order: 10 (within security announcements group)

## Schedule
- Polls every 28800 seconds (8 hours)

## Time Policy
- Default timezone: Asia/Shanghai
- Naive strategy: assume_default
- Maximum past drift: 7 days (filters very old content)

## Deduplication
The plugin maintains a cache of processed item IDs in a `.cache` directory within the plugin folder to ensure idempotency and avoid reprocessing the same briefings.