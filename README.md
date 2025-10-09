# SecLens

SecLens 聚合主流厂商的安全公告与情报源，为安全团队和个人提供统一的观测、订阅与管理能力。后端基于 FastAPI + SQLAlchemy，插件体系负责扩展采集来源，前端模板则提供轻量的管理与展示页面。

## 目录结构

- `app/` — FastAPI 应用代码，包含路由、服务、模板等。
- `resources/` — 已打包的插件样例，结构与上传格式一致。
- `scripts/` — 运维和调试脚本，例如本地运行单个插件或打包插件。
- `tests/` — Pytest 测试套件，覆盖 API、插件与页面渲染。
- `docs/` — 项目文档（贡献指南、插件规范、部署步骤、产品背景等）。
- `dist/` — 打包输出目录（忽略在版本库中）。
- `frontend/` — 预留的前端工程目录，当前仍在规划中。

完整的开发说明请参考：

- `docs/SETUP.md` — 本地环境与启动步骤。
- `docs/CONTRIBUTING.md` — 代码风格、测试规范与插件工作流。
- `docs/PLUGIN_SPEC.md` — 插件 manifest、运行契约与上传流程。
- `docs/PRODUCT_CONTEXT.md` — 产品目标与场景背景。
- `ROADMAP.md` — 迭代计划与当前优先级。

## 快速开始

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

应用启动时会自动调用 `Base.metadata.create_all` 初始化数据库表，如使用新的迁移脚本请参考 `scripts/init_db.py`。插件打包、脚本执行等更多用法见 `docs/CONTRIBUTING.md`。
