# Product Context

原始需求记录：网络安全官方公告信息聚合 - SecLens


本产品原始需求：来采集主流操作系统、数据库、中间件、流行产品的官方网站的security告警信息，用来解决普通用户需要去多个网站自助查询获取信息的问题。
但同时，也做了扩展，支持除了安全漏洞预警信息意外的，所有网络安全相关的资讯

核心分为以下几块：
- 采集器&采集引擎：每个来源是一个独立的Python采集程序，程序自己维护自己的采集任务，负责更新最新的消息到数据库
- 前端展示，按照不同类别不同厂商展示不同的信息，如：操作系统、数据库、消息队列……操作系统下分（Windows、Linux……）
- 消息订阅/推送，提供rss订阅、API订阅机制，也提供邮件发送、webhook推送等，基于用户选择的订阅方式
- 用户管理，登记自己的邮箱、webhook等信息，选择自己的过滤条件即可订阅
- 管理系统：上传插件（采集脚本）、用户设置（基本管理、参数设置……）



后台使用pgsql数据库，每个插件在数据库中有自己的记录，插件运行中的一些就关键记录信息可以使用数据库存储。
主服务会根据插件上传时填写的运行频次（cron表达式），执行插件，获取信息

插件采集到的信息通过API写入数据库，插件更新一些状态/记录信息也通过API完成，而不是直接写数据库。

我考虑到的一些还不成体系的问题，供你参考i：
- 插件要负责自己信息获取记录，只更新最新的消息到数据库
- 首页展现应该分门别类，同时提供一个搜索功能
- 事实上，我们不仅提供漏洞告警信息的收集和订阅，只提供安全会议、产商新闻、公众号资讯（区分媒体、个人、社区、团队）、安全机构、安全组织……
- 采集过来的没条信息，可能会被打上多个标签
- 未来支持用户对信息做点赞操作，增加热门效果
- 建议首页支持按照时间顺序的方式展示，（feed模式+列表模式），同时也提供主体导航，支持用户按照类别浏览和展示

这个系统最难的地方，我认为是数据分类，就像图书馆，我们要为元数据设计不同维度的类别标识。数据分类上，我们一开始需要考虑好。


-------------------------------------------

ChatGPT Answer:

# SecLens｜网络安全官方公告信息聚合

> 目标：以“官方与权威为主、广义安全资讯为辅”的原则，聚合并结构化主流 OS/数据库/中间件/热门产品的安全公告与相关资讯，提供检索、筛选、订阅与推送能力，降低信息分散带来的获取成本。

---

## 1. 产品边界与定位

* **核心**：官方/权威来源的安全公告（advisory、security update、bulletin、PSIRT 等）。
* **扩展**：安全会议、厂商新闻、团队/媒体/个人公众号文章、社区贴文、机构通报（CERT/应急响应/CISA KEV 等）。
* **服务对象**：运维/安全工程师、开发团队、合规/应急响应团队、泛安全关注者。
* **关键体验**：多源统一 → 结构化抽取 → 分类/筛选 → 搜索 → 订阅/推送（RSS/API/邮件/Webhook）。

---

## 2. 总体架构

```
+------------------+         +------------------+         +---------------------+
|  Collector 插件  |  --->   |  Ingest API 网关 |  --->   |  处理管道(ETL/规则) |
|  (一源一插件)    |         |(鉴权/限流/验参)  |         |  去重/合并/打标     |
+------------------+         +------------------+         +---------------------+
                                                             |
                                                             v
                                               +---------------------------+
                                               |  PostgreSQL(主库)         |
                                               |  + JSONB/全文/GIN/物化视图 |
                                               +---------------------------+
                                                             |
                                               +---------------------------+
                                               |  OpenSearch/TypeSense(可选) |
                                               |  → 高级搜索/聚合/高亮       |
                                               +---------------------------+
                                                             |
                                        +----------------+   +-----------------+
                                        | 前端 Web      |   | 订阅投递服务     |
                                        | (分类/时间线) |   | RSS/Email/Webhook|
                                        +----------------+   +-----------------+
```

* **调度**：主服务根据插件 manifest 中的 cron 表达式触发执行（本地 APScheduler/Celery Beat + Worker；或 K8s CronJob）。
* **插件与主库交互**：一律通过 **Ingest API**（HTTP/JSON，Token 鉴权），禁止插件直连数据库。
* **可观测性**：插件运行日志、拉取数、解析耗时、增量数、错误率统一上报，Grafana/Prometheus 告警。

---

## 3. 插件（采集器）规范

### 3.1 插件清单与生命周期

