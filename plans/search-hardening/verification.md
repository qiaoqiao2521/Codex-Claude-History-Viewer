# 独立复核（2026-09-27）

## 结论
上一轮报告**部分成立，需要更正验收口径**。当前未新增已复现产品缺陷；三个忠实变体确实被既有责任测试检出。但 11/11 探针存在可复现假绿，归档 fixture 有时间戳错误，“3/3 预算已用尽”和浏览器完整闭环 pass 无法由记录支持。

仅核验上一轮报告及补复现材料，未修改产品实现或既有 tests/。原实验 JSON 与已绑定报告保留，不倒填 begin/finish。未停止、重启或操作用户服务，本轮没有复跑浏览器。

## Checklist
- [x] 阅读 CapMesh 规范、仓库约定与实验报告。
- [x] 检查实验记录、哈希与预算口径。
- [x] 独立复跑责任测试与三个忠实变体。
- [x] 检查 fixture/oracle/探针的可重放性及假绿风险。
- [x] 收敛已确认、需更正与未验证结论。

## 需要更正的证据问题

### R1 — 原探针可以假绿（P2）
`evidence/probe.py:47-58` 只比较 session id 集合，不消费 manifest 的 source，也不核对 store_id、摘录正文。errors/partial 仅在特定零命中场景断言；metadata snippet_status 只是打印。隔离进程同时篡改返回来源/存储身份、摘录正文、partial/errors 和 metadata 状态，仍 11/11 PASS。去掉 `_` 转义也仍通过，因为 fixture 缺少对应干扰反例。不能据此宣称 I1/I3/I6 全部独立成立；产品既有测试有更强断言，不能外推为产品真的串源。

I5 同样未被这个探针证明：每个 case 都 scan，且只比较源 JSONL 哈希，没有查询前后旧缓存内容快照。

### R2 — 归档 fixture 的时间修复未落盘（P2）
`fixture_v2.py:14-16` 把秒数直接折成分钟，生成 1011 个非法时间戳（10:60:00 到 10:77:00）。归档版本完整短语实际绝对索引 1010，摘录为 [1010,1012,1013]，已包含短语；clusters2 却硬编码检查 2106 并打印 EXCLUDED，且不以错误码失败。

仅修正隔离副本为 datetime+timedelta 后，短语索引才是 2106，摘录 [1,2,3]，G2 确实复现。结论与复放材料要分开：G2 有事实基础，归档脚本不能原样证明报告所述场景。

### R3 — 浏览器 pass 超出证据（P2）
- B1 普通及 force 点击失败后改用 location.href 导航；证明深链目标/阅读器定位，不证明点击操作通过。点击失败的原因“周期重渲染”仍只是原报告归因，未独立确认。
- 原 oracle B3 为“索引变化后翻页”，实际 B3 为全零 source_revision 深链拒绝；两者是不同场景。直接 API cursor 验证不能替代浏览器翻页操作。
- browser scope 未包含 app.py、reader.py、workspace.js、app.js 等真正影响结果的文件。运行中这些文件曾变动；六项哈希一致仅支持被记录的范围，不支持整条浏览器链路稳定。
- B2 故障/恢复叙述符合判定要求，但持久 artifacts 只有 Markdown 记述，没有原始 HTTP、DOM 或截图。本次未重跑 B2，不升级其证据强度。

应将旧 browser pass 收窄为“已有深链/故障恢复的时点观察，真实点击与浏览器翻页变更未验证”。

### R4 — 预算与摘要统计不一致（P2/P3）
两份 JSON 均只有一条 attempt；CapMesh show 的 used_attempts=1，budget.attempts=3。mutation 是一个登记 attempt 内三个有效变体及一个 invalid 植入，不是已登记 3/3，更不是 budget exhausted。不事后倒填记录。

总述称 3 处盲区，findings 列 V1–V5；G1/G2 是主要待决策项，另有 G3 说明缺口及 G4 已声明取舍。oracle 日期写 09-06，实际实验时间为 09-26 UTC；六维度 JSON 和 findings 口径也不一致。原始日志/patch 未完整绑定，不能用结构校验代替这些执行证据。

## 本次新鲜复验

- HEAD 8969e4efbecb60544f1f02841ecfaae2f0bb7efa；两份实验六个 scope 文件及报告哈希仍匹配。
- 当前工作树全量 Python：447 tests，446 通过 / 1 跳过；9 套 JS 通过。437 是旧轮基线，不应当成当前测试数。本次全量耗时 760.218 秒，不作为正常性能基线或性能承诺。
- 新隔离副本 M1：raw-fallback 召回断言失败，另一个依赖命中的测试出现 IndexError；检出依据是前者的真实缺失断言，不把任意红测试算检出。
- M2：短语摘录不含 `alpha beta actual phrase`，对应断言失败。
- M3：查询异常被吞后责任断言失败。
- 每个变体恢复后，三个聚焦责任测试全绿；未重复宣称本次每次恢复都跑了全量447。
- G1 `CAFÉ` 零命中、修正 fixture 时间后的 G2、扫描后的旧 cursor 拒绝均重新确认。没有新增产品缺陷定性。

原始 patch、命令、失败断言、恢复日志及作用域哈希见 [verification-mutations](evidence/verification-mutations/)。复跑入口：[verify_mutations.py](evidence/verify_mutations.py)，参数为仓库根和一个**不存在**的新输出目录。产物只在隔离副本内改代码。

探针假绿、归档/修正 fixture 对照的原始输出与复放入口见 [verification-oracle](evidence/verification-oracle/README.md)。该目录只保存脚本和小型日志；按说明复制到新的临时目录运行，不向仓库写入大体积 fixture 或缓存。

## 本次执行错误与边界
第一次隔离完整责任测试 120 秒超时（不算 detected）；后收窄到能直接击中机制的三个责任测试。第二次 M3 发现同一字符串在两个函数出现，锚点拒绝执行；最终限定 search 函数后成功。原目录均保留，不抹掉失败尝试。当前全量日志位于被忽略的 work/search-hardening-verification/。

采用知识页 `Obsidian/Wiki/自动化开发范式与智能体协作.md#按当前任务选择验收依据`：区分静态检查、实际交互与交付位置；本次据此不以新测试通过倒推旧浏览器点击通过。经验已在该页表达，不另建卡、不重复写项目进度到知识库。

## 最小下一步
先修补**验证资产**：参数化 fixture 路径、修正时间、按完整来源身份和正文/状态增加断言、补 literal 负例；绑定完整浏览器源码快照，再验证真实点击与翻页。当前没有授权扩大产品行为，G1/G2 的产品决策继续保留。
