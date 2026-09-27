# Findings

- 项目阅读器由 `/history` 的 app.js 管理；项目会话分页来自 `/api/reuse/sessions`，每源候选上限 500，cursor 绑定来源修订。归组应在分页前生成元数据，不改分页集合。
- 消息导航必须用 `messages ORDER BY ts_ms,id` 的绝对位置。audit 的事件序号不可当 reader 的消息索引。
- 现有 parser 索引文本完整，search_blob 与摘录曾因先截断漏掉尾部命中；关键消息同样采用全文定位后截取。native DB 不强行套用消息索引 schema。
- 首轮归组是可解释线索，不是同任务判定；原文/失败/每个成员都保留。

## 实现与验证结果

两后端模块各有独立测试，Handler 另用真实临时索引和只读 OpenCode DB 验证。首轮 474 项基线加 6 项 Handler 集成后为 480 项。详细缺陷、纠正过的根因和验收范围见 [browser-report.md](browser-report.md)。无需改 parser 版本或重新解析历史。