* **一源一插件**：每个来源（官网/接口/RSS/CSAF）独立仓库或独立目录。
* **Manifest**：`plugin.json`

```json
{
  "name": "msrc-security-update-guide",
  "version": "0.1.3",
  "author": "seclens",
  "homepage": "https://learn.microsoft.com/security-updates/",
  "schedule": "0 */2 * * *",              
  "content_types": ["advisory", "patch"],
  "formats": ["html", "json", "csaf"],
  "lang": ["en"],
  "config_schema": {
    "type": "object",
    "properties": {"proxy": {"type": "string"}},
    "additionalProperties": false
  }
}
```

* **运行**：容器化或虚拟环境运行；必须支持“**增量拉取**”。
* **容错**：指数退避、ETag/Last-Modified/If-None-Match 复用；请求签名/重试上限；失败状态上报。

### 3.2 插件输出（标准事件模型）

* 通过 `POST /v1/ingest/items` 提交数组，单批 100 条以内；重复提交由服务端幂等化。

```json
{
  "source": {
    "source_slug": "msrc_sug",
    "external_id": "msrc-kb-5035778",    
    "origin_url": "https://...",
    "fetched_at": "2025-09-16T12:34:56Z"
  },
  "content": {
    "title": "Windows ... Security Update",
    "summary": "...",
    "body_raw": "<html>...</html>",
    "body_text": "...纯文本...",
    "published_at": "2025-09-10T00:00:00Z",
    "lang": "en"
  },
  "vuln": {
    "cve_ids": ["CVE-2025-12345"],
    "cwe_ids": ["CWE-79"],
    "cvss": {"v3": 8.8, "vector": "CVSS:3.1/AV:N/..."},
    "severity": "High",
    "exploited": false,
    "patch_available": true
  },
  "affects": [
    {"vendor": "Microsoft", "product": "Windows 11", "versions": ">=22H2,<24H2"}
  ],
  "labels": ["official", "os", "windows"],
  "topics": ["advisory", "patch"],
  "extras": {"kb": "5035778"}
}
```

### 3.3 插件运行态上报

* `POST /v1/plugins/{slug}/runs:start|finish`
* 字段：开始/结束时间、拉取总数、新增数、更新数、错误明细、最后光标（分页 token / last\_id / since）。

### 3.4 安全与隔离

* 网络白名单、只出不入；读写分离的最小权限 Token；限速与超时；容器内只读根文件系统；不允许写本地敏感目录。

---

## 4. 数据模型（PostgreSQL）

> 以 **Item (原子信息)** → **Event (归并后的事件)** 的二层模型；多标签/多维度分类。

### 4.1 主要表

```sql
-- 来源/插件
CREATE TABLE sources (
  id SERIAL PRIMARY KEY,
  slug TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  type TEXT CHECK (type IN ('vendor','cert','media','community','gov','research')),
  homepage TEXT,
  lang TEXT[],
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 原始项（幂等：source_id + external_id 唯一）
CREATE TABLE items (
  id BIGSERIAL PRIMARY KEY,
  source_id INT REFERENCES sources(id),
  external_id TEXT NOT NULL,
  origin_url TEXT,
  title TEXT NOT NULL,
  summary TEXT,
  body_text TEXT,
  body_raw TEXT,
  published_at TIMESTAMPTZ,
  fetched_at TIMESTAMPTZ NOT NULL,
  lang TEXT,
  cve_ids TEXT[],
  cwe_ids TEXT[],
  cvss JSONB,
  severity TEXT,                 -- Low/Medium/High/Critical 或 vendor 原值
  exploited BOOLEAN,
  patch_available BOOLEAN,
  affects JSONB,                 -- [{vendor,product,versions}]
  labels TEXT[],                 -- 自由标签
  topics TEXT[],                 -- 受控分类（见 5）
  extras JSONB,
  fingerprint TEXT,              -- 规范化指纹
  UNIQUE(source_id, external_id)
);
CREATE INDEX idx_items_cve ON items USING GIN (cve_ids);
CREATE INDEX idx_items_tsv ON items USING GIN (to_tsvector('simple', coalesce(title,'')||' '||coalesce(summary,'')));

-- 归并后事件（同一 CVE/同一公告簇）
CREATE TABLE events (
  id BIGSERIAL PRIMARY KEY,
  key TEXT UNIQUE NOT NULL,      -- 例如 cve:2025-12345 或 vendor:msrc:kb-5035778
  canonical_title TEXT,
  timeline JSONB,                -- [{type:'published|updated', at, source, url}]
  metrics JSONB,                 -- 聚合指标（最高严重度、影响产品数等）
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- 事件-项 映射
CREATE TABLE event_items (
  event_id BIGINT REFERENCES events(id) ON DELETE CASCADE,
  item_id BIGINT REFERENCES items(id) ON DELETE CASCADE,
  PRIMARY KEY(event_id, item_id)
);

-- 受控标签/分类词表
CREATE TABLE voc_tags (
  id SERIAL PRIMARY KEY,
  slug TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  facet TEXT NOT NULL,           -- domain/os/db/middleware/cloud/vendor/product/region/topic
  parent_slug TEXT NULL
);

-- 用户/订阅
CREATE TABLE users (
  id BIGSERIAL PRIMARY KEY,
  email TEXT UNIQUE,
  webhook_url TEXT,
  prefs JSONB                    -- 语言、时区、摘要频率等
);

CREATE TABLE subscriptions (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT REFERENCES users(id),
  query JSONB,                   -- 过滤条件（见 7）
  channel TEXT CHECK (channel IN ('rss','email','webhook','api')),
  schedule TEXT,                 -- cron 或即时
  enabled BOOLEAN DEFAULT true
);

-- 点赞/热度
CREATE TABLE reactions (
  user_id BIGINT REFERENCES users(id),
  event_id BIGINT REFERENCES events(id),
  kind TEXT CHECK (kind IN ('like')),
  created_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY(user_id, event_id)
);
```

