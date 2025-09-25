# SecLens Plugin Specification

## Directory & Packaging
- Each plugin resides in a standalone folder (e.g. `resources/ubuntu_security_notice/`).
- Required files: `manifest.json`, Python package or module containing the collector, tests, and optional README/state files.
- Package the folder as `<slug>.zip` preserving relative paths when uploading via `/v1/plugins/upload`.

## manifest.json Fields
```json
{
  "slug": "aliyun_security",
  "name": "Aliyun Bulletin Collector",
  "version": "1.0.0",
  "entrypoint": "collector.main:run",
  "description": "Fetches Aliyun security bulletins",
  "schedule": "3600",
  "source": {
    "publisher": "Alibaba Cloud",
    "homepage": "https://t.aliyun.com/",
    "feed_url": "https://t.aliyun.com/abs/bulletin/bulletinQuery"
  },
  "runtime": {
    "ingest_url": "https://host/v1/ingest/bulletins",
    "token": "<api token>"
  }
}
```
- `slug`: unique snake_case identifier, reused in database `source_slug`.
- `entrypoint`: import path in `module:function` form; function must accept `ingest_url`, `token`, `**kwargs` and return `(list[BulletinCreate], response | None)`.
- `source`: metadata about the upstream feed; include `publisher`, `homepage`, `feed_url`, and other relevant keys.
- `schedule`: polling interval in seconds or cron string, interpreted by scheduler.
- `runtime`: free-form config merged into kwargs when the entrypoint runs.

## Collector Contract
- Use `app.schemas.BulletinCreate` to normalize fields; populate `source.source_slug`, `content.title`, `content.published_at`, and `raw`.
- Only call the ingest API (`POST /v1/ingest/bulletins`) through HTTPS and include the Bearer token from manifest.
- Log via `logging` and surface exceptions; the platform captures stdout/stderr.
- Maintain idempotency with dedupe keys (`external_id`, `origin_url`) and persist cursors inside the plugin directory (e.g. `.cursor`).

## Testing Expectations
- Provide `test_<slug>.py` next to plugin code using `pytest`.
- Mock remote responses with sample fixtures (JSON, RSS, HTML) under the same directory.
- Verify normalization (model validation) and ingest payload structure; tests must run with `pytest resources/<slug>`.

## Upload & Lifecycle
1. Zip the plugin directory: `cd resources/ubuntu_security_notice && zip -r ../ubuntu_security_notice.zip .`.
2. Base64-encode archive and call `/v1/plugins/upload` with `PluginUploadRequest`.
3. Activate via `/v1/plugins/{slug}/activate` and monitor run logs in the admin UI or scheduler output.
4. Increment `version` when changing behaviour; include changelog notes in PRs.

## Security & Compliance
- Never embed credentials; consume them from `runtime` or environment.
- Respect upstream rate limits; throttle (e.g. `time.sleep`) when paginating.
- Validate and sanitize parsed HTML; prefer official JSON/RSS feeds when available.
