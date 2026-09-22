# Findings

- 本机 PATH 有 Codex、Claude Code、OpenCode、CodeBuddy/cbc、Gemini CLI、pi、Copilot snap 入口及若干包装器。
- `cbc` 指向 `@tencent-ai/codebuddy-code/bin/codebuddy`。
- OpenCode 已有只读 SQLite 适配器；新需求包括核验实际本机发现路径与读取结果。
- 完整命令/存储盘点见 [inventory-extra.md](inventory-extra.md)。命令别名按同一存储归并，不按命令数量假定来源数量。
- OpenCode 本机原生库：188 会话，4,668 消息，18,251 parts；公开 Reader 的读取与交接已只读通过。
- CodeBuddy 18 主会话、2,672 展示记录，total 134,201,786 / cached 128,960,512。原生 input 已含 cache，按 providerData.messageId 去重；17 个 agent-* 文件携父会话 ID，排除以免覆盖。
- ZCode 本机独立库：55 会话、6,916 消息、25,898 parts。session 无 OpenCode 的用量列，使用连接内 TEMP VIEW 从 message 聚合，主库只读；按 sequence 排序。真实 5,895 条显式 total 都等于 input+output，cache 是输入分项。
- Gemini 0.59.0 当前 JSONL，同时支持旧 JSON；升级并存时优先同名 JSONL。$set/$rewindTo 与同 ID 更新先物化再计量。projectHash 不是 cwd。
- pi 0.73.1 和 Prime 0.9.4 兼容树形 JSONL，默认历史目录均未找到。合成测试通过；保留分支提示，继承 parentSession 的用量未知，整体完成状态不推断。
- Copilot Snap 1.0.83：2 个 events.jsonl 可读会话 / 13 展示记录；另一个仅有目录无 transcript，不能计为恢复正文。usage 未验证语义，保留未知。
- 默认未安装/尚无历史的来源不能阻止全部来源分页；显式错误路径、曾成功后丢失和旧缓存仍有数据时必须继续报告失败。
- 本机 cchv 指向旧稳定 1.2.0；本轮完成后安装独立候选目录并保留可回退入口，不公开发布稳定版。

## Implementation and acceptance

- 13 provider identities share Web/Reader discovery; CBC command aliases share one source. TeamAI/Codex Web GPT have no verified separate native transcript store; CM/Orca coordination logs are recorded in the inventory, not duplicated as provider sessions.
- AGY CLI: 30 sessions, 29 decoded text/thinking/tool records (9,443 steps, 10,340 displayed records), one old 132,959-byte PB remains metadata-only. Desktop Antigravity: one summary, original conversation file missing. Counters are dated local observations. Verified installed descriptors, not guessed binary strings, define the decoder.
- Actual read-only checks: OpenCode Reader search/handoff passed; CBC/Gemini/Copilot parsers and selected small-session handoffs passed in temporary caches with source hashes unchanged; ZCode source DB hash unchanged; AGY CLI and desktop DB/WAL/SHM hashes unchanged. No private transcripts were saved in the repository or candidate. pi/Prime have no local history, so only synthetic acceptance is claimed.
- Independent review fixed ZCode project aggregation querying the wrong table. Trailing tool failure also exposed an audit outcome bug: later meaningful activity now revokes an earlier final answer; AUDIT_VERSION 4 invalidates old cached classifications.
- Browser (Chrome, synthetic-only localhost:8794): cross-source search; CBC source/deep-link + validated resume command; Gemini JSON Pointer raw record and selected handoff; AGY decoded search/message jump + partial coverage and legacy metadata notice; ZCode sequence order and explicit tail-failure `incomplete`. Server and task tab stopped after acceptance.
- Integration tests cover actual app startup with fake HOME, all default stores, missing optional histories, explicit bad paths, source mutation/revision rejection, metadata/partial pagination, demo isolation and unchanged source bytes. AGY actual I/O budgets include summary DB/WAL and conversations; over-limit reads fail explicitly.
- Final regression: `python3 -m unittest discover -s tests -q` ran 413 tests in 11.327s, 412 passed / 1 existing external integration skipped; all 7 `tests/test_*.js` suites passed. Python compileall, both JS syntax checks and `git diff --check` passed.