### 4.2 指纹与去重

* **Primary key**：`(source_id, external_id)` 保证原子项幂等。
* **Fingerprint**：`normalize(title) + sorted(cve_ids) + vendor/product` 计算哈希（例如 SHA1）；
* **相似度合并**：无 CVE 的资讯使用 `SimHash/MinHash + Jaccard` 与时间窗口（±14 天）聚类；同簇落到一个 `event`。

---

## 5. 分类体系（Taxonomy v0.1）

> 采用“多维受控词 + 自由标签”的混合模式；受控词确保检索/订阅稳定性。

**Facet 列表**

* **domain**：`advisory`（安全公告）、`patch`（补丁/更新）、`exploit`（利用/PoC）、`threat-intel`、`incident`（事件通报）、`research`、`conference`、`news`
* **asset**：`os`、`database`、`middleware`、`message-queue`、`network-device`、`application`、`cloud`、`container`、`browser`、`mobile`
* **vendor**：标准化厂商名（Microsoft / Red Hat / Oracle / Cisco / Apple / Google / Apache / PostgreSQL / MySQL...）
* **product**：标准化产品名（Windows 11、RHEL、Oracle DB、Cisco IOS XE、iOS、Android、Nginx、Apache HTTPD、Kafka、RabbitMQ...）
* **region**：`global`、`cn`、`us`、`eu` ...
* **lang**：`en`、`zh`...
* **severity**：`Info/Low/Medium/High/Critical`（映射 vendor 原值）
* **signal**：`exploited`、`kev`（进入 CISA KEV）、`patch-available`、`workaround`、`active-scan` 等

> 词表以 `voc_tags` 存储；维护**别名映射表**（alias）做标准化，如 “MSFT→Microsoft”“Win11→Windows 11”。

---

## 6. 处理流水线（ETL）

1. **接收**：校验字段、大小限制、XSS 清洗。
2. **标准化**：

   * 标题/摘要清洗（去品牌前缀、括号噪声、日期尾缀）。
   * CVE/CWE/KB/ODID 正则抽取与校验。
   * 版本范围解析（semver/epoch\:ver-rel），统一为表达式：`>=x,<y`。
   * 语言检测；时间规范化为 UTC。
3. **分类**：

   * 规则优先（来源→vendor/product 映射、路径命名）
   * 轻量模型（文本多标签分类，置信度<阈值回退到规则）。
4. **去重**：指纹对比 + 相似度聚类 → 归并为 `event`，更新时间线。
5. **强化**（可选）：

   * 外部数据补全（例如 KEV、NVD 向量/严重度；保留来源权重与延迟差异）
6. **索引**：写入 OpenSearch 索引（含聚合字段、同义词）。
7. **派发**：触发订阅规则（即时/定时），投递队列。

---

## 7. 检索与订阅

### 7.1 过滤表达能力（统一查询 JSON）

```json
{
  "domains": ["advisory","patch"],
  "vendors": ["Microsoft","Cisco"],
  "products": ["Windows 11","IOS XE"],
  "asset": ["os","network-device"],
  "severity": ["High","Critical"],
  "signals": ["exploited","kev"],
  "cve": ["CVE-2025-12345"],
  "lang": ["en","zh"],
  "date": {"from": "2025-09-01", "to": "2025-09-16"},
  "sort": "published_at:desc"
}
```

