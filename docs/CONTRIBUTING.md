# Contributing Guide

## Project Structure & Module Organization
- `app/` holds the FastAPI application (routers, schemas, services) and starts at `app/main.py`.
- `resources/<slug>/` stores packaged plugins (manifest + collector + assets) that mirror the upload format.
- `tests/` mirrors the application and plugin layout with matching module names.
- `scripts/` hosts one-off utilities such as local ingestion runners or data migration helpers.
- Configuration examples live in `.env.example`; keep environment-specific overrides in `.env` (never commit).
- Refer to `ROADMAP.md` for the active重构计划、里程碑与当前优先级；提交前请同步检查路线图是否需要更新。

## Build, Test, and Development Commands
- `python -m venv .venv && source .venv/bin/activate` sets up and activates the virtual environment.
- `pip install -r requirements.txt` installs API, collector, and tooling dependencies.
- `uvicorn app.main:app --reload` runs the API locally with hot reload.
- `python scripts/run_plugin.py --source aliyun_security` executes a single插件 against the ingest API.
- `pytest` runs the entire test suite; add `-k name` to target a subset.
- 前端资产将在重构阶段迁移至 `frontend/`（待建）目录并通过构建工具打包；请在运行 API 之前执行 `npm run build`（命令细节见 `ROADMAP.md` 更新）。

## Coding Style & Naming Conventions
- Follow PEP 8 with 4-space indentation and `snake_case` for modules, functions, and variables.
- Use `PascalCase` for Pydantic models and SQLAlchemy ORM classes.
- Keep FastAPI routers grouped by domain (e.g., `alerts.py`, `sources.py`).
- Run `ruff check .` before committing to enforce lint rules and auto-fix trivial issues.
- 前端代码遵循 ESLint + Prettier（将于重构阶段引入），TypeScript 组件使用 PascalCase 命名，样式变量统一在设计系统中维护。

## Testing Guidelines
- Use `pytest` with fixtures under `tests/fixtures` for shared setup (database, HTTP mocks).
- Name test files `test_<module>.py` and ensure each new feature has unit coverage plus an ingestion happy-path test.
- Integrate `pytest --cov=app --cov=resources` in CI; target ≥80% coverage for核心模块。
- 对前端交互新增 Playwright/组件级测试时，需要在 `tests/ui/` 下维护并在 CI 中执行。

## Commit & Pull Request Guidelines
- Write commits in the imperative mood (e.g., `Add Aliyun bulletin collector`).
- Organize changes so each commit addresses a single concern; rebase to keep history linear.
- PRs must describe the change, testing performed (`pytest`, manual collector run), and any configuration updates.
- Link to tracking issues and include screenshots or sample payloads when modifying API responses or UI.
- 每个里程碑完成后，在 PR 描述中引用 `ROADMAP.md` 对应章节并勾选已完成项。

## Security & Configuration Tips
- Never hard-code credentials; rely on environment variables and `.env` templates.
- Review third-party source terms before adding a collector and honor rate limits (`time.sleep` if necessary).
- Store long-lived API tokens in the secrets manager of your deployment environment, not in code or `.env` files.
- 新的插件运行框架将通过集中配置管理密钥；在迁移完成前避免在插件内直接请求外部存储。

## Plugin Development Workflow
1. **Planning**
   - 评估数据源（API、RSS、网页）：确认认证、频率限制、分页/增量策略，并收集样本记录（尤其用于生成稳定 `external_id`）。
   - 确定插件 slug（小写+下划线），在 manifest、`SourceInfo.source_slug`、`scripts/run_plugin.py` 中保持一致。

2. **Skeleton**
   - 新建 `resources/<slug>/`，至少包含：
     - `collector.py`：采集实现。
     - `manifest.json`：元数据、调度、UI 配置（`group_slug`、`source_title` 等）。
     - `__init__.py`：可留空。
   - 若需要本地状态/游标，约定路径并在 manifest `runtime` 或代码注释说明。

3. **Collector Implementation**
   - 使用 dataclass `FetchParams` 定义可配置参数。
   - `fetch(...)` 负责网络请求，封装 headers、超时、分页，必要时加入重试与错误处理。
   - `_serialize_item(...)`（可选）先裁剪原始字段。
   - `normalize(...)` 输出 `BulletinCreate`：
     - 保证标题、摘要、正文、发布时间存在合理 fallback。
     - `labels`/`topics` 去重并与 `app/catalog.py` 中的分组保持一致。
     - 将源特有信息放入 `extra`，保留原始数据于 `raw`。
   - `collect(...)` + `run(...)`：聚合 fetch + normalize，并支持可选 ingest。

4. **Manifest & CLI**
   - `manifest.json` 设置 `entrypoint: "collector:run"`、`schedule`（秒）、`source` 元信息以及 `ui` 配置，以驱动首页分组与来源。
   - 在 `scripts/run_plugin.py` 的 `--source` choices 中注册新 slug。
   - 更新 `info_source.yaml` 与相关帮助文档，说明数据来源和用途。

5. **Testing**
   - 在 `tests/collectors/test_<slug>.py` 编写规范化测试，验证 slug、`external_id`、topics/labels、发布时间等关键字段。
   - 对游标或增量逻辑补充单元测试覆盖边界场景。
   - 运行 `pytest tests/collectors/test_<slug>.py`（或 `pytest tests/collectors`）保证绿灯。

6. **打包上传 & 激活**
   - 通过 `python scripts/package_plugins.py --output-dir dist/plugins` 一次性生成 `slug-version.zip`；加 `--upload-url` 可直接上传到 `/v1/plugins/upload`。
   - 手动上传示例：
     ```bash
     curl -X POST http://127.0.0.1:8000/v1/plugins/upload \
       -H "Content-Type: application/json" \
       -d '{"filename": "xxx.zip", "content": "$(base64 xxx.zip)"}'
     ```
   - 激活特定插件：
     ```bash
     curl -X POST http://127.0.0.1:8000/v1/plugins/<id>/activate -d '{"activate": true}'
     ```
   - 手动执行一次采集：
     ```bash
     curl -X POST http://127.0.0.1:8000/v1/plugins/<id>/run
     ```
   - 启动本地调度：`python scripts/run_scheduler.py --ingest-url http://127.0.0.1:8000/v1/ingest/bulletins`
   - 在提交说明里记录数据映射、验证步骤、速率限制等注意事项。若插件需要额外依赖或环境变量，请在 manifest `runtime` 与文档中注明，便于后续维护。
