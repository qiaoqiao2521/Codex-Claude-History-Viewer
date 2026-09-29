# Linux local CLI sources

The Web and `python3 -m history_core` share provider identities, filters and parsers in `history_core/providers.py`. CLI aliases do not create duplicate sources. All new provider stores are read-only; derived file indexes stay in the Viewer data directory and AGY derived indexes are in memory.

| Source | Default input | Explicit Web option | Notes |
|---|---|---|---|
| CodeBuddy / `cbc` | `~/.codebuddy/projects/**/*.jsonl` | `--codebuddy-dir` / `--cbc-dir` | Native CodeBuddy envelopes; excludes parent-ID `agent-*` sidecars; message usage dedup |
| Gemini CLI | `~/.gemini/tmp/*/chats/` | `--gemini-dir` | JSONL and legacy JSON, including child-agent recordings; prefer migrated JSONL over same-name JSON |
| pi | `~/.pi/agent/sessions/` | `--pi-dir`, `--pi-sessions-dir` | v1–v3 tree entries, branch annotations; inherited fork usage remains unknown |
| Prime Agent | `~/.prime/agent/sessions/` | `--prime-dir`, `--prime-sessions-dir` | pi-family parser, separate identity and cache |
| GitHub Copilot | `~/.copilot/session-state/` | `--copilot-dir` | Falls back to `~/snap/copilot-cli/common/.copilot`; only `events.jsonl` transcripts |
| ZCode | `~/.zcode/cli/db/db.sqlite` | `--zcode-state-db` | Shared Desktop/CLI/TUI/ACP store; OpenCode-family SQLite with sequence ordering |
| OpenCode | `$XDG_DATA_HOME/opencode/opencode.db` | `--opencode-state-db` | XDG defaults to `~/.local/share`; existing native reader |
| AGY CLI | `~/.gemini/antigravity-cli/conversation_summaries.db` | `--agy-state-db` | Summary plus neighboring `conversations/*.db`; verified protobuf text/thinking/tool fields |
| Antigravity desktop | `~/.gemini/antigravity/conversation_summaries.db` | `--antigravity-state-db` | Separate store, same decoder; legacy `.pb` is metadata-only |

Existing Codex, Claude, OpenClaw and Hermes sources remain available. Environment overrides supported for new stores: `CODEBUDDY_CONFIG_DIR`, `GEMINI_CLI_HOME`, `PI_CODING_AGENT_DIR`, `PI_CODING_AGENT_SESSION_DIR`, `PRIME_AGENT_CODING_AGENT_DIR`, `PRIME_AGENT_SESSION_DIR`. Explicit arguments win; `--demo` overrides all private discovery and environment paths.

Machine input is the **sessions directory** from the table (or the exact native SQLite file), whereas Web `--*-dir` is the parent tool home:

```bash
python3 -m history_core --source cbc --source-path ~/.codebuddy/projects --data-dir ~/.cache/cchv-reader refresh
python3 -m history_core --source codebuddy --source-path ~/.codebuddy/projects --data-dir ~/.cache/cchv-reader search --query error
python3 -m history_core --source zcode --source-path ~/.zcode/cli/db/db.sqlite search --query error
```

## Evidence boundaries

CodeBuddy supports native tool audit and explicit file-change records. Gemini, pi/Prime and Copilot provide normalized conversation/tool audit and revision-bound handoff; their file diff reconstruction is not yet supported. JSON evidence uses a message JSON pointer; JSONL uses the original line. Gemini/pi/Prime/Copilot materialization requires a complete document within the 2 MiB selected-evidence limit; larger histories stay searchable but bounded handoff explicitly rejects them.

OpenCode/ZCode native read-only audit is available, but content-bound raw record/fragment export stays unavailable until a native snapshot binding exists. AGY audit uses SQLite step indices from verified decoded records; its selected-fragment export is likewise unavailable. AGY reads private, automatically cleaned DB/WAL snapshots to avoid SQLite updating the original SHM read marks. Source revisions include conversation files and WAL, not just the summary DB. Unsupported steps and legacy `.pb` remain explicitly partial/metadata-only; media is not decoded. Limits: 64 MiB physical DB+WAL per conversation, 256 MiB per refresh, 20,000 steps per conversation, 8 MiB per step and 2 MiB for audit snapshots; exceeding a limit refuses the read.

A displayed resume command never executes the provider. CodeBuddy uses `cbc --resume <id>`; unverified resume syntaxes are not guessed.

Usage is provider-reported historical accounting, not a cost estimate. CodeBuddy, Gemini and ZCode input already includes cached tokens. No verified counters means unknown accounting (legacy usage totals may display zero); it does not mean a free session. Copilot counters are intentionally not inferred from shutdown telemetry; AGY/Antigravity token accounting remains unsupported.

Installed configuration/orchestration wrappers such as TeamAI and CM are not additional native provider histories. CLI names sharing a store are grouped. The dated local inventory and format exceptions are in [the source plan](../plans/local-cli-sources/findings.md).

## mcode v2（无头来源）

MiniMax Code 0.5.5 的 `~/.minimax/v2/sessions` 已作为 `mcode` 注册到公共 reader。固定 manifest/messages 文件、公开块与工具关联，来源只读；不假定旧 `~/.minimax/sessions` 包含 v2。Web 自动发现本轮未扩展。使用 [activity 时间窗入口](daily-activity.md)；旧单来源 `--source mcode --source-path ... --data-dir ... refresh/search` 也可用。
