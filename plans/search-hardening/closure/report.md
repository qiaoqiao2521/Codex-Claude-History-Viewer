# 检索加固补证 — 2026-09-27

本报告是独立补证，不覆盖原实验和报告，不新增或倒填 attempt。旧 mutation/browser 实验仍各登记 **1/3**。本轮没有改产品实现或既有 `tests/`。

## 判定范围

原复核的 R1/R2 验证资产缺陷已由 [hardened](../hardened/README.md) 补齐；R3 的真实点击与修订变化后翻页已在冻结源码上重新执行。R4 采用已更正的登记预算。没有由本轮观察确认的新产品缺陷；这不表示所有来源、平台和性能边界均已验证。

G1/G2 在 [当前搜索语义](../../../docs/search-semantics.md) 中声明，并由新版探针固定当前行为：非 ASCII 大小写折叠不作保证，跨消息摘录依消息顺序取前三条。未实现 Unicode casefold 或跨消息短语加权。

## 独立探针与反向验证

最终 [v3 记录](../hardened/verification-v3/summary.json)：控制组前后各 **19/19**；8 个故意造错用例全部 exit=1 且命中预定断言，不以任意异常当作检出。来源、store、正文、状态、partial、errors、数量和 `_` 转义均受到约束。35 文件、2184 个时间戳合法；查询阶段旧缓存内容/修订及来源字节不变。

4 个验证脚本以冻结副本执行，产品源码、原始验证脚本、冻结验证脚本、实际 manifest/source-hashes 四组前后哈希均一致。另一个审查者曾在新临时目录独立复跑 v2，确认断言有效，并指出脚本绑定不足；v3 随后补齐，父任务核对所有 12 份日志哈希与结果。此处不声称 v3 再由第二审查者完整重跑。

## 运行边界

- HEAD `8969e4efbecb60544f1f02841ecfaae2f0bb7efa` 加当时未提交工作树。
- 独立实例 `127.0.0.1:8843`，运行 `/tmp/hv-search-closure-20260927/source`；合成 HOME 与缓存完全隔离。
- [源码快照](evidence/source-snapshot.json) 绑定 `app.py`、全部 `history_core/`、`audit/`、静态 HTML/JS/CSS 和 VERSION，共 42 文件；[前后比对](evidence/source-after.json) 全部一致。完整可复放源码另存于 [runtime-source.tar.gz](evidence/runtime-source.tar.gz)。
- 真 Chrome 的共享连接不可用，桌面兜底未找到可操作窗口；没有重启代理或复制登录资料。采用不需登录的 Codex in-app browser，不能据此声称用户真实 Chrome 会话已验收。
- 原 35 个合成 JSONL 不变；B2 明确新增一份 `page-25.jsonl`，B3 只移动并恢复合成 `.codex` 目录。[初始](evidence/fixture-initial-hashes.json) / [最终](evidence/fixture-final-hashes.json) 哈希保留。
- 浏览器 fixture 的 manifest 保留首次中文摘录前缀 57/56 的算术错误。本次浏览器按操作前写下的 [oracle](oracle.md) 判定，不以该旧 manifest 证明全部数据正确。最终探针在另一个新 fixture 上执行。

## 浏览器结果

| 场景 | 实际动作与判定 | 原始证据 |
| --- | --- | --- |
| B1 搜索到原文 | 搜索框提交中文“ 双千兆 ”，真实点击“打开命中原文”，进入 Codex `alpha-0001`，阅读器提示“已定位消息 4”，对应正文可见。返回后改查 `tailneedle`，链接定位消息 3。没有 force click 或脚本导航替代点击。 | [搜索](evidence/b1-search.ax.txt)、[阅读器](evidence/b1-click-reader.ax.txt)、[正文断言](evidence/b1-assertions.json)、[换词](evidence/b1-new-query.ax.txt) |
| B2 变更后翻页 | 25 会话首屏显示 20 条；向实际合成来源新增 page-25 并显式刷新索引；点击旧“加载更多结果”，出现 `index_revision_changed`，旧结果和翻页入口清除。重新搜索并点击加载更多得到 page-25…page-00 共 26 条、26 个唯一身份，顺序完整。 | [变更](evidence/b2-mutation.json)、[拒绝](evidence/b2-stale-page.ax.txt)、[清空断言](evidence/b2-stale-final-assertions.json)、[26 条断言](evidence/b2-complete-assertions.json) |
| B3 故障与恢复 | 停止本轮实例，移走合成 Codex 后以同一冻结源码和缓存重启。Claude 独有词仍返回 Claude，页面披露 Codex 不可用；Codex 独有词返回带警告的空。恢复目录并显式刷新，原 Codex 结果重现且 warning 消失；HTTP `partial=false/errors=[]`。 | [Claude 降级](evidence/b3-claude-degraded.ax.txt)、[带披露的空](evidence/b3-codex-degraded.ax.txt)、[恢复](evidence/b3-restored.ax.txt)、[HTTP](evidence/b3-restored-codex.json) |
| B4 深链修订拒绝 | 将 B1 实际链接的 source_revision 改为全零，页面明确提示索引变化，旧正文未渲染。这是额外场景，不替代 B2。 | [页面](evidence/b4-reject.ax.txt)、[断言](evidence/b4-assertions.json) |

动作时刻与 URL 见 [actions.jsonl](evidence/actions.jsonl)，关键截图在同目录。HTTP 响应只补充页面观察，不替代交互。

## 验证过程中修正的测量问题

- B2 第一次断言使用了工具不支持的 `getByRole(..., level:3)`，实际计入页面 h1/h2；第二次使用 DOM mirror 不支持的 `childElementCount` 得到 undefined。两次失败保留；最终采用已观察到的 `#searchResults` 范围内 heading/link 数量，均为零，并结合可见错误和隐藏翻页入口判定。
- 用户追加比较任务时，临时标签 3 随轮次中断关闭；重新建立标签 4 继续 B3。旧保存 helper 仍指向旧标签的一次失败没有当作产品缺陷，之后显式传入新标签完成记录。
- 独立审查指出探针初版只绑定产品源码、未绑定验证脚本。最终另轮绑定验证脚本、manifest 与源哈希，旧 v2 运行记录原样保留。

## 收尾与未覆盖项

实例 8843 已停止、临时标签已关闭、合成目录已恢复。用户现有服务未操作，见 [cleanup.json](evidence/cleanup.json)。没有提交、推送或导出真实历史。

本次仅验 Codex/Claude 合成来源与当前 Linux 路径。真实登录态 Chrome、其他原生来源、Windows/WSL、LLM 外呼、持续性能和 U1 陌生用户试用仍不在本轮证据内。原 447 Python（446 pass/1 skip）与 9 JS 是上一复核轮的结果；本轮不冒称重跑这份全量基线。

本轮补跑的是 15 项大会话检索测试 + 14 项 reuse contract 测试（共 29 项，全部通过）及全部 9 套 JS（全部通过）；`git diff --check` 通过。原始日志见 [large-search](evidence/python-large-search.log)、[reuse-contract](evidence/python-reuse-contract.log)、[JS](evidence/js-regression.json)。
