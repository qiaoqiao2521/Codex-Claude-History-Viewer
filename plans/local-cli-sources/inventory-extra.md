# Extra local CLI source inventory

Observed: 2026-09-22T18:01:24+08:00

Scope: read-only metadata/schema inventory of requested installed commands. No model/login launch, no private configuration values or conversation text printed. SQLite opened with `mode=ro`; row counts capped at 10,001. JSONL inspection emitted keys and known structural event types only. Counts are dated observations, not ongoing monitoring.

## Initial inventory decision (superseded by verified implementation below)

**Add ZCode and Copilot as independent sources. Reuse the pi parser for Prime Agent as a separate selectable store when its history exists. Treat AGY as an important schema spike, not a JSONL source already supported.**

| Command | Installation / local history evidence | Source decision |
| --- | --- | --- |
| `zcode`, `zcode-cli`, `zcode-tui`, `zcode-acp`, `zcode-acp-server` | Desktop wrapper launches `~/Apps/ZCode-3.11.2-linux-x64.AppImage`; CLI bundle `~/.local/share/zcode-cli.cjs`; TUI package `zcode-app-cli` 3.14.1-27; ACP package 0.37.1. Main transcript DB `~/.zcode/cli/db/db.sqlite` has 55 sessions / 6,916 messages / >10,000 parts. | One independent **zcode** source. Desktop/CLI/TUI/ACP are access surfaces over the same ZCode store, not five sources. OpenCode-like schema permits factoring shared read-only adapter logic, but do not relabel this independent DB as the user's OpenCode store. |
| `copilot` | `/snap/bin/copilot` resolves via Snap; installed `copilot-cli` 1.0.83, strict confinement. `~/.copilot/session-state` is absent, but `~/snap/copilot-cli/common/.copilot/session-state` has 3 session directories and 2 `events.jsonl` files. Parent `session-store.db` has 3 session rows and 3 turn rows. | Add **copilot** JSONL adapter, discovering both normal and Snap common roots. Missing transcript for one session must remain explicit. `events.jsonl` is primary timeline; session-store summary alone is incomplete. |
| `agy` | Native ELF `~/.local/bin/agy`. Independent root `~/.gemini/antigravity-cli`: 30 `conversation_summaries` rows; `conversations/` has 29 SQLite DBs and 1 protobuf file. A sampled session has 179 `steps`, mostly protobuf BLOB columns. | Distinct **agy** history exists and matters. Needs a protobuf/step decoder spike or official structured export contract; do not claim full retrieval using only summaries or input history. |
| `antigravity` | Desktop launcher `~/Apps/Antigravity/Antigravity-x64/antigravity`; root `~/.gemini/antigravity` has 1 summary DB row but its conversations directory is empty. | Same family as AGY but a separate physical root. Preserve store identity; current desktop evidence supports metadata only, not recovered full transcript. |
| `prime-agent` | Package 0.9.4. Source declares `.prime/agent`, session JSONL v3 and `type=session/message`, tree `id/parentId`, `message` payload; `~/.prime/agent/sessions` does not exist. | Format-compatible pi family, distinct configurable root. Reuse pi parser and register Prime root when present; no live-history acceptance can be claimed on this host. |
| `codex-web-gpt` | Desktop AppImage 5.0.6 wrapper; env variable names `CODEX_WEB_GPT_APPIMAGE`, `CODEX_WEB_GPT_LAUNCHER_EXECUTABLE`. No `~/.codex-web-gpt` or `~/.config/codex-web-gpt` store found. | Do not add a guessed provider. This is a desktop shell; independent transcript store was not established from wrapper/package metadata. Existing Codex sources should retain ownership of any native Codex transcript. |
| `orca-ide` | Desktop launcher; `~/.config/orca` includes provider hooks, Codex runtime home and one Codex-session-backfill JSONL. `orchestration.db` stores runs/tasks/deliveries/terminal archives, rather than a plain provider transcript model. | Provider sessions belong to existing adapters; orchestration evidence is a different optional product capability. Do not index UI cache or coordination messages as extra provider conversations automatically. |
| `teamai` | Package `teamai-cli` 0.23.1, a configuration/agent tooling bundle referring to Claude/Codex/OpenCode. No `~/.teamai` root exists. | No independent transcript source established. Do not count wrapper/config tooling as another provider. |
| `cm`, `controlmesh` | Both uv entrypoints import `controlmesh.__main__.main`. `~/.controlmesh/transcripts/{tg,terminal}` has 2 JSONL files; separate runtime event directory has 2 JSONLs. | One orchestrator surface history, not two CLI providers. It has independent user-visible transport turns but overlaps underlying Agent work. Add only under explicit transport-history scope with link/dedup policy, not in this native-source pass. |

## ZCode adapter contract evidence

Canonical DB: `~/.zcode/cli/db/db.sqlite`, not desktop `~/.zcode/v2/tasks-index.sqlite`. The latter has 34 task rows and is a UI task index, not complete messages. Installed `zcode-acp-server/dist/tasks-index.js` explicitly documents this distinction (lines 4–5).

Core schema:

