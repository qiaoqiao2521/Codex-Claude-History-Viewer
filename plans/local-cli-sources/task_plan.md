# 本机 Agent CLI 历史来源

## Goal
按用户“看看本地有什么 cli，都加上，opencode、cbc 都加上”的要求，盘点 Linux 本机 Agent CLI，接入可读取的独立历史存储，贯通检索、会话、用量与交接。命令别名按底层存储归并；不能验证的能力明确标记。

## Scope
- 只读本机历史，不调用模型、不登录、不上传原文。
- 保持 Python 标准库与无构建前端；已有来源兼容。
- 不修改旧候选包或将 U1 待试用改为通过。

## Plan
- [x] L1 盘点可执行文件、别名与实际存储格式。
- [x] L2 实现解析器和来源发现，接入 Web / HistoryReader。
- [x] L3 接入来源 UI、能力提示及来源交接；用合成数据验证边界。
- [ ] L4 回归、只读真实数据核验、浏览器验收及文档收口。

## Acceptance
明确包含 OpenCode、CodeBuddy/cbc；每个发现的独立来源有读取能力或具体不支持原因；别名不重复计数；demo 隔离真实历史；失败/未知状态不伪装成完成证据。

## Status
L1–L3 complete. L4 code, read-only data and browser acceptance complete; final regression and local candidate installation in progress. Legacy AGY PB / missing desktop bodies are explicit capability limits, not silently claimed successes. U1 remains pending independently.
