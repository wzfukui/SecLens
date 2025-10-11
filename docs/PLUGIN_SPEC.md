# SecLens Plugin Specification

## Directory & Packaging
- Each plugin resides in a standalone folder (e.g. `resources/ubuntu_security_notice/`).
- Required files: `manifest.json`, Python package or module containing the collector, tests, and optional README/state files.
- Use `scripts/package_plugins.py` to bundle and (optionally) upload plugins:
  - Package all resources: `./.venv/bin/python scripts/package_plugins.py`
  - Package a single plugin directory: `./.venv/bin/python scripts/package_plugins.py --resources-dir resources/redhat_advisory`
  - Provide `--upload-url http://127.0.0.1:8000/v1/plugins/upload` (and `--token <token>` when needed) to push the generated archive immediately after packaging.
- The script discovers plugins by locating `manifest.json`. When a directory is passed via `--resources-dir`, it now recognises the directory itself as a plugin, so per-plugin packaging/upload works without nesting.
- Archives are emitted into `dist/plugins` by default following `<slug>-<version>.zip` naming and preserve relative paths required by `/v1/plugins/upload`.

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
  },
  "time_policy": {
    "default_timezone": "Asia/Shanghai",
    "naive_strategy": "assume_default",
    "max_future_drift_minutes": 120,
    "max_past_drift_days": 365
  },
  "ui": {
    "group_slug": "vulnerability_alerts",
    "group_title": "漏洞预警",
    "group_description": "官方与权威渠道发布的安全漏洞与补丁通知。",
    "group_order": 10,
    "source_title": "阿里云安全公告",
    "source_order": 10
  }
}
```
- `slug`: unique snake_case identifier, reused in database `source_slug`.
- `entrypoint`: import path in `module:function` form; function must accept `ingest_url`, `token`, `**kwargs` and return `(list[BulletinCreate], response | None)`.
- `source`: metadata about the upstream feed; include `publisher`, `homepage`, `feed_url`, and other relevant keys.
- `schedule`: polling interval in seconds or cron string, interpreted by scheduler.
- `runtime`: free-form config merged into kwargs when the entrypoint runs.
- `time_policy`: 统一的时间解析策略。字段说明：
  - `default_timezone`：当原始时间缺失时区信息时采用的 IANA 时区标识（如 `Asia/Shanghai`）。
  - `naive_strategy`：`assume_default` / `utc` / `reject`，分别代表“绑定默认时区”“保持 UTC”或“抛弃该时间值”。
  - `max_future_drift_minutes`：允许发布时间领先抓取时间的最大分钟数，超过则降级使用 `fetched_at` 并打标。
  - `max_past_drift_days`：允许发布时间落后的最大天数，用于过滤过旧内容（可选）。
- `ui`: optional UI metadata powering homepage/source 自动分组。常用键包括：`group_slug` / `group_title` / `group_description`（分组信息）、`group_order`（分组排序）、`source_title`（来源展示名）与 `source_order`（分组内排序）。

## Collector Contract
- Use `app.schemas.BulletinCreate` to normalize fields; populate `source.source_slug`, `content.title`, `content.published_at`, and `raw`.
- 调用 `app.time_utils.resolve_published_at`（即将提供的统一入口）完成时间解析，并把 `time_meta` 写进 `BulletinCreate.extra` 以便追踪。
- Only call the ingest API (`POST /v1/ingest/bulletins`) through HTTPS and include the Bearer token from manifest.
- Log via `logging` and surface exceptions; the platform captures stdout/stderr.
- Maintain idempotency with dedupe keys (`external_id`, `origin_url`) and persist cursors inside the plugin directory (e.g. `.cursor`).
- 插件带 `ui` 配置后，无论是通过 `/v1/plugins/upload` 注册还是本地运行 `scripts/run_plugin.py --source <slug> --ingest-url ... --force` 写入数据，首页与仪表盘都会自动生成对应的分组与来源标签。

## Testing Expectations
- Provide `test_<slug>.py` next to plugin code using `pytest`.
- Mock remote responses with sample fixtures (JSON, RSS, HTML) under the same directory.
- Verify normalization (model validation) and ingest payload structure; tests must run with `pytest resources/<slug>`.

## Upload & Lifecycle
1. **Packaging**: Use the provided script to package plugins:
   - Package all resources: `./.venv/bin/python scripts/package_plugins.py`
   - Package a single plugin: `./.venv/bin/python scripts/package_plugins.py --resources-dir resources/<plugin-name>`
   - The packaged ZIP file will be created in `dist/plugins/` with format `<slug>-<version>.zip`
2. **Uploading**: Use the upload script to upload plugins to the SecLens instance:
   - Upload plugin: `./.venv/bin/python scripts/upload_plugin.py dist/plugins/<plugin-name>-<version>.zip`
   - For testing without verification: `./.venv/bin/python scripts/upload_plugin.py dist/plugins/<plugin-name>-<version>.zip --skip-verify`
3. **Activation**: After successful upload, the plugin appears in the system but requires activation:
   - Check available plugins: `GET /v1/plugins` or view in admin UI
   - Activate via API: `POST /v1/plugins/{slug}/activate` (requires auth token)
   - Or activate through admin UI plugin management page
   - Monitor run logs in the admin UI or scheduler output
4. **Plugin Updates**: When updating existing plugins:
   - Increment the `version` field in `manifest.json` (e.g., from 1.0.0 to 1.0.1)
   - Re-package and re-upload the new version
   - Multiple versions can coexist; only one can be active at a time
   - Manually activate the new version through the admin UI after upload
5. **Verification**: Always test the plugin functionality after activation to ensure proper operation.

## Security & Compliance
- Never embed credentials; consume them from `runtime` or environment.
- Respect upstream rate limits; throttle (e.g. `time.sleep`) when paginating.
- Validate and sanitize parsed HTML; prefer official JSON/RSS feeds when available.
