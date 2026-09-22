# U1 组织与判定说明

状态：**pending**。此文件是试用准备材料，不是验收结果。至少一名未参与开发的人独立完成五任务后才能填写 U1 结论；自动化、开发者演示、材料检查均不能替代。

候选源码 commit：`0bb034bd25c7ab6d2677d241dc087eb15313638b`；VERSION：`1.3.0-rc.1`；试用包 SHA-256：`1fb62066b96a19738eee835c61d162c8405cb62915b0996d1412f126718adfba`。包位置见 [交付记录](../progress.md)。2026-09-22 材料预检与干净安装通过，U1 未运行。浏览器/Python/Linux 仍由实际参与者填写；不宣称 Windows/WSL 或真实模型能力。

## 制作合成候选包

先冻结待试用 commit，确认已包含本轮实现、`scripts/build_reuse_trial.py`、`scripts/reuse_fixture.py`、固定题集和本任务单；不要从旧版 tag 打包。把下列占位符替换成最终候选 commit，在仓库根目录执行单条命令：

```bash
python3 scripts/build_reuse_trial.py --revision 0bb034b --output /tmp/hv-u1-candidate.zip
```

脚本只从指定 commit 的受控源码清单打包，运行该提交中的题集生成器，再叠加两个文件工具会话。固定 E0 数据不修改；原始 demo 被全合成的 12 会话替换（Codex 6、Claude 6、3 个完整项目路径）。Claude 成功的 tool_result 显式记录 `is_error: false`；Codex 保留写入失败与测试失败。构建脚本本身必须与候选提交一致，输出已存在则拒绝覆盖。

产出三个文件：`hv-u1-candidate.zip`、`hv-u1-candidate.sha256`、`hv-u1-candidate.manifest.json`。外部 manifest 自动记录实际 commit、VERSION、ZIP SHA-256、逐文件摘要及 `U1 pending`。ZIP 内 `BUILD_INFO.json` 绑定实际运行身份与各文件摘要；`demo/u1-manifest.json` 记录 12 个 JSONL 摘要和原 E0 数据摘要；`TRIAL_TASKS.md` 自动写入代码提交并指向外部校验文件。归档自身摘要放在外部，不能把自引用摘要写进归档。

这是一份带合成 demo 覆盖层的定制候选包，不是未经修改的正式 Release。原日志、HOME、索引缓存、开发工作区 `work/` 和本 observer 答案均不加入归档；构建本身也不证明产品体验通过。

冻结提交前如需根任务浏览器材料检查，可调用 `scripts.build_reuse_trial.prepare_demo(target_root)` 创建独立的 12 会话目录；该函数拒绝覆盖非空目录，只能算工作树材料预检，不能用它的结果冒充候选归档身份。

组织者解压最终 ZIP 后，按 `TRIAL_TASKS.md` 启动 `--demo`，确认只出现 Codex 6 / Claude 6、3 个完整项目路径，且未读取 OpenCode/Hermes 私人库；验证五任务所需材料可见。记录为 **material_preflight**，包含实际候选身份、环境、日期与观察结果。不要重新打包带运行缓存的解压目录；构建产物保持不变。脚本默认 `material_preflight: not_run`，预检证据单独记录，不能自动关闭 U1。

## 观察规则

- 给参与者 `tasks.md`、候选包和 README，不展示本答案，不演示点击路径。
- 启动说明可以读；观察者不得逐步引导。求助必须记录原话、提示内容和次数，需提示才完成的任务单列 `assisted`。
- 任务 1 从读到启动说明开始计时；任务 2 从确认索引就绪并交付题目时计时；任务 5 从开始选取到导出后打开核对完毕。浏览器加载等待属于耗时，不能扣除；环境安装故障单列原因。
- 任务 3/4 无冻结时间上限，记录实际值，不在看完结果后增删门槛。保留原题与失败步骤。
- 仅保存必要的合成证据定位与反馈。邀请、分享和人员安排由用户执行，不自动发送任何材料。

## 判定参考（不给参与者看）

| 任务 | 最小正确结果 | 不能算通过的情况 |
|---|---|---|
| 1 | 看见合成数据；Codex 6、Claude 6；能分清未配置/不可用与成功零结果；提示可执行 | 只因首页 HTTP 200 即判通过，或看到私人历史 |
| 2 | `linux / codex / shared-repair-01 / message_index=4`，原文为 SQLite 锁错误、短事务、等待 reader 释放；与同 ID Claude 记录分开 | 只找对标题、未到原文；把建议说成当前已验证 |
| 3 | `/synthetic/beta/repo` 与 `/synthetic/alpha/repo` 分开；最近是 Claude `trial-file-fixed`；其 `tests/test_a.py` 成功不证明 `reuse-beta-03` 的 worker 超时解决 | 把两个 repo 合并；根据较晚成功自动清除早先无关失败 |
| 4 | 同项目 `src/a.py` 至少出现 Codex `trial-file-failed` 和 Claude `trial-file-fixed`；前者写入失败/测试失败，后者工具编辑与历史测试成功；当前文件状态未知，完整 patch 缺失可明确提示 | 把失败工具标成成功修改；凭历史记录宣称当前磁盘文件正确；伪造完整 diff |
| 5 | 所选至少两来源，目标片段均出现，未选的长填充正文不混入；Markdown/JSON可打开，来源/store/会话/消息/修订或未知一致；材料仅为上下文 | 导出全会话代替所选；把复制成功称为接收者已采纳/已执行 |

消息序号按现有索引从 0 开始。store_id 是配置来源绝对根路径的内容摘要，换机器或解压路径时会变化；应核对来源绑定一致，不能硬编码 `linux` 为 store_id。trial-file-* 的证据 raw_ref/消息序号以当前候选界面与生成 JSONL 对照记录，避免工具结果折叠后的显示序号与原始行号混用。

## 记录模板与关闭条件

| 字段 | 记录 |
|---|---|
| 候选代码 commit / VERSION / 试用包 SHA-256 | 待填 |
| u1-manifest 摘要 / 解压目录是否干净 | 待填 |
| material_preflight 日期 / 人员 / 结果 | 未执行 |
| 独立试用者匿名编号 / 未参与开发确认 | 待用户安排 |
| Linux / Python / 浏览器 | 待填 |
| T1 秒数 / T2 秒数 / T3 秒数 / T4 秒数 / T5 秒数 | 未运行 |
| 各任务求助次数和逐条提示 | 未运行 |
| 正确的来源、会话、消息定位及导出文件名 | 未运行 |
| 失败原文 / 阻断步骤 / 修复后复测 | 未运行 |
| U1 结论及理由 | pending |

每任务记录 `independent_pass / assisted / failed / skipped`。T1 ≤300s、T2 ≤60s、T5 ≤120s 是计划冻结的目标；未达标保留结果并处理实际阻断，不修改题目或阈值。材料准备完成、自动 API 测试成功不关闭 U1。一次参与者通过仅构成本轮最小可用性证据，不证明普遍适用。
