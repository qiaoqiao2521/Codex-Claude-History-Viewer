# Browser fixture ready

`/tmp/hv-search-closure-20260927/fixture` was built completely by this worker; it contains 35 JSONL files and 2184 valid timestamps. **Do not rebuild or modify it except the browser test's explicit controlled index-change action.** This worker will not touch it again.

- Source roots: `home/.codex/sessions` and `home/.claude/projects`.
- `双千兆` → codex / alpha-0001 / absolute message_index 4.
- `sharedneedle` → same ID alpha-0001 in separate Codex and Claude stores.
- `paginationneedle` → page-24 ... page-00, exactly 25 Codex sessions; source startup scan must finish before accepting this count.
- `cwdmetaneedle` → metadata-only, no fabricated body excerpt.
- For controlled refresh: add a **new** Codex JSONL or append an ordinary message to page-00 using a valid ISO timestamp; then explicit refresh and click the original page's next button. Original fixture hashes intentionally cease matching after this UI mutation; use the initial browser snapshot to document it.

The browser fixture's `manifest.json` preserves the generator's first arithmetic expectation (57 x's before the Chinese tail), which was wrong by one character. This does **not** affect its source JSONL or any browser case. The final independent manifest generator is corrected to 56 x's (`70 - len('after2mneedle ')`). Oracle replay uses its own newly built root. No product behavior was changed to make this expectation pass.
