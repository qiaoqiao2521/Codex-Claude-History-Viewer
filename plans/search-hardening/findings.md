> 2026-09-27 独立复核：原报告部分结论需收窄，尤其探针假绿、fixture 时间、预算和浏览器 pass。以 [verification.md](verification.md) 的更正及新鲜复验为准；下文保留原轮记述。

# Findings — 检索链路 CapMesh 加固轮（2026-09-26）

2026-09-27 后续补证已完成：[新版验证资产](hardened/README.md)、[冻结浏览器验收](closure/report.md)。新一轮实测覆盖真实点击与索引变化后翻页，并固定 G1/G2 当前语义；以下原轮记述及其复核更正保留，不倒推原 attempt 的证据强度。

对象：HEAD `8969e4e` + 未提交检索修复（`history_core/reuse.py`、`history_core/sources.py`）。
本轮只审查与补复现证据，未修改任何产品实现文件。

## 一、已复现产品缺陷

**无。** 全部 11 个手工预期用例（含 2M 边界、尾部命中、raw fallback、字面 LIKE、中文、
跨源同 id、项目路径命中、干净零命中）在未注入版本上通过；三个故障簇的可达故障路径
均按契约表现（详见 evidence/mutation-report.md 与 evidence/browser-report.md）。

## 二、验证盲区（现有测试未覆盖、本轮已补证据）

- **V1 跨消息摘录排序**：delta-0001 上 5 条早期单词命中（索引 1–5）把 2106 处完整短语
  挤出前三（实测 snippets=[1,2,3]）。无任何测试固定该行为（既有测试只覆盖"短语消息在
  前三窗口内"的场景）。见契约缺口 G2。
- **V2 非 ASCII 大小写折叠**：`q=CAFÉ` 零命中（SQLite `lower()` 仅折叠 ASCII）。无测试
  声明该口径；`test_literal_percent_underscore_and_ascii_case_match_consistently` 只覆盖 ASCII。
- **V3 锁获取等待无界**：持有 `indexer.lock` 3 秒时，search 端到端阻塞 2.81 秒后正常返回。
  查询预算（2s deadline）在**获取锁之后**才生效，锁等待本身不受任何预算约束。无测试测量。
  无正式性能目标，故仅报告测量事实：等待上界=锁持有者时长，随后 SQL 才受预算约束。
- **V4 自动化点击路径**：结果列表周期重渲染使 Playwright 常规与 force 点击均超时；
  键盘操作与人工点击路径未在本轮验证。
- **V5 WAL 外部写锁**：对缓存库 `BEGIN EXCLUSIVE` 不阻塞读者（HTTP 层无故障表现）——
  弹性行为无测试固化，但也无故障面。

## 三、契约缺口（contract_gap，不擅自判为 Bug）

- **G1 非 ASCII 大小写**：无契约声明。影响：`CAFÉ`/`É` 类查询静默零命中。
  待决策：声明"仅 ASCII 大小写不敏感"或改用 ICU/Python 侧折叠。
- **G2 跨消息摘录排序**：`_indexed_snippets` 文档字符串只承诺"消息内短语优先"；跨消息按
  消息序取前 3 条"任一词"命中，无短语加权。影响：完整短语命中可能被更早的弱相关命中
  挤出摘录（会话级发现不受影响——score 对短语有 +4）。待决策：短语命中跨消息加权，
  或文档声明现状。
- **G3 metadata 命中的状态字符串**：`snippet_status='metadata_match_or_excerpt_unavailable'`
  未出现在任何用户侧文档；UI 以空摘录+"命中依据"文案呈现。待决策：是否需要用户可读说明。
- **G4 检索响应不携带"来源缺失"之外的部分覆盖细节**：来源缺失时 errors+partial 已达标；
  但"从未使用过的可选来源被静默跳过"（`optional_missing_source`）在检索响应中无痕迹，
  仅 health 卡片披露。代码文档已声明该取舍，属已声明契约，列出备查。

## 四、未复现怀疑与未验证范围

- 原报告"系统零命中由 2MB 截断导致"维持证伪结论（large-session-search findings）；本轮
  未再纠缠该归因，J1900 仅作过上一轮只读样本，本轮全部使用合成数据。
- 未验证：真实数据上的全源性能、多标签并发、导出链路、键盘可达性、Windows/WSL 平台。
- 证据适用性：所有结论仅适用于本文件头部所记代码状态（HEAD 8969e4e + 指定未提交修复）。
  运行环境注意：8895/8897 端口存在其他会话启动的服务（8895 现以 `--material-dir` 参数
  运行），与本轮隔离实例（8831，已停止）无关。

## 五、六个质量维度声明

| 维度 | 声明 | 具体场景 |
|---|---|---|
| correctness | covered | 合成 fixture 11 用例：会话/消息命中、绝对索引、字面词法、跨源同 id、修订拒绝 |
| data_integrity | covered | 查询前后源 JSONL SHA256 不变；旧缓存查询不写入 |
| privacy_permissions | covered | HOME 隔离 + 合成数据；真实会话/凭据未复制、未上传 |
| performance | covered（测量事实） | 锁等待 2.81s/3s 持锁；预算饥饿显式报错；无正式性能目标 |
| compatibility | covered（限定） | 旧 schema 缓存只读回填（既有测试 + M1 变体）；非 ASCII 折叠未定义（G1） |
| accessibility | not_covered | 键盘/读屏未验证；自动化点击受阻现象已记录 |

## 六、最小下一步建议

为 G2 补一条固定跨消息排序行为的回归（delta 场景），并在 oracle/README 用一句话声明
G1 的大小写口径——两者都是小时级的文档/测试工作量，能消除本轮发现的两处最可能引起
用户困惑的静默行为。

## 七、证据适用性核对（收尾时点）

轮次进行中观察到工作树被另一会话推进（`app.py`、`PROJECT.md`、`static/workspace.*` 等
新脏文件，非本轮所改；8895 端口服务已由该会话以 `--material-dir` 重启）。本轮六个作用域
文件在收尾时点的 SHA256 与 mutation 实验开始基线**逐位一致**（46b67019… / 2b70be52… /
85144ab6… / 3adc91b8… / 1ba97e26… / 854c9e27…），故上述结论对所记代码状态仍然成立；
对基线之外的文件（app.py 路由层、workspace 前端）的任何后续变化不在本报告担保范围内。
