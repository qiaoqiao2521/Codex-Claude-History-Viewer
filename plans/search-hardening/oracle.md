# 检索链路独立预期与合成 Fixture 清单（oracle）

写作顺序：本文件在深入探测实现行为**之前**起草，预期只来自用户需求与已声明契约，
不得把实现现状抄成正确答案。生成时间：2026-09-06。

## 契约来源（独立于实现代码）

1. `PROJECT.md` Success："快速定位并检查相关会话……把主张追溯回证据"。
2. `plans/large-session-search/task_plan.md` Acceptance：2M 字符后中英文可命中；长单条
   消息尾部命中可定位；LIKE 特殊字符按文字匹配；原始历史不变；既有分页/修订与资源预算保留。
3. `history_core/reuse.py` 模块声明："Bounded, revision-bound cross-source history read models"。
4. 本轮任务书九条不变量。

## 九条不变量的可检验预期

| # | 不变量 | 可观察预期 |
|---|---|---|
| I1 | 发现、命中、摘录、跳转同源同会话 | 搜索结果 item 的 (system,source,store_id,id) 与点击后 `/history` 页加载的会话一致；`snippet.message_index` 等于阅读器该消息的绝对索引 |
| I2 | 展示裁剪不造成漏检 | 关键词位于 2M 字符之后、或单条消息 8192 字符之后的尾部时，会话级与消息级检索都必须命中 |
| I3 | 词法行为有契约 | 多词 AND 定位会话；大小写：ASCII 不敏感；字面 `%`/`_`/`\` 按文字匹配不拓宽 |
| I4 | 过滤不改绝对索引 | context 类消息被排除出摘录，但保留其索引序号（命中消息索引不因排除而位移） |
| I5 | 旧缓存可读、查询不隐式改写 | 旧 schema 缓存可查询；查询前后源 JSONL 字节与缓存内容哈希不变 |
| I6 | 失败/部分/空/零命中是不同状态 | 来源失败：`errors` 非空 + `partial=true`；候选截断：`truncated=true`；真零命中：无 errors 且 `partial=false` 且 items 空 |
| I7 | 修订变化不返回混合分页 | cursor 携带修订；来源变化后翻页必须显式失败（`index_revision_changed`），不允许旧 cursor 静默续读 |
| I8 | 乱序/切换不覆盖当前意图 | 前端对同一端点的并发请求以序号守卫；慢响应不得覆盖较新查询的渲染 |
| I9 | 入口差异须有契约依据 | legacy `/api/{s}/{src}/sessions?q=` 与 reuse `/api/reuse/search` 对同一 fixture 的命中集合不得矛盾 |

契约未定义处（候选，待实验后归类 contract_gap）：
- G1 非 ASCII 大小写折叠（如 `É`↔`é`）行为未在任何已读契约中声明；SQLite `lower()` 仅折叠 ASCII。
- G2 多词查询的摘录排序：跨消息按消息序取前 3 个"任一词"命中，完整短语命中若位于更晚消息可能不出现——文档字符串只声明"消息内短语优先"，跨消息排序无契约。
- G3 仅标题/项目命中时 `snippet_status='metadata_match_or_excerpt_unavailable'` 与"零命中"的区分已实现，但该字符串契约未见用户侧文档声明。

## 合成 Fixture（全部合成数据；不复制真实会话）

目录：`/tmp/cchv-hardening/home/{codex,claude}`（HOME 指向 fixture home 实现来源隔离），
缓存 `/tmp/cchv-hardening/cache`，端口 8799（避开 8787/8895 现有服务）。

| 会话 | 内容（手工定义） | 预期 |
|---|---|---|
| A `alpha-0001` (codex) | filler 2,100,000 字符；ctx 消息含 `双千兆CTX`（kind=context）；`m_long` 12,000 字符仅尾部 11,500 处有 `tailneedle`；`m_target` 含 `双千兆网卡`；`m_utf` 含 `Café café Ω 🎯`；`m_lit` 含 `100%_done\path` | 见下表 |
| B `beta-0001` (codex) | 关键词 `betatitle` 仅出现在标题 | q=betatitle 命中 B；摘录为空、snippet_status=metadata_match_or_excerpt_unavailable |
| C `gamma-0001` (codex) | m1 含 `gammaterm1`，m2 含 `gammaterm2`；第 2101 条消息（>2000）含完整短语 | q="gammaterm1 gammaterm2" 命中 C（跨消息 AND）；消息级至少命中 m1 所在索引 |
| D `alpha-0001` (claude) | 与 A 同 id、不同正文，含 `claudedistinct` | q=claudedistinct 仅命中 claude 侧；两条同 id 记录互不混源 |
| E `quiet-0001` (codex) | 无任何关键词 | q=nomatchXYZ 零命中：所有源 items 空且无 errors |

### A 会话消息序（手工定义，绝对索引以 messages 表 ts_ms,id 排序为准）

| 绝对索引 | 内容 | 角色 |
|---|---|---|
| 0 | session_meta（用户首问，含 `alphagoal`） | user |
| 1 | filler 2.1M 字符 | assistant |
| 2 | ctx：`<permissions instructions>双千兆CTX…`（应为 context，排除出摘录但占索引） | system |
| 3 | `m_long`（12,000 字符，尾部 `tailneedle`） | assistant |
| 4 | `m_target`：`在双千兆网卡上验证 OpenWrt` | assistant |
| 5 | `m_utf` | assistant |
| 6 | `m_lit` | user |

### 手工预期表（逐查询）

| 查询 | 会话命中 | 消息级预期 |
|---|---|---|
| `双千兆` | A | 命中索引 4（`m_target`）；索引 2（ctx）不得出现；索引 1 filler 之后仍可命中 |
| `双千兆CTX` | 无（context 不参与会话匹配） | 无 |
| `tailneedle` | A | 命中索引 3，摘录含 `tailneedle`（证明无 8192 预截断） |
| `100%_done\` | A | 命中索引 6，字面匹配 |
| `%` | A（仅 m_lit 含字面 %） | 不得匹配全库 |
| `Café` | A | 命中索引 5（ASCII 大小写折叠；`É` 折叠行为记 G1） |
| `betatitle` | B | items=[B]，snippets=[]，snippet_status=metadata…unavailable |
| `gammaterm1 gammaterm2` | C | 跨消息 AND；至少一条摘录索引=m1 的绝对索引 |
| `第2101条短语`（两词） | C | 2001 之后的消息可命中（I2） |
| `claudedistinct` | D（claude 源） | codex 源不得出现同 id 幽灵命中 |
| `nomatchXYZ` | 无 | 全源零命中、无 errors、partial=false |

## 浏览器场景 oracle

- B1 正常链路：搜索 `双千兆` → 结果含 A → 点击"核对完整消息" → `/history?...message=4` →
  阅读器可见 `在双千兆网卡上验证 OpenWrt` → 返回 → 换查询 `tailneedle` 结果正确。
- B2 来源故障：chmod 000 codex fixture 目录 → 搜索应仍返回 claude 侧结果且页面/接口
  明示 codex 错误（partial），不得呈现为全局零命中；恢复权限后重试完整恢复。
- B3 修订变化：翻页 cursor 存续期间向 codex fixture 追加新会话文件 → 续页必须显式
  `index_revision_changed`（HTTP 409）并提示重新搜索，不得混合新旧页。

## 基线事实（本轮实测）

- HEAD `8969e4e`；未提交：`history_core/reuse.py`、`history_core/sources.py`、
  `docs/ARCHITECTURE.md`、`plans/README.md`、`plans/history-viewer-product-validation/findings.md`、
  `tests/test_reuse_contract.py`；未跟踪：`plans/large-session-search/`、
  `tests/test_large_session_search.py`、`tests/test_large_search_snippets.py`（另有三组无关未跟踪目录）。
- 运行状态：8799 为本轮隔离实例；8895 为既有真实数据服务（PID 882276）；8787 无监听。
- 基线测试：437 Python（436 通过 1 跳过）、9 套 JS 全过（2026-09-06 实测）。
