# SecLens Agents 指南

面向采集代理（agents）与插件开发者的运行规范，重点记录时间字段的梳理、解析策略与质量控制流程。本文档应在每次引入新来源或调整解析逻辑时同步更新。

## 时间字段盘点（2025-10）

| source_slug | 原始时间示例 | 格式/来源 | 是否自带时区 | 已观测问题 | 建议默认时区 |
| --- | --- | --- | --- | --- | --- |
| aliyun_security | `publishTime = 1751627951000` | API 毫秒时间戳 | ✅（UTC 隐含） | 无 | 不需要 |
| doonsec_wechat | `2025-10-10T11:20:49` | RSS `<pubDate>` ISO 字符串 | ❌ | 解析为 UTC，实际应为 UTC+08，产生 8 小时偏差 | `Asia/Shanghai` |
| exploit_db | `Tue, 16 Sep 2025 00:00:00 +0000` | RSS `<pubDate>` | ✅ | 无 | 不需要 |
| freebuf_community | `Fri, 10 Oct 2025 02:34:48 +0800` | RSS `<pubDate>` | ✅ | 无 | 不需要 |
| huawei_security | `publishDate = 2025-10-08` | API 字符串（无时间） | ❌ | 解析为 UTC 零点，偏离本地时间 | `Asia/Shanghai` |
| linuxsecurity_hybrid | `Wed, 01 Oct 2025 09:35:34 +0000` | RSS `<pubDate>` | ✅ | 无 | 不需要 |
| msrc_update_guide | `Thu, 09 Oct 2025 16:08:32 Z` | RSS `<pubDate>` | ✅ | 无 | 不需要 |
| oracle_security_alert | `Fri, 10 Oct 2025 18:00:00 +0000` | RSS `<pubDate>` | ✅ | 无 | 不需要 |
| redhat_advisory | `2025-10-09T17:48:05Z` | REST JSON | ✅ | 无 | 不需要 |
| sihou_news | `Thu, 09 Oct 2025 14:58:05 +0800` | RSS `<pubDate>` | ✅ | 无 | 不需要 |
| ccgp_local_procurement | `2025-10-10 13:58` | HTML 列表 `<em>` 字段 | ❌ | 需按北京时间解析 | `Asia/Shanghai` |
| ccgp_central_procurement | `2025-10-09 08:30` | HTML 列表 `<em>` 字段 | ❌ | 需按北京时间解析 | `Asia/Shanghai` |
| tencent_cloud_security | `2025-10-09 14:17:21` | HTML async JSON | ❌（插件内手工设定） | 已手动转 UTC+08 | `Asia/Shanghai`（现有实现已覆盖） |
| the_hacker_news | `Thu, 09 Oct 2025 22:49:00 +0530` | RSS `<pubDate>` | ✅ | 无 | 不需要 |
| ubuntu_security_notice | `Fri, 10 Oct 2025 03:01:00 +0000` | RSS `<pubDate>` | ✅ | 无 | 不需要 |

> 采样时间：2025-10-10；若上游格式调整，请在复测后更新表格。

## 统一的时间解析蓝图

1. **候选字段采集**：抽出 item 级字段（`pubDate`、`published`、`datePublished` 等）、feed/channel 元信息（`lastBuildDate`）、HTTP header (`Date`)、以及插件输入参数。
2. **解析函数**：集中到 `app/time_utils.py` 中实现 `resolve_published_at(raw_candidates, policy, fetched_at)`，内部使用 `email.utils.parsedate_to_datetime`、`datetime.fromisoformat`、必要时引入 `dateutil.parser.isoparse` 兜底。
3. **策略驱动**：为每个来源维护 `TimePolicy`：
   ```python
   TimePolicy(
       default_timezone="Asia/Shanghai",
       naive_strategy="assume_default",  # 或 "reject" / "utc"
       max_future_drift_minutes=120,
       max_past_drift_days=365,
       forbid_midnight_if_no_time=True,
   )
   ```
   清单存放在 `resources/time_policies.yaml`（建议新建）并在插件加载时注入。
4. **多层兜底**：
   - 命中带时区的字段 → 直接转 UTC。
   - 无时区但 policy 指定默认 → 先绑定默认时区，再转 UTC。
   - 数据异常或缺失 → 返回 `None`，由上层选择 `fetched_at` 或丢弃。
5. **元信息回写**：解析结果写入 `bulletin.extra["time_meta"] = {"source": "item.pubDate", "applied_timezone": "Asia/Shanghai", "fallback": False}`，方便排查。

## 数据质量与告警

- **未来漂移**：`published_at - fetched_at > policy.max_future_drift` 视为可疑，降级为 `fetched_at` 且打上 `time_meta["flag"] = "future_drift"`.
- **过旧数据**：早于最近一次游标保存时间 + `max_past_drift_days` 的条目默认跳过，避免重复回灌。
- **解析失败日志**：`logger.warning("time_parse_failed", extra={"source": slug, "payload": raw})`，并在 Prometheus/ELK 中做聚合。
- **定期体检**：添加 `scripts/check_time_policy.py`，按来源抓取 3 条样本并输出解析链路，供巡检。

## 落地步骤

1. **实现工具库**：编写 `app/time_utils.py` 与 `TimePolicy` 定义，附带单元测试覆盖各种格式（RFC822、ISO、纯日期、时间戳）。
2. **整合老插件**：逐个 collector 引入工具函数，删除分散的 `_parse_pub_date` 实现，确保使用政策映射。
3. **完善测试**：为每个插件新增“无时区场景”单测；Doonsec/华为/Tencent 需覆盖默认时区的断言。
4. **监控配置**：在现有日志与告警体系中增加 `time_meta.flag` 维度，首月重点关注 Doonsec/Huawei。
5. **文档同步**：更新 README 与 `docs/PLUGIN_SPEC.md`（当前 PR 已完成），后续若策略变动需关联更新。

执行完成后，所有新旧来源的时间线将具备可追溯性，排序稳定性亦可满足国内用户的 UTC+08:00 预期。
