> 2026-09-27：已独立复核，预算实际登记 1/3，浏览器点击/翻页仍未验证；详见 [verification.md](verification.md)。原实验记录不倒填。

# Progress

## 最新补证 — 2026-09-27

已完成剩余验证资产与浏览器链路，见 [closure/report.md](closure/report.md) 及 [hardened/README.md](hardened/README.md)。真实点击、实际索引变化后旧分页拒绝/重新拉全 26 条、来源降级/恢复、过期深链拒绝均在 42 文件冻结源码上完成。临时服务已停，原实验各 1/3 不变，下文是之前的阶段记录，不用新证据倒填旧 attempt。

G1/G2 已写入 [当前搜索语义](../../docs/search-semantics.md)，固定现状而未改检索实现；U1 于 2026-10-01 取消。

## Current

M1 复审轮完成并经独立复核：mutation（exp-29b20283…，conclusion=detected）与 browser
（exp-c0a251b7…，原判 pass，已按 R3 收窄口径）两实验各登记 **1/3 attempts**；
findings.md 交付缺陷报告与六维度声明。两轮均未改产品实现与既有 tests/。

## Done

- 事实边界确认：HEAD 8969e4e；未提交修复=history_core/reuse.py+sources.py（哈希入实验基线）；
  8787 无监听、8895 为其他会话服务、本轮隔离实例 8831（已停止）。
- oracle.md：九不变量 + 手工预期表（先于实现探测成文；日期误写 09-06，实验实际
  2026-09-26 UTC——文件已绑定实验哈希不倒填，以本条为准）。
- 合成 fixture + manifest；簇 A/B/C 有限实验：A-p1~p5（G1/G2 缺口证据）、B-p1/p2redo
  （修订=索引修订，cursor 语义正确）、C-p1（锁等待测量）/C-p2（预算饥饿显式）。
- mutation M1/M2/M3 三个忠实变体被责任测试检出——复核轮在新隔离副本上**新鲜复验**成立；
  首次 M1 植入 invalid 重做；每次恢复后聚焦责任测试全绿（恢复后全量复跑仅首轮做过，
  不逐变体宣称）。
- browser B1/B2/B3 时点观察成立但按 R3 收窄（见下）；两次无效注入（pkill 自匹配、
  WAL 锁不可达）如实记录。
- 复核轮当前基线：**447 Python（446 通过 1 跳过）+ 9 套 JS**（437 是旧轮基线，不再引用）。

## 更正（按 verification.md R1–R4 采纳）

- **R1 探针假绿**：probe.py 只比会话 id 集合、不消费 manifest source、不核对 store_id/
  摘录正文，errors/partial 仅零命中场景断言——篡改来源身份/正文/状态仍 11/11 PASS。
  探针只作冒烟证据；I1/I3/I6 的独立成立以产品既有测试与复核轮为准，I5 未被探针证明。
- **R2 归档 fixture 时间戳错误**：归档 fixture_v2.py 生成 1011 个非法时间戳，短语实际
  绝对索引 1010（摘录已含短语），clusters2 硬编码 2106 的 EXCLUDED 输出不能证明所述场景；
  修正时间后短语索引 2106、摘录 [1,2,3]，**G2 结论成立但归档脚本不可原样复放**。归档脚本
  按原样保留作诚实记录，修正复放在 evidence/verification-oracle/。
- **R3 浏览器结论收窄**：location.href 导航只证明深链目标/阅读器定位，不证明点击通过
  （"周期重渲染"归因未独立确认）；全零 source_revision 拒绝 ≠ "索引变化后翻页"（后者仅有
  API 层证据）；browser scope 未含 app.py/reader.py/workspace.js/app.js；B2 只有 Markdown
  记述、无原始 HTTP/DOM 产物，本轮未重跑、不升级证据强度。
- **R4 预算口径**：两份实验各登记 **1/3 attempts**（一个登记 attempt 内含三个有效变体
  与一个 invalid 植入），不存在"3/3 已用尽"。

## Remaining

- 本轮验证修补已完成；细节和工具测量修正见最新补证。
- 当前语义已声明；Unicode 全面折叠与跨消息短语加权未纳入本轮。
- 源码交付按用户当前提交推送授权处理；U1 已取消，未执行的试用不计通过。

## Issues

- 无阻断。工作树由多会话并行推进（本轮期间 app.py、workspace.* 等出现非本轮改动）；
  作用域六文件哈希经复核轮确认仍与实验基线一致。

## 2026-09-28 提交收口

本提交固定全文检索依赖修复、回归测试及加固补证。历史实验/绑定报告保持原样，1/3 attempt 口径不变；证据只对记录的源码快照有效，不自动覆盖后续功能与改名。
