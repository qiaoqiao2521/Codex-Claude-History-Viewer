# Progress

## Current

2026-09-22：HV-reuse-linux-v1 实施 **5/5**。代码、契约测试、两轮独立审查及 Linux 真实浏览器工程验收完成；`1.3.0-rc.1` 候选代码为 `0bb034bd25c7ab6d2677d241dc087eb15313638b`，包、干净安装与 v1.2.0 回滚核验均通过。该日期 U1 尚待安排；**2026-10-01 用户已取消 U1/M3，当前工程完成，无待安排试用，Agent 对接为主**。

## Done

- R1 跨来源词法检索/摘录/精确消息深链与修订分页；R2 来源诊断/显式刷新/脱敏诊断；R3 完整 cwd 项目时间线；R4 精确文件路径、工具结果和显式补丁；R5 最多5片段/8000字符、修订校验与遮盖预览导出。
- E0 冻结题集 16/20 准确证据命中、4/4 负例；10k HTTP p95 120.51ms；旧单源门槛16/16。详见 [验收摘要](acceptance.json) 与 [发现](findings.md)。
- 328 Python（327 pass / 1 external-reader skip）、7/7 JS，语法和 diff 检查通过。Linux Chrome 合成浏览器检查通过，独立人类试用未运行。
- U1 五任务与观察材料、可复现打包脚本已准备；不自动邀请或外发。
- 保留三处 unrelated untracked，未把它们纳入交付。

### Candidate artifacts

源码冻结：`0bb034bd25c7ab6d2677d241dc087eb15313638b`（功能主提交 `7499157` + 导出定位字段收紧）。收尾文档提交可以在其之后，不改变包内源码身份。当时 U1 pending，候选仅本地交付；以下是冻结历史产物，不代表当前发布状态。

- 便携包：`work/reuse-delivery/final/history-viewer-1.3.0-rc.1.zip`，SHA-256 `21232aea84342c9788c81b6d0200e94c5320ec957322039d7b50f736469f529d`。
- 合成试用包：`work/reuse-delivery/final/history-reuse-trial-1.3.0-rc.1.zip`，SHA-256 `1fb62066b96a19738eee835c61d162c8405cb62915b0996d1412f126718adfba`；只含 Codex 6 / Claude 6 合成会话，内置 TRIAL_TASKS.md。
- [参与者任务单](trial/tasks.md) / [组织者观察与答案](trial/observer.md)。答案不随试用包提供。
- 同目录 portable-install.json / trial-install.json / material-preflight.json 及 HTTP 基准保留原始证据；[acceptance.json](acceptance.json) 保存可随仓恢复的简要事实。构建时 manifest 的 material_preflight=not_run 是历史状态，外部预检记录为 passed；该验收快照的 U1 为 pending，保留原样；当前已取消。

再生：`python3 scripts/build_release.py --revision 0bb034b --output /新目录/portable.zip`；`python3 scripts/build_reuse_trial.py --revision 0bb034b --output /新目录/trial.zip`。产物目录不入 Git，不含真实历史与缓存。

## Remaining

本计划无开放工程阻断，U1 已取消。本次只提交源码与文档，不创建稳定发行或替换安装。仓库交付与保留项见 [收尾记录](agent-first-closeout.md)。

## Issues

Q17–Q20 自然语言改写未命中；原生库 ordinary provenance/文件追溯和 Hermes audit 的限制如实暴露。Windows/WSL、模型外呼、原生库性能、浏览器绘制时间未验证，不属于 Linux 合成性能成绩。

## Next

以具体 Agent 使用反馈推进检索和交接；不再安排 U1。既有测试入口与证据见 task_plan.md；未授权自动执行模型任务，不留自动续跑。