* URL 形式：`/search?q=vendor:Microsoft product:"Windows 11" severity:Critical after:2025-09-01`（解析为上面的 JSON）。

### 7.2 订阅通道

* **RSS**：公开/私有（带 token）；支持上述过滤表达式。
* **Email**：即时/日报/周报；HTML + 纯文本；同一事件多来源**合并展示**。
* **Webhook**：`POST` JSON：

```json
{
  "event": {"key":"cve:2025-12345", "title":"...", "severity":"Critical"},
  "items": [ {"source":"msrc_sug","origin_url":"..."}, {"source":"nvd","origin_url":"..."} ]
}
```

* **API**：OAuth2 / Token；速率限制；可分页、可流式（SSE）。

---

## 8. 前端信息架构

* **首页**：

  * **时间线**（Feed 模式）与**列表**双视图；
  * 顶部搜索框 + 快捷过滤（severity、exploited、kev、patch-available）；
  * 今日/本周/本月统计卡片（事件数、受影响产品数、Critical 数、KEV 新增）。
* **分类导航**：按资产（OS/DB/中间件/消息队列/网络设备/云/浏览器/移动）→ 厂商 → 产品。
* **事件页**：

  * 事件总览（严重度、受影响产品/版本、是否在 KEV、是否被利用）；
  * **时间线**（各来源条目、更新/撤稿）；
  * 订阅按钮（该过滤条件一键订阅）。
* **来源页**：展示来源信誉、平均延迟、历史质量（解析率/错误率）。

---

## 9. 管理后台

* 插件管理：上传/更新/回滚、环境变量、默认 schedule、沙箱策略。
* 运行监控：实时日志、错误面板、耗时分布、成功率、增量曲线。
* 词表管理：受控词增删改、别名绑定、审核队列。
* 数据修正：条目回收站、合并/拆分事件、字段纠偏。
* 用户/订阅：封禁、限流、投递重试、退订分析。

---

## 10. 热度与排序

* **热度分** `score = w1*recency_decay + w2*severity + w3*signal + w4*likes`。

  * `recency_decay = exp(-Δt / τ)`；`severity ∈ {0,1,2,3,4}`；`signal`（exploited/kev/patch）加权；`likes` 用 Wilson 分数或对数归一。
* 列表页默认 `hotness` 与 `published_at` 混合排序，事件页内按来源可信度和时间排序。

---

## 11. 安全与合规

* 严格区分**引用**与**原创**，保留原链接与来源水印；遵循 robots/ToS。
* HTML 清洗、URL 安全（跳转链过滤、恶意域名黑名单）。
* API 访问速率与滥用防护、订阅频率限制（阈值 + 自适应退避）。

---

## 12. 可观测性与 SLO

* 关键指标：

  * 来源覆盖度、抓取延迟 P50/P95、解析成功率、事件去重率、订阅投递成功率。
* 告警：来源中断、异常激增/骤降、错误率 > 阈值、投递重试 > 阈值。

---

## 13. 迭代路线图

**MVP（2–3 周）**

1. 10 个优先级最高来源（MSRC、Apple、Cisco PSIRT、Red Hat、Ubuntu USN、Oracle CPU、GitHub GHSA、CISA KEV、Apache、Nginx）。
2. 基础模型：`items` 入库 + 规则分类 + 基于 CVE 的事件合并。
3. 首页时间线 + 分类导航 + RSS 订阅；Email 日报。

**v1.0**

* 指纹/相似度去重、OpenSearch 高级搜索、Webhook 推送、后台词表管理。

**v1.1**

* 轻量多标签分类模型、热度排序、用户点赞、来源质量画像、周/月报模板。

---

## 14. 插件 Python 模板（示例）

```python
# plugin.py
import requests, time
from datetime import datetime, timezone

API = "https://api.seclens.local/v1/ingest/items"
TOKEN = "${INGEST_TOKEN}"

SESSION = requests.Session()
SESSION.headers.update({"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})

LAST_CURSOR_FILE = ".cursor"

def load_cursor():
    try: return open(LAST_CURSOR_FILE).read().strip()
    except: return None

def save_cursor(v):
    open(LAST_CURSOR_FILE, 'w').write(v or '')

def fetch_since(cursor):
    # TODO: 调用来源接口/RSS/CSAF，返回结构化列表
    return []

def normalize(raw):
    return {
        "source": {
            "source_slug": "msrc_sug",
            "external_id": raw["id"],
            "origin_url": raw["url"],
            "fetched_at": datetime.now(timezone.utc).isoformat()
        },
        "content": {
            "title": raw["title"],
            "summary": raw.get("summary"),
            "body_text": raw.get("text"),
            "published_at": raw.get("published_at"),
            "lang": "en"
        },
        "vuln": {
            "cve_ids": raw.get("cves", []),
            "severity": raw.get("severity")
        },
        "affects": raw.get("affects", []),
        "labels": ["official"],
        "topics": ["advisory"]
    }

if __name__ == "__main__":
    cursor = load_cursor()
    raws = fetch_since(cursor)
    payload = [normalize(r) for r in raws]
    if payload:
        r = SESSION.post(API, json=payload, timeout=30)
        r.raise_for_status()
        # 从响应中获得新光标（例如 last_id）
        save_cursor(r.json().get("next_cursor"))
```

