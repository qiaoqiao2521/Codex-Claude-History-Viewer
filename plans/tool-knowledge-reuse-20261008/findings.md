# Findings

- 采用现有知识页关于按实际调用入口验证的经验：归一化纯函数、公开 reader 和缓存迁移分别核对。来源：Obsidian `Wiki/自动化开发范式与智能体协作.md`。
- Codex 工具结果渲染及摘要只处理字符串；同一人工对象直接输入会丢正文，序列化为 JSON 字符串后可读。审计提取器已有对象/列表支持，阅读器能力不一致。
- 会话级 AND 与最早三条任一词摘录不是同一条有效工具经验；内部推理参与旧全文召回。
- 原知识入口只有宽主题；旧协作规则仅要求新页补入口，旧页新增经验缺少发现性维护。
- 知识库已有近期经验，不能将索引缺口概括成完全未更新；索引刷新不代表原页已写入。

## Protected prior work

- `plans/daily-activity/` 未跟踪测量、基线和原始定位：已有计划明确仅本地保留；不上传。源码及公开验收文件已在 Git。
- `plans/search-hardening/*.lock`：本地实验锁，保留，不入 Git。
- `plans/specmesh-r001-validation/`：已读当前计划，验证完成但明确“不提交实验 fixture 或 Harness 产物”；保留其本地证据和嵌套测试 Git。无需为知识维护重测设备。
- `plans/ubuntu-keyboard-recovery/`：进度中混有两个日期的恢复段，真实输入验收与 USB I/O 收尾没有当前确认；保留原文件。接续 owner：根 Codex；从 `task_plan.md` 的输入验证和现有 `progress.md` 判断对应日期，不自动重做系统或磁盘操作。
- `agents/controlmesh_typescript_migration_plan(1)..md`：已读迁移结论和证据边界，仍引用旧账户的公开仓库与未完成的本地审计；不能作为已验收实现交付。接续 owner：根 Codex；在对应 ControlMesh 当前计划核对本地源码和适用范围后整理。
- Obsidian 的嵌套 `编程/SpecMesh/`、公众号目录保持独立 Git 边界；其他已有主题修改先审阅，不盲目暂存。
- Obsidian 的既有视频路线与 ROS 2 项目地图已查目录、来源和验收边界；涉及更广项目历史与同时进行的机器人任务，保留当前主工作区。接续 owner：根 Codex；先核对对应媒体/ROS 2 项目已有计划及这四页的引用，不为整理笔记重跑实体环境。当前任务仅隔离交付已核实的开发知识、入口与后台浏览器经验。
