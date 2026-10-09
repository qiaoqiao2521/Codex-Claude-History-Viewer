# Progress

## Current

2026-10-10：代码、公共 CLI/Python 接口、原页修订和读回已验证；根 Codex 正在普通提交推送与远端核对。下文 2026-10-08 的验证保留为前轮事实。

## 2026-10-10 Recheck

- 修复 brief 候选排序、完整短正文、有界 Call ID 输入/结果关联及独立错误状态；默认 search 排序保持兼容。
- `message` 用 search 的同一修订直接分页展开；完整选中消息先识别秘密范围再输出等长遮罩窗口，空字符与长 Call ID 边界已验证。
- 修复内层失败被外层元数据覆盖、stdout 误判退出码、原生业务 JSON 丢字段与畸形 Call ID 崩溃；正式旧缓存公开刷新恢复正文及状态。
- 按用户最终确认新增 `markers`：Learning 指令注入、原生 Skill 请求、Agent 声明分别标记；按名称、会话与录制工作目录查定位，不取隐藏正文、不新建表或反馈数据库、不评价作用。
- Codex parser v8、Claude v6；公开刷新恢复旧缓存标记。Claude 混合 hook 内容逐元素定位，Codex 缺失新 turn ID 不沿用旧值。
- 误扩的新 skill 草稿已从默认库撤出；没有安装、helper 或反馈数据库。现有 tracemesh-recall 正文恢复 0.4.1。共享 AGENTS 只增加用户确认的日志标记约定，Claude/Codex 原有入口均使用它。

## 2026-10-10 Verification

- `PYTHONPATH=tests:. python3 -B -m unittest discover -s tests -p 'test_*.py' -q`：649 项通过，1 项既有跨仓 reader 配置跳过。
- workspace JS、tool-collapse 18/18 与 diff 检查通过。76 个受影响项目 Markdown 相对链接、28 个知识页 wikilink/锚点通过。
- 独立审查报告的解析、分页脱敏、巨大 Call ID 和两处 marker 归因缺陷均先复现后修复，公共 Reader/CLI 回归通过；源录制字节保持只读。
- 所选当前 Codex 录制读回 4 个 Learning 注入标记与 1 个 Agent 声明。第一次活跃文件前后哈希不稳定；后续有界核对源字节不变，不推广为全库捕获。

## 2026-10-10 Knowledge closeout

状态：`updated`。根 Codex 串行修订 canonical 原页，并将本轮 delta 应用到 fresh origin/main 的隔离工作树。4 页已实际读回，28 个链接/锚点已核对，交付哈希留在本机缓存。

- `Wiki/开发知识入口.md`：工具配对、直接消息展开及技能/插件日志标记路由；浏览器入口同步插件优先。
- `Wiki/开发协作接入.md`：“规划时”一次有界查询四项；“执行中”现有对话标记与后续 Agent 的职责。
- `Wiki/自动化开发范式与智能体协作.md`：“历史工具检索”“技能触发日志”“解析、索引与知识回写分别验收”；保留原有主题。
- `Wiki/浏览器自动化与登录态.md`：“后台运行与桌面占用”仅修订入口次序，没有执行账号操作。
- 四态、pending owner 与原页读回约定为 `already_covered`，没有重复改写。

交付状态暂为 `pending`：代码及4页已验证，普通 push 与远端内容核对由根 Codex 完成。原知识主工作区分叉及其它进行中主题保留，详见 findings。

## 2026-10-08 Done

- 修复原生对象、JSON 封套、文本块和业务 JSON 正文；展开与折叠共用归一化。显式失败优先，深层结构有界，媒体检查基于最终显示正文。
- 正文检索排除上下文、内部思考与未分类记录；工具输入/结果和相关用户消息优先摘录，绝对消息编号保持不变。
- 增加 `search --brief`；保留来源、索引修订、展开定位及内容覆盖警告。零命中不消除未知 AGY step 的覆盖警告。
- Codex 解析版本 5 → 6；公开 reader 验证刷新旧派生缓存后恢复正文，原录制保持只读。
- 已读所有本次所涉 Git 状态和既有任务约束；保留本地原始测量、禁提交 fixture、未验收的系统恢复和独立嵌套仓库，接续入口见 findings。

