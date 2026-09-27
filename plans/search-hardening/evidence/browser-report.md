# Browser 实验报告 — 检索链路专项 QA（exp-c0a251b7c92847ac24ad5f43）

日期：2026-09-26（UTC）。服务：`HOME=/tmp/cchv-hardening/home python3 app.py --data-dir
/tmp/cchv-hardening/webcache --port 8831`（隔离端口；HOME 隔离使 agy/antigravity 指向 fixture
home 且 not_found，真实私有历史未注册）。fixture v2 全合成。UI 为 1.3.0-rc.3 工作树。

## B1 正常链路 — pass

- target_operation：检索"双千兆" → 摘录 → 打开命中原文 → 返回 → 换查询 `tailneedle`。
- oracle（oracle.md 手工预期）：alpha-0001 命中、摘录正文"在双千兆网卡上验证 OpenWrt 前先核对
  驱动"、深链 `message=4`；ctx 消息（索引 2）不得出现在结果；换词后深链 `message=3`。
- 观测（DOM 快照 + /api/reuse/search 交叉核对）：
  - 搜索页：`已显示 1 个结果`，结果卡摘录与 API snippets[message_index=4] 一致，深链携带
    `source_revision=43cf55…`；ctx 未混入。
  - 阅读页：状态"检索：双千兆 · 已定位消息 4"，消息 4 正文可见（消息头时间戳 18:00:05 与
    fixture 构造一致）；消息 3（tailneedle 长消息）在其上方。
  - 返回后换查询 `tailneedle`：1 结果、深链 `message=3`、`message=2`（ctx）未出现。
- 自动化备注：结果列表周期性重渲染使 Playwright 常规/force 点击均超时，跳转改用快照中
  已证实的链接 href（`location.href`）完成；人工点击不受影响的风险未在本轮覆盖。

## B2 来源故障与恢复 — pass（fault_hit + recovery）

- 注入：停止服务（按 PID）→ 将 `/tmp/cchv-hardening/home/.codex` 移走 → 重启。
  首次注入尝试因 pkill 模式自匹配中止、目录未移走，判 invalid 并重做（同一次尝试内）。
- fault_hit：health 明确 `codex | not_found | source_not_found`；搜索 claudedistinct 返回
  claude 结果且 `errors=[{codex, source_unavailable}], partial=true`；搜索 codex 独有词
  返回空但 **errors 非空 + partial=true**——不是误导性干净零命中。
- 放回目录（未刷新）：仍为空——显式刷新策略一致（freshness: unknown 有声明）。
- recovery：`POST /api/reuse/refresh {system:linux, source:codex}` → `{"status":"refreshed"}`；
  重搜"双千兆"恢复 `[codex alpha-0001], partial=false`。
- 不可达故障记录：外部 `BEGIN EXCLUSIVE` 持锁对 WAL 库不阻塞读者，HTTP 层无故障表现
  （弹性设计）；预算饥饿路径已在 API/单测层证明显式报错（见 mutation 报告 C-p2 与既有测试）。

## B3 修订变化提示 — pass

- 注入：以全零 `source_revision` 打开同一深链。
- 观测：阅读页显示"索引已变化，请重新选择当前项目以刷新会话。检索消息请返回检索页重新定位."，
  目标消息正文**未**渲染（不展示过期内容）。

## no_new_regression 依据

浏览器阶段未改动任何产品文件；实验前全量 437 Python（1 skip）+ 9 套 JS 通过，独立探针
11/11 PASS，源 fixture SHA256 前后一致（probe.py 内置校验）。

## 范围声明

- 未覆盖：键盘可达性、窄窗口/六主题视觉、导出（交接证据）链路、真实用户点击路径、
  并发多标签。8895/8897 为其他会话启动的服务（8895 现携带 `--material-dir` 参数运行），
  本轮未触碰。
