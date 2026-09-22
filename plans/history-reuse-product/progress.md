# Progress

## Current

2026-09-22：HV-reuse-linux-v1 实施 **5/5**。代码、契约测试、两轮独立审查及 Linux 真实浏览器工程验收完成；正在冻结 `1.3.0-rc.1` 候选源码并验证包/干净安装。**U1 pending**，用户明确稍后安排。

## Done

- R1 跨来源词法检索/摘录/精确消息深链与修订分页；R2 来源诊断/显式刷新/脱敏诊断；R3 完整 cwd 项目时间线；R4 精确文件路径、工具结果和显式补丁；R5 最多5片段/8000字符、修订校验与遮盖预览导出。
- E0 冻结题集 16/20 准确证据命中、4/4 负例；10k HTTP p95 129.15ms；旧单源门槛16/16。详见 [验收摘要](acceptance.json) 与 [发现](findings.md)。
- 328 Python（327 pass / 1 external-reader skip）、7/7 JS，语法和 diff 检查通过。Linux Chrome 合成浏览器检查通过，独立人类试用未运行。
- U1 五任务与观察材料、可复现打包脚本已准备；不自动邀请或外发。
- 保留三处 unrelated untracked，未把它们纳入交付。

## Remaining

候选 commit、离线包 SHA、干净安装/回滚及最终材料预检记录；U1 由用户安排。

## Issues

Q17–Q20 自然语言改写未命中；原生库 ordinary provenance/文件追溯和 Hermes audit 的限制如实暴露。Windows/WSL、模型外呼、原生库性能、浏览器绘制时间未验证，不属于 Linux 合成性能成绩。

## Next

完成候选包身份链，停止临时服务后交付；此后仅等待 U1 的独立用户反馈。
