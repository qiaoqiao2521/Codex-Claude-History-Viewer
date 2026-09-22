# Findings

## 规划阶段代码基线（2026-09-22；以下为实施前观察）

- `main` / `a58df9a817f93ba3ddc84ca14193dd8ad380e495`，规划开始时 tracked clean。保留原有 `agents/controlmesh_typescript_migration_plan(1)..md`、`plans/specmesh-r001-validation/`、`plans/ubuntu-keyboard-recovery/`。
- v1.2.0 的旧独立交付已完成；本轮没有重跑旧验收，也没有核验此刻运行进程。历史 M3 独立用户试用仍未完成。
- 上一轮本仓代码只读比较：主搜索固定来源，会话结果无命中片段；消息内搜索已有摘录/消息索引，审计有跳转能力，适合复用。
- `history_core/service.py::workspace` 聚合各来源最近会话再取全局 12 条，尚无项目级时间线。`static/workspace.js` 提供会话级入口，证据位置主要以文字显示。
- 已有文件路径过滤、handoff 导出、resume command、Linux 启动/桌面入口与 health；新计划聚焦连接路径和缺少的交互，不能把已有能力列成零起点。
- `docs/ARCHITECTURE.md` 仍夹有旧 Python 3.8 与“跨修订分页未保证”表述；当前 PROJECT 为 3.11+，v1.2 段及代码已有修订协议。后续涉及模块时同步，当前不扩大文档整理范围。

## 外部参考（阅读文档，不代表安装测评）

2026-09-22 复核官方 README（未安装、未运行其基准、未复制代码）：

- [HizTam/codex-history-viewer](https://github.com/HizTam/codex-history-viewer)：项目关联、文件 AI 改动历史、搜索词带入会话、交接文件/提示词。这支持把“从文件到证据再到复用”作为流程比较点，不代表本项目需要 VS Code 扩展或同等功能数量。
- [jhlee0409/claude-code-history-viewer](https://github.com/jhlee0409/claude-code-history-viewer)：全来源搜索、项目/worktree 浏览、消息深链及桌面/服务器两种入口。借鉴入口连续性，不引入其技术栈或拓展平台。
- 上轮已读的 [cass](https://github.com/Dicklesworthstone/coding_agent_session_search) 文档提供命中摘录、相关性排序与上下文展开参考；本轮没有安装、跑分或代码移植。

建议来自用户工作流与本仓缺口，不以 provider 数量或 star 排名决定优先级。

## 设计判断

- 项目是跨会话的工作范围，单条会话成功不足以证明同项目所有阻塞解除。
- 文件变化的意图、工具执行结果、历史测试及当前文件状态是不同事实，时间线须保留这种区别。
- 统一搜索之外优先减少用户找回项目、追溯文件和组织交接的操作成本；先修首次使用障碍，再引入更多个性化功能。
- 本轮仅授权规划。完整计划的执行、U1 试用和新发布均未开始。

## 增量事实复核

- 项目列表已支持 cwd 聚合（`history_core/sources.py::list_projects`）；新 R3 要做的是跨来源项目连续阅读，非新建项目列表。
- `static/app.js` 已有文件 filter 和成果文件点击，后端 `list_sessions_page` 的 file_path 做候选/精确过滤；新 R4 是带逐次证据的时间线。精确过滤后的跨页结束条件列为待验收项，并未在本轮运行复现。
- `app.py::handle_session_audit`（当前 699 行）调用 `build_handoff_bundle` 时未传 Reader 的 provenance；`history_core/service.py::handoff` 则经 selected_audit 取得快照和来源。R5 明确先统一两条路径，不假定当前 Web 已有相同修订校验。
- `audit/handoff.py` 自动挑选证据与变更；当前有主题/预览/复制/下载，缺少用户跨会话挑选。R5 限制为少量选择，不做自动综合知识库。
- 只读协作审查认可四个非搜索增量；文件工作脉络低于项目连续视图/选择性交接，排序降至 P2。

## 计划审查结果

独立只读审查发现两处表述需修正，均已采纳：文件过滤是“单来源跨会话”，不是单会话；检索 Hit@5 只统计有答案题，负例/来源失败/分页契约另计。性能进一步固定 10k 总量、来源配比、5 次预热/100 次采样、HTTP 起止与 nearest-rank p95，首次进程及浏览器绘制单列。此为计划修正，无产品代码或实测结果。

## 本轮实施与验收（2026-09-22）

- 用户授权完整实施，并明确 U1 稍后安排。五项功能完成；候选 1.3.0-rc.1 不取代稳定发行 v1.2.0。代码、包、安装身份以 progress 的最终冻结记录为准。
- E0 在旧 HEAD a58df9a 上先冻结：已知来源情况下会话 Hit@5 16/20，首屏消息证据 0/20。新跨来源准确消息证据 16/20，负例 4/4；Q17–Q20 的自然语言改写未命中，保留原题。题集只修正 store_id 字段契约，语义摘要 8de4b68ab63a5f0a4366b2e5bbcf18d067f4b8c216faa2b067c9a655cf3eebde 未改题意/答案/门槛。
- 10k 固定 JSONL：Codex/Claude 各 5000，20 消息/16KiB。5 次预热、100 HTTP，nearest-rank p95 129.15ms，首次新服务进程 53.39ms（不声称 OS 冷缓存）。保留旧单来源 16/16 门槛通过，10k RSS 34.8MiB、热查 p95 166.81ms。原生数据库性能未测。
- 机器结果摘要、来源矩阵、回归与浏览器事实见 [acceptance.json](acceptance.json)；详细本机原始测量保存在忽略的 work/reuse-evaluation/，可按脚本与冻结题集再生。测量有自己的源码摘要，不把后续纯文档改动冒充测量时源码。
- 原生能力：OpenCode 可检索/项目/审计，但 ordinary provenance unknown，不能据此选择修订证据；Hermes 可搜正文及 reasoning，cwd 未记录则未绑定，ordinary audit 不支持；两者文件追溯显式 file_history_not_indexed。OpenClaw JSONL 的检索/项目/修订审计通过合成测试。这不是这些工具的真实账户验收。
- 两轮独立审查复现并修复：部分来源查询失败导致跨页混合集合、Hermes reasoning 被正文遮盖、indexing health 等待锁、旧深链索引漂移。另通过原生矩阵修正 Hermes transport 冒充 cwd；浏览器发现 Claude 显式退出码遗漏，修复并将 AUDIT_VERSION 升到 3。
- 搜索消息偏移与审计事件偏移不同。前者经 source_revision 校验缓存页面；后者经 evidence_id/raw line 与内容修订读取原始行。文件工具仅对精确路径和明确调用结果配对，结构化补丁可展示，当前磁盘状态始终 unknown。
- Chrome 实机验证：消息4准确跳转/返回保留查询、来源诊断、三个项目、src/a.py 的两来源记录、失败保留、原始行及纯文本 patch；选择完整消息和审计摘要分开标示。剪贴板和本地 Markdown/JSON 下载验证。420/480px 测得无横向溢出；浏览器绘制时间因当前只读接口不提供 performance 而保留未测，不用 HTTP 时间替代。
- 仅合成数据。旧真实缓存、真实 JSONL 与第三方库未用于本轮浏览器和性能验证；试用包只包含12条合成记录。U1 尚未邀请/运行，不由 Agent 代测。