---

## 15. Ingest API（草案）

```http
POST /v1/ingest/items
Auth: Bearer <token>
Body: [Item,...]  (参见 3.2)
Resp: { "accepted": 50, "duplicates": 3, "next_cursor": "abc123" }

POST /v1/plugins/{slug}/runs:start
POST /v1/plugins/{slug}/runs:finish

GET  /v1/search?q=...&page=1&size=20
GET  /v1/events/{key}
GET  /v1/sources/{slug}

GET  /v1/rss?query=...    (XML)
POST /v1/subscriptions    (创建/更新)
```

---

## 16. 展示层关键页面（低保真）

* **首页**：时间线（卡片式，右侧 facet 筛选）、顶部搜索、热度榜、今日新增/关键信号小组件。
* **事件详情**：标题 + 严重度 + 信号徽标；受影响产品；时间线（来源条目）；相关事件（相似/同产品）。
* **来源目录**：按资产/厂商/产品分层浏览。

---

## 17. 风险与优先事项（重点）

1. **分类/词表治理**：是系统可用性的瓶颈 → 先做“规则+词表”，再小步引入模型。
2. **去重与归并**：官方与聚合源（如 NVD/KEV）时间与字段不一致 → 事件时间线化，避免“二选一”。
3. **来源条款与抓取礼仪**：尊重 ToS/robots；对需要 API Key 的来源单独申请与配额管理。
4. **投递风控**：Webhook 与 Email 的滥用与退信处理、重试队列、速率限额。
5. **插件安全**：上传即运行存在风险 → 沙箱/白名单、代码扫描、只读文件系统、最小权限。

---

## 18. 落地建议（下一步）

* **Week 1**：确定 Taxonomy v0.1 + 词表与别名表；落库 DDL；完成 Ingest API 与 2 个示范插件。
* **Week 2**：时间线页 + 基础检索；RSS；事件合并（CVE 维度）。
* **Week 3**：管理后台（词表/插件）；Email 日报；去重优化与 OpenSearch 对接（可选）。

> 本草案覆盖架构、数据模型、采集规范与 UI/订阅的关键点，可直接作为团队对齐与任务拆分的基线文档。


太好了！我把你的需求和想法整理成了一份**完整的技术方案草案**，已经放到右侧画布里（“SecLens 1.0 技术方案（草案）”）。里面包含：

* 端到端架构图（采集→ETL→去重归并→索引→前端/订阅）
* 插件规范（manifest、输出数据模型、运行态上报、隔离与安全）
* **数据库表设计**（items/events 双层模型、词表/别名、订阅/投递、点赞热度）
* \*\*分类本体（Taxonomy v0.1）\*\*与别名治理方案（这是最关键的难点）
* 去重与事件归并策略（CVE/指纹/相似度聚类 + 时间线合并）
* 搜索与订阅（统一过滤表达式、RSS/Email/Webhook/API）
* 前端信息架构（Feed 模式 + 列表、事件页时间线、来源质量画像）
* 运行可观测性、风控、合规与 SLO
* MVP→v1.1 的迭代路线图
* Python 插件模板与 Ingest API 草案

接下来建议的**落地顺序**（也写在文档最后）：

1. 先冻结 **Taxonomy v0.1 + 别名表**（这决定了后面所有筛选/订阅的可用性）。
2. 上线 Ingest API + 两个示范插件（MSRC、CISA/KEV 或 Ubuntu USN）验证全链路。
3. 做 **基于 CVE 的事件归并** 和首页时间线 + RSS；随后再引入指纹/相似度的“无 CVE”资讯归并。


如果你愿意，我可以按这份草案直接把：

* **PostgreSQL DDL** 导出为可执行脚本，
* **FastAPI 的 Ingest API** 雏形项目结构，
* **两个示范采集插件**（一 HTML/RSS、一 JSON/CSAF）

都一次性给你打包出来。
