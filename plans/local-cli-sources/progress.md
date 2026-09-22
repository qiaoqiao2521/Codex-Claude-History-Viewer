# Progress

## Current
L1–L4 complete，Linux 本机 CLI 来源扩展已交付。`cchv` 已安装候选 **1.3.0-rc.2**；既有稳定发行仍为 v1.2.0。

## Done
- Web / Reader 共用 13 来源身份。CBC/OpenCode 明确接入；ZCode、Gemini、Copilot、pi/Prime、AGY/Antigravity 按独立存储归并，原有来源保留。
- 检索、会话、可验证用量、原文定位与交接按来源能力接通；别名去重，部分正文与未支持能力明确呈现。
- 真实只读核验和合成浏览器验收见 [findings](findings.md)。Python 413 项：412 通过、1 项既有外部集成跳过；7 套 JS 通过；语法与 diff 检查通过。
- 源码冻结：`eb40004d2a8d2042fba3adecab77f1a0e674fcf7`。之后仅补交付文档，不更改候选代码。
- 本地包：`work/local-cli-delivery/history-viewer-1.3.0-rc.2.zip`；SHA256 `7de6668761f0599087a786959eeb3ec07798d59fdb144554bf6a262631c0c76a`。不含真实转录、缓存、配置或本地 work 目录。
- `scripts/verify_release.py` 在干净 venv 中验包通过；现有缓存未变、HOME 未写入、升级和回滚合成计数均为 4。证据：`work/local-cli-delivery/release-verification.json`。
- 实际安装：`~/.local/share/cchv/releases/1.3.0-rc.2-eb40004`；`current` 已原子切换。旧 `releases/1.2.0-eb99792` 保留，`rollback-before-1.3.0-rc.2` 指向旧目录。
- 通过实际 `~/.local/bin/cchv` 启动隔离 demo，HTTP version 对齐上述源码，health 包含 13 来源；验收后进程停止。证据：`local-install.json`、`launcher-smoke.json`（同一交付目录）。

## Remaining
本次已授权工程工作无剩余。用户安排 U1 后再记录独立 Linux 用户试用结果。

## Issues
- AGY CLI 30 个会话中 29 个正文可读，一个旧 PB 编码未确认；桌面 Antigravity 一个摘要对应正文文件缺失。媒体与 token 计量未支持；原生库选择性片段导出保留能力限制。
- pi/Prime 已安装但本机没有历史；仅声称合成格式验收。Windows/WSL、外部模型调用、原生 resume 执行不属于本轮验收。
- U1 按用户要求 pending。上一轮候选保留本地；用户随后明确授权推送和启动验收，源码已推送 origin/main。仍未发布稳定版，无关未跟踪文件保持原样。

## Next
2026-09-22 用户要求“推送、启动，我亲自验收”：已推送源码与交付文档到 origin/main，启动已安装 1.3.0-rc.2（eb40004）并打开 `http://127.0.0.1:8787/`。真实历史模式、13 来源目录和首页 HTTP 200 已确认，服务保留运行供用户操作。启动记录位于 `~/.cache/cchv/run/acceptance-current.json`；这是本次启动观察，不是持续监控。等待用户验收反馈，不将其自动记为通过；既有 U1 独立新用户试用仍待安排。
