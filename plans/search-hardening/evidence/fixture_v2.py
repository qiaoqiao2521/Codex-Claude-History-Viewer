#!/usr/bin/env python3
"""Fixture v2 additions: (1) a second session matching '填充' so a page-1
cursor exists; (2) delta-0001 with FIVE early single-term hits before the
phrase message, to probe cross-message excerpt ordering. Additive only."""
import json
from pathlib import Path

CODEX = Path('/tmp/cchv-hardening/home/.codex/sessions/2026/09/06')
def line(ts, obj): return json.dumps({"timestamp": ts, **obj}, ensure_ascii=False)
def msg(ts, role, text):
    ct = "input_text" if role == "user" else "output_text"
    return line(ts, {"type": "response_item", "payload": {"type": "message", "role": role,
              "content": [{"type": ct, "text": text}]}})
def t(n):
    m, s = divmod(n, 60)
    return f"2026-09-06T10:{m:02d}:{s:02d}Z"

# filler2-0001: second session matching q=填充
F = [line(t(2400), {"type": "session_meta", "payload": {"id": "filler2-0001", "timestamp": t(2400), "cwd": "/fix/proj-fill"}}),
     msg(t(2401), "user", "这里也有填充内容")]
(CODEX / "rollout-2026-09-06T10-40-00-filler2.jsonl").write_text("\n".join(F) + "\n", encoding="utf-8")

# delta-0001: hits at idx 1..5 (gammaterm1), phrase at idx 2102... use 2106 for margin
D = [line(t(2500), {"type": "session_meta", "payload": {"id": "delta-0001", "timestamp": t(2500), "cwd": "/fix/proj-delta"}}),
     msg(t(2501), "user", "deltagoal")]
for i in range(5):                                   # idx 1..5 contain the term
    D.append(msg(t(2502 + i), "assistant", f"第{i}次提到 gammaterm1 的独立消息"))
for i in range(2100):                                # idx 6..2105
    D.append(msg(t(2510 + i), "assistant", f"其他{i}"))
D.append(msg(t(4620), "user", "gammaterm1 gammaterm2 完整短语在深处"))  # idx 2106
(CODEX / "rollout-2026-09-06T10-41-40-delta.jsonl").write_text("\n".join(D) + "\n", encoding="utf-8")
print("fixture v2 written")
