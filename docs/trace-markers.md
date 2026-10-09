# Skill 与 output-style 日志标记

TraceMesh 从现有 Codex、Claude 录制中提取触发标记，提供修订绑定的查询。标记写入原有消息索引元数据，不新增数据库，不修改技能内容。效果分析和技能优化属于后续调用 Agent，在技能所属仓库进行。

## 标记的证据范围

| kind / event | 原记录 | 能确认什么 |
| --- | --- | --- |
| `output_style / context_injected` | Codex system/developer 中的已知 Learning 指令；Claude `SessionStart` 的 `hook_additional_context` 或 system/developer 指令 | Learning 指令出现在记录中；提示正文哈希可比较版本。不能据此证明插件执行成功或学习有效 |
| `skill / invocation_requested` | 原生 `Skill` 工具调用与 `input.skill` | 对该技能发起了调用；用 Call ID 定位对应结果。不能把请求直接当加载成功 |
| `skill / agent_declared` | Assistant 独立输出的显式标记 | Agent 声明采用该技能；原记录位置与版本可追溯。不是工具执行证明 |

`learning-output-style` 是插件。它的上下文注入单独标记，不视为 skill 调用。安装、启用、目录列表、普通名称提及、`SKILL.md` 文件读取、教学 Insight 和用户转述不触发标记。内部推理不参与声明识别。

同一记录保留原生行号或 JSON pointer、绝对 `message_index`、时间、Call ID 和录制中的工作目录。工作目录来自当时的 context，不探测当前磁盘或推断 Git 根目录。Claude 原生 `Skill` 保留调用块编号；没有版本、路径或哈希时保留 unknown，不读取当前技能文件冒充历史版本。

## Agent 怎样留下标记

Claude 的原生 `Skill` 调用已经提供标记，不再重复声明。Codex 等没有原生调用记录时，实际采用技能后，在现有对话中输出一条独立 Assistant 消息：

```text
[[tracemesh:skill-trigger]] {"name":"example-skill","path":"/repo/skills/example/SKILL.md","version":"unknown"}
```

可选 `content_hash` 是当时所读技能正文的 SHA-256，格式为 64 位十六进制。字段只接收 `name` 或同义 `skill`、`path`、`version` 与 `content_hash`；正文上限 2,048 字符。动态字段先做最小脱敏，再限为 128 字并标记截断。不要输出原始参数、秘密或整份技能正文。

该声明只在完整独立消息中识别。代码块示例、用户消息、工具返回和带说明的混合正文不会误记为触发。跨 SessionStart 或压缩后重复注入保留各自原生定位，不合并成一次虚构调用。

## 查询与原文定位

从仓库根目录执行，来源与缓存使用已确认的本机映射：

```bash
python3 -m history_core --source codex --source-path ~/.codex/sessions --data-dir ~/.cache/cchv-reader markers --name learning-output-style --kind output_style --limit 3
python3 -m history_core --source claude --source-path ~/.claude/projects --data-dir ~/.cache/cchv-reader markers --name example-skill --kind skill --limit 3
```

首次使用或需要新录制时，先对该来源显式 `refresh`。只更新既有派生索引。旧缓存需重解析，Codex parser 为 v8，Claude 为 v6；未刷新或历史未留标记都不能解释成“从未触发”。

`HistoryReader.markers(...)` 使用相同实现，可按 `name`、`kind`、`session_id` 和 `project` 过滤。`project` 精确匹配录制中的工作目录，CLI 对应 `--project`。返回的 `index_revision` 与 search、message 共用；第二页必须附上该修订和 `next_offset`。修订变化后从第一页重查。CLI 会话过滤用 `--session`。

输出只含白名单标记与定位，不导出隐藏上下文、推理或原始工具参数。`coverage=recorded_markers_only`、`partial=true`、`uncaptured_triggers_possible=true` 明确说明捕获边界；`effect_assessment=not_performed` 明确说明未评价作用。其他来源不支持时显式报错。

后续 Agent 用标记定位会话，再通过 [message](search-semantics.md#从搜索直接展开消息) 阅读所需公开调用、返回及纠正。它可以分析前因后果，判断是否值得在原技能仓库调优；TraceMesh 本次接口不提取结论、不写反馈库、不自动调优。
