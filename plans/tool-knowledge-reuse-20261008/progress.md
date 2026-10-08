# Progress

## Current

工程验证和知识原页更新已完成；源码待根 Codex 串行提交、普通推送并核对远端。

## Done

- 修复原生对象、JSON 封套、文本块和业务 JSON 正文；展开与折叠共用归一化。显式失败优先，深层结构有界，媒体检查基于最终显示正文。
- 正文检索排除上下文、内部思考与未分类记录；工具输入/结果和相关用户消息优先摘录，绝对消息编号保持不变。
- 增加 `search --brief`；保留来源、索引修订、展开定位及内容覆盖警告。零命中不消除未知 AGY step 的覆盖警告。
- Codex 解析版本 5 → 6；公开 reader 验证刷新旧派生缓存后恢复正文，原录制保持只读。
- 已读所有本次所涉 Git 状态和既有任务约束；保留本地原始测量、禁提交 fixture、未验收的系统恢复和独立嵌套仓库，接续入口见 findings。

## Verification

- `PYTHONPATH=tests:. python3 -B -m unittest discover -s tests -p 'test_*.py' -q`：586 项通过，1 项既有跨仓 oracle 配置跳过。
- `node tests/test_workspace.js` 通过；`node tests/test_tool_collapse.js` 18/18 通过。
- 独立审查的 JSON 正文、覆盖提示与媒体包装旁路均先复现后修复；公开 reader 合成检查与源哈希核对通过。
- 最终代码使用新派生缓存定点展开一份旧录制：12 条工具结果均保留正文，无空值或 unsupported；所选日期的源哈希不变。日期覆盖仍为 partial，不推广为全库已重新解析。
- 67 个项目 Markdown 相对链接有效；23 个知识页 wikilink 与标题锚点有效；skill `quick_validate.py` 通过；diff 检查通过。

## Knowledge closeout

状态：`updated`。根 Codex 汇总、读回并通过隔离工作树交付：

- Obsidian `Wiki/开发知识入口.md`：13 类问题路由及“历史工具检索的最短入口”，同步旧页新增触发条件与源码定位。
- `Wiki/开发协作接入.md`：“规划时”与“在已有任务进度中记录回写结果”，定义四种结果、原页读回和 pending owner。
- `Wiki/自动化开发范式与智能体协作.md`：“历史工具检索”与“解析、索引与知识回写分别验收”；保留并同步入口依赖的近期经验。
- `Wiki/浏览器自动化与登录态.md`：“后台运行与桌面占用”，整合已完成并行任务的有效经验，保留原页其他内容。

知识库普通推送：`qiaoqiao2521/my-programming-world` → `e375896fb92d652391dea226e14009b76640fbdd`。GitHub API 读回远端 main 与 4 页内容，逐页哈希匹配交付快照；主工作区历史分叉、未提交文件和嵌套 Git 原样保留。

共享 `~/.agents/AGENTS.md` 已加入有界工具查询与知识收尾规则；`tracemesh-recall` 0.4.1 已改为 `--brief --limit 3` 并读回验证。两者保留修改前备份。当前机制是 Agent 执行约定，不宣称存在运行时自动回写 Hook。

## Remaining

- 源码精确暂存、普通推送与远端读回。

## Issues

活跃录制会导致全库刷新时源变化；本次使用合成录制检验缓存迁移，并限定日期与会话进行真实读回。此前实现过程产生的临时 v6 派生缓存不是正式旧版迁移依据，最终真实检查使用新缓存。

源码与 Codex 技能入口已更新；未替换既有打包 GUI 安装，未将本轮声明为全库历史覆盖或外部应用验收。

## Next

根 Codex 提交源码并核对普通推送。历史遗留的接续 owner 和最短入口已记录在 findings；本轮知识回写状态为 updated。