## 2026-10-08 Verification

- `PYTHONPATH=tests:. python3 -B -m unittest discover -s tests -p 'test_*.py' -q`：586 项通过，1 项既有跨仓 oracle 配置跳过。
- `node tests/test_workspace.js` 通过；`node tests/test_tool_collapse.js` 18/18 通过。
- 独立审查的 JSON 正文、覆盖提示与媒体包装旁路均先复现后修复；公开 reader 合成检查与源哈希核对通过。
- 最终代码使用新派生缓存定点展开一份旧录制：12 条工具结果均保留正文，无空值或 unsupported；所选日期的源哈希不变。日期覆盖仍为 partial，不推广为全库已重新解析。
- 67 个项目 Markdown 相对链接有效；23 个知识页 wikilink 与标题锚点有效；skill `quick_validate.py` 通过；diff 检查通过。

## 2026-10-08 Knowledge closeout

状态：`updated`。根 Codex 汇总、读回并通过隔离工作树交付：

- Obsidian `Wiki/开发知识入口.md`：13 类问题路由及“历史工具检索的最短入口”，同步旧页新增触发条件与源码定位。
- `Wiki/开发协作接入.md`：“规划时”与“在已有任务进度中记录回写结果”，定义四种结果、原页读回和 pending owner。
- `Wiki/自动化开发范式与智能体协作.md`：“历史工具检索”与“解析、索引与知识回写分别验收”；保留并同步入口依赖的近期经验。
- `Wiki/浏览器自动化与登录态.md`：“后台运行与桌面占用”，整合已完成并行任务的有效经验，保留原页其他内容。

知识库普通推送：`qiaoqiao2521/my-programming-world` → `e375896fb92d652391dea226e14009b76640fbdd`。GitHub API 读回远端 main 与 4 页内容，逐页哈希匹配交付快照；主工作区历史分叉、未提交文件和嵌套 Git 原样保留。

共享 `~/.agents/AGENTS.md` 已加入有界工具查询与知识收尾规则；`tracemesh-recall` 0.4.1 已改为 `--brief --limit 3` 并读回验证。两者保留修改前备份。当前机制是 Agent 执行约定，不宣称存在运行时自动回写 Hook。

## Remaining

本轮代码与知识验证已完成。剩余为普通提交推送与远端读回，owner：根 Codex。既有本地材料恢复入口见 findings。

## 2026-10-08 Delivery

源码成果提交：`2f8328630459495399ce481eb38629d935ca318e`，已普通推送到 `qiaoqiao2521/Codex-Claude-History-Viewer` 的 main。GitHub API 读回 main SHA 与本地提交一致。仅暂存本轮 19 个已审阅文件；原始历史、运行日志、本地测量与禁提交 fixture 没有入库。

知识库远端提交和 4 页内容哈希已在 Knowledge closeout 分别核对。共享规则与 skill 属于本机文件，保留修改前备份。此后仅追加本任务的完成记录，不改变已验证代码。

## Issues

活跃录制会导致全库刷新时源变化；本次使用合成录制检验缓存迁移，并限定日期与会话进行真实读回。此前实现过程产生的临时 v6 派生缓存不是正式旧版迁移依据，最终真实检查使用新缓存。

源码与 Codex 技能入口已更新；未替换既有打包 GUI 安装，未将本轮声明为全库历史覆盖或外部应用验收。

## Next

根 Codex 完成普通推送后记录远端修订及4页内容核对。以后从 `search --brief` 或 `markers` 进入；标记记录事件，后续 Agent 再判断效果并在原技能仓库调优。
