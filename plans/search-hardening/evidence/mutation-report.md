# Mutation 实验报告 — 检索链路注入验证（exp-29b202832208176d042b3c94）

日期：2026-09-26（UTC，实验记录时间戳为准）。对象：隔离副本 `/tmp/cchv-hardening/mutant`
（HEAD `8969e4e` + 未提交检索修复，rsync 自工作树，排除 .git/缓存）。fixture：`/tmp/cchv-hardening/home`
（全合成）；预期：`plans/search-hardening/oracle.md` + `/tmp/cchv-hardening/manifest.json`。

## 正常基线（注入前对照）

- 副本全量 `python3 -m unittest discover -s tests`：437 tests OK（1 skip）。
- 独立探针 `probe.py`（11 个手工用例，覆盖 2M 边界、尾部命中、raw fallback、字面 LIKE、
  中文、跨源同 id、项目路径命中、干净零命中）：11/11 PASS，源文件 SHA256 前后一致。

## 变体与判定

### M1 — 会话正文匹配退化为仅 search_blob（首次植入 invalid，重做后 detected）

- **planted**：`history_core/sources.py` `_indexed_body_match_sql`，将 messages 子查询的
  join 条件改为 `search_message.session_id=''`（恒不匹配；绑定数不变，SQL 合法）。
- 首次尝试直接删除 EXISTS 导致 LIKE 占位符 4→1 不匹配，所有查询响亮报
  `source_schema_unavailable` —— 判 **invalid**（未能构造目标机制的忠实变体），重做占 1 次 attempt。
- **reached**：探针 7 例 FAIL（`tailneedle`、`rawfallback`、`双千兆`、`100%_done\`、`Café`、
  `betatitle`、`gammaterm1 gammaterm2` 全部由"命中"退化为 **无 errors 的空结果**）。
- **responsible_check**：`python3 -m unittest tests.test_large_session_search tests.test_large_search_snippets tests.test_reuse_contract`
  → **16 failures + 5 errors**（含 raw_fallback、2M 后双语召回、字面 LIKE、语料排序等）。
- **contract_violation**：I2（裁剪/回退不可造成漏检）；并使误导性空结果与真零命中不可区分（I6 风险面）。
- **分类：detected**。

### M2 — 摘录匹配前预截断 8192 字符（detected）

- **planted**：`history_core/reuse.py` `_indexed_snippets`，`text = "substr(COALESCE(m.text,''),1,8192)"`。
- **reached**：探针 `q=tailneedle` → 会话仍命中但 `snippets=[]`（关键词位于 12,000 字符消息的
  ~11,500 处，超出预截断窗口）——静默丢失消息级定位。
- **responsible_check**：`tests.test_large_search_snippets` → **4 failures**
  （`tail_after_two_million…(tailneedle/后置系统)`、`phrase_is_preferred…`、`multiple_query_terms…`）。
- **contract_violation**：I2（单条消息尾部命中可定位）。
- **分类：detected**。

### M3 — 查询异常吞成空结果（detected）

- **planted**：`history_core/reuse.py` `search()` 中 per-source `except` 分支改为 `pass`
  （不追加 `errors`）。
- **reached**：budget 饥饿探针（`query_budget` 替换为 execute 即抛 `interrupted`）→
  `items=0, errors=[], partial=false` —— 与干净零命中**完全不可区分**。
- **responsible_check**：`tests.test_reuse_contract` →
  `test_query_failure_cannot_issue_or_consume_mixed_source_cursor` **FAILED**。
- **contract_violation**：I6（失败/部分/空/零命中必须可区分）。
- **分类：detected**。

## 恢复对照

每次植入后恢复原件并复跑：责任测试文件 29/29 OK；副本全量 437 OK（1 skip）；探针 11/11 PASS；
预算饥饿探针恢复为 explicit（errors+partial）。源 fixture 全程 SHA256 无变化。

## 边界声明

- 注入缺陷为人工构造，**不代表产品原本存在同类缺陷**；detected 仅说明现有检查能抓住该机制。
- 变体预算 3/3 已用完（含 1 次 invalid 重做）；无 corrections。
- 复现命令：见 `plans/search-hardening/` 下 probe/clusters 脚本（/tmp 副本随清理失效，脚本已留在 evidence/）。
