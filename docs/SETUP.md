# SecLens 开发环境准备指南

本指南帮助你在 macOS 上为 SecLens MVP 建立基础开发环境，包括 Python 虚拟环境与 PostgreSQL 数据库。所有命令默认在项目根目录 (`/Users/donaldford/app/SecLens`) 执行。

## 1. 基础依赖检查

1. **Homebrew**（用于安装 PostgreSQL 等工具）
   ```bash
   brew --version
   ```
   如果未安装，请参考 https://brew.sh 按提示安装。

2. **Python 3.x**（macOS 随附版本即可）。确认命令：
   ```bash
   python3 --version
   ```

3. **Git & Make（可选，但推荐）**
   ```bash
   git --version
   make --version
   ```

## 2. 安装 PostgreSQL（通过 Homebrew）

1. 安装数据库：
   ```bash
   brew install postgresql@15
   ```
   > 可以将 `@15` 替换为你需要的版本；后续命令以 15 为例。

2. 配置 PATH（添加到 `~/.zshrc` 或 `~/.bashrc`）：
   ```bash
   echo 'export PATH="/usr/local/opt/postgresql@15/bin:$PATH"' >> ~/.zshrc
   source ~/.zshrc
   ```
   > Apple Silicon 机器若使用 `/opt/homebrew` 前缀，请替换路径。

3. 初始化并启动服务：
   ```bash
   brew services start postgresql@15
   ```
   如需停止：
   ```bash
   brew services stop postgresql@15
   ```

4. 验证 `psql` 可用：
   ```bash
   psql --version
   ```

## 3. 创建开发数据库与账户

1. 创建数据库用户（示例名：`seclens`）：
   ```bash
   createuser --interactive --pwprompt seclens
   ```
   按提示设置密码。

2. 创建开发数据库（示例名：`seclens_dev`）：
   ```bash
   createdb -O seclens seclens_dev
   ```

3. 使用 `psql` 验证连接：
   ```bash
   psql -U seclens -d seclens_dev -h localhost
   ```
   如果能进入交互式 shell，说明数据库准备就绪；输入 `\q` 退出。

## 4. 建立 Python 虚拟环境 (venv)

1. 在项目根目录创建虚拟环境：
   ```bash
   python3 -m venv .venv
   ```

2. 激活虚拟环境：
   ```bash
   source .venv/bin/activate
   ```
   > 关闭终端或运行 `deactivate` 即可退出虚拟环境。

3. 升级 pip 并安装基础工具：
   ```bash
   pip install --upgrade pip wheel
   ```

4. 预装常用依赖（未来可在 `requirements.txt` 中维护）：
   ```bash
   pip install fastapi "uvicorn[standard]" "psycopg[binary]" python-dotenv
   ```
   `psycopg[binary]` 提供 PostgreSQL 驱动；如日后需要更细粒度控制，可改用 `psycopg` + `pg_config`。

## 5. 环境变量与配置文件

1. 在项目根目录创建 `.env` 文件（暂存最小配置）：
   ```bash
   cat <<'ENV' > .env.example
   DATABASE_URL=postgresql+psycopg://seclens:YOUR_PASSWORD@localhost:5432/seclens_dev
   ENV
   ```
2. 将 `.env.example` 复制为 `.env` 并填入真实密码：
   ```bash
   cp .env.example .env
   ```

## 6. 快速验证

1. 激活虚拟环境后，在 Python REPL 中验证数据库驱动：
   ```python
   >>> import psycopg
   >>> psycopg.__version__
   ```

2. 后续创建 FastAPI 项目时，可运行：
   ```bash
   uvicorn app.main:app --reload
   ```
   确保服务成功启动（此处仅作占位，等项目代码完善后执行）。

## 7. 常见问题

- **`psql: command not found`**：确认已将 Homebrew 的 PostgreSQL `bin` 路径加入 PATH。
- **无法连接数据库 (`connection refused`)**：检查 `brew services list` 中 PostgreSQL 状态，必要时重启：
  ```bash
  brew services restart postgresql@15
  ```
- **SSL 相关错误**：本地开发可在数据库 URL 加上 `?sslmode=disable`。

准备完成后，你就可以开始实现 Ingest API、编写采集插件并进行调试了。如果过程中遇到特定问题，可以把报错贴出来我再协助排查。

## 手动触发全部采集插件

本地开发环境可使用内置调度函数一次性运行所有已激活插件，并立即写入采集结果：

```bash
source .venv/bin/activate
python - <<'PY'
from scripts.scheduler_service import run_plugins_once
run_plugins_once()
PY
```

调度完成后，可通过以下方式确认插件执行情况：

- 查询 `/dashboard/plugins` 看板的“采集总量”“上次运行”“下一次运行”字段。
- 查看数据库 `plugin_runs` 表记录（或运行 `python scripts/debug_print_plugin_runs.py` 自行编写脚本）获取成功/失败状态与错误信息。
- 调用 `GET /v1/bulletins?source_slug=<slug>` 验证是否有新公告写入。
