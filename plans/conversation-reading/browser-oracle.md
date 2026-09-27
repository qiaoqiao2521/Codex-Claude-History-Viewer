# 浏览器独立预期（操作前固定）

只用 `build_fixture.py` 构造的合成记录。来源同 ID 保留为不同会话；不接触用户历史。

- `/synthetic/login` 应有 3 个会话：Codex/Claude `shared-session` 两个同标题组成一组，Codex `unrelated` 单独保留。展开和关闭归组后，各有 3 个原始行。组标签只表示相关线索。
- Codex `shared-session` 原文索引固定为：0 context、1 用户请求、2 方案、3 tool use、4 失败结果、5 复测陈述、6 最后回复。关键消息应为 1/2/4/5/6；0、3 不作节点。实际点击消息 4 后阅读器应显示“已定位消息 4”和 `LoginExpired` 原文，不靠页面脚本直接跳转。
- 切到 Claude 同 ID 会话，应显示 Claude 的旧失败原文，关键消息面板先清空；重新展开不能出现 Codex 复测。
- `/synthetic/paging` 共 51 个相同标题会话；第一页 50 个，下一页 1 个。归组计数先为 50/51，再为 51/51，原始成员身份不重不漏。
- native details 的 Enter/Space 可以开关；420px 宽度应能读标题、列表与关键消息，无页面横向溢出。
- 浏览器、全量测试和独立用户试用分别记账。真实 Chrome 不可用时可用隔离浏览器验证合成来源，不能称真实用户完成 U1。