- `session(id, project_id, workspace_id, parent_id, directory, path, title, time_created, time_updated, ...)`.
- `message(id, session_id, time_created, time_updated, data, sequence)`.
- `part(id, message_id, session_id, time_created, time_updated, data, sequence)`.
- Sampled `message.data` keys include `role`, `time`, `tokens`, `model`, `modelID`, `modelId`, `providerID`, `providerId`, `agent`, `cost`, `semantics`, `visibility`.
- Sampled `part.data` kinds: `text`, `reasoning`, `tool`, `step-start`, `step-finish`, `timeline`; tool-related keys include `callID`, `tool`, `state`, `status`.
- There are also 3 `.jsonl` rollout files, but they are not the primary complete session store. Do not duplicate DB sessions by indexing both formats.

Suggested synthetic fixture: minimal OpenCode-shaped DB plus explicit `sequence`, mixed `modelID/modelId`, a timeline-only part, one tool failure, and a parent session. Verify message/part ordering, read-only SQLite access, source label and cache/store separation.

## Copilot adapter contract evidence

Roots to consider: `~/.copilot/session-state/*/events.jsonl` and `~/snap/copilot-cli/common/.copilot/session-state/*/events.jsonl`. The Snap common root is the actual populated store here; `~/snap/copilot-cli/current/.copilot` is absent.

Observed top-level JSONL keys: `type`, `id`, `parentId`, `timestamp`, `data`. Event types include `session.start`, `session.info`, `session.model_change`, `system.message`, `user.message`, `assistant.turn_start`, `assistant.message`, `tool.execution_start`, `tool.execution_complete`, `hook.start`, `hook.end`, `assistant.turn_end`, `session.shutdown`. `workspace.yaml` exists beside some histories.

Observed `data` keys relevant to parsing: `sessionId`, `startTime`, `context`, `content`, `role`, `toolCallId`, `toolName`, `arguments`, `result`, `success`, `toolRequests`, `outputTokens`, `modelMetrics`, `currentTokens`, `conversationTokens`. Some opaque/encrypted reasoning fields exist; preserve explicit unsupported/unknown state rather than decoding guesses. Use session-start context for cwd if present; do not read arbitrary config/auth files.

Suggested synthetic fixture: session start → user → assistant → tool start → failed tool complete → assistant → shutdown. Include duplicate/tail records, opaque reasoning, and absent workspace metadata. Schema-only observations do not establish all token-counter semantics.

## AGY decoder boundary

`~/.gemini/antigravity-cli/history.jsonl` contains **input/history entries**, keys `conversationId`, `display`, `timestamp`, `type`, `workspace`; it is not a user/assistant/tool transcript. Never label indexing it as AGY full-history support.

Conversation SQLite schema:

- `trajectory_meta(trajectory_id, cascade_id, trajectory_type, source)`.
- `steps(idx, step_type, status, has_subtrajectory, metadata BLOB, error_details BLOB, permissions BLOB, task_details BLOB, render_info BLOB, step_payload BLOB, step_format)`.
- Other tables: `gen_metadata`, `executor_metadata`, `parent_references`, `trajectory_metadata_blob`, `battle_mode_infos`.
- Summary index provides title/preview/count/time/workspace and a `raw_summary BLOB`; no raw private content was inspected or exported.

A useful next spike is identifying versioned protobuf descriptors in the installed/public AGY implementation and creating fully synthetic step fixtures. Until then, report `unsupported_format` for transcript retrieval, with metadata availability separately represented.

## Prime and orchestrator notes

Prime installed source: `dist/config.js:380` gives `.prime/agent`; lines 487–492 resolve session root and env overrides. `dist/core/session-manager.js:12` says version 3; lines 1146–1153 define session header, lines 1315–1321 define message entry. Relevant env names include `PRIME_AGENT_CODING_AGENT_DIR` and `PRIME_AGENT_SESSION_DIR`. Do not import session manager at runtime: its load/migration paths may write source files.

ControlMesh transcript schema observed: `attachments`, `chat_id`, `created_at`, `reply_to_turn_id`, `role`, `session_key`, `source`, `surface_session_id`, `topic_id`, `transport`, `turn_id`, `visible_content`. These are surface turns; runtime event schema is separate. Reading them would extend Viewer to transport conversations, requiring a deliberate scope decision.

No production adapter or fixture was added in this inventory pass. Root agent should choose ZCode/Copilot integration first; Prime can share the ongoing pi work, while AGY needs a separate honest format gate.

## Verified implementation, 2026-09-22

ZCode, Copilot, Prime and AGY/Antigravity are now registered. AGY field maps were recovered from the installed ELF protobuf descriptors and exercised with synthetic fixtures. Actual CLI coverage: 30 sessions, 29 decoded (9,443 steps / 10,340 displayed records), one legacy `.pb` metadata-only. That 132,959-byte file fails wire validation and lacks recognizable common compression headers; its encoding remains unknown. Desktop has one summary whose conversation DB/PB is absent: `source_missing`, not an unsupported PB. These findings supersede the initial spike recommendation above.

AGY reads bounded private DB/WAL snapshots; the summary and conversation copies share an actual physical-byte budget. Derived indexes are in memory. Both real stores' DB/WAL/SHM SHA256 values remained unchanged after indexing. Unknown steps, missing sources, unsupported token accounting and absent selected-fragment bindings remain explicit. See [source capabilities](../../docs/local-cli-sources.md).
