#!/usr/bin/env python3
"""Synthetic fixture builder for search hardening. All data is fake; the
expected-hit manifest is hand-authored in manifest.json (construction-defined
arithmetic), never derived from the code under test."""
import json, os
from pathlib import Path

HOME = Path('/tmp/cchv-hardening/home')
CODEX = HOME / '.codex/sessions/2026/09/06'
CLAUDE = HOME / '.claude/projects/proj-claude'

def line(ts, obj):
    return json.dumps({"timestamp": ts, **obj}, ensure_ascii=False)

def meta(ts, sid, cwd):
    return line(ts, {"type": "session_meta", "payload": {"id": sid, "timestamp": ts, "cwd": cwd}})

def msg(ts, role, text):
    ctype = "input_text" if role == "user" else "output_text"
    return line(ts, {"type": "response_item", "payload": {"type": "message", "role": role,
              "content": [{"type": ctype, "text": text}]}})

def event(ts, etype, payload):
    return line(ts, {"type": "event_msg", "payload": {"type": etype, **payload}})

def t(n):  # 10:00:00Z + n seconds
    m, s = divmod(n, 60)
    return f"2026-09-06T10:{m:02d}:{s:02d}Z"

# --- Session A alpha-0001 (indexes are construction-defined) ---
A = [
    meta(t(0), "alpha-0001", "/fix/proj-alpha"),
    msg(t(1), "user", "alphagoal 请准备环境"),                       # idx 0
    msg(t(2), "assistant", "x" * 2_100_000),                        # idx 1 filler >2M
    msg(t(3), "user", "<permissions instructions>双千兆CTX rule</permissions instructions>"),  # idx 2 context
    msg(t(4), "assistant", "y" * 11500 + "tailneedle" + "y" * 300), # idx 3 tail at ~11500
    msg(t(5), "assistant", "在双千兆网卡上验证 OpenWrt 前先核对驱动"),  # idx 4
    msg(t(6), "assistant", "Café café Ωω 🎯 end"),                  # idx 5
    msg(t(7), "user", "status 100%_done\\path literal"),            # idx 6
    event(t(8), "unknown_event", {"note": "rawfallback marker"}),   # idx 7 raw fallback (blob-excluded)
]
(CODEX / "rollout-2026-09-06T10-00-00-alpha.jsonl").write_text("\n".join(A) + "\n", encoding="utf-8")

# --- Session B beta-0001: keyword only in project path ---
B = [
    meta(t(20), "beta-0001", "/fix/betatitle-only"),
    msg(t(21), "user", "普通内容无关键词"),
    msg(t(22), "assistant", "普通回复"),
]
(CODEX / "rollout-2026-09-06T10-00-20-beta.jsonl").write_text("\n".join(B) + "\n", encoding="utf-8")

# --- Session C gamma-0001: cross-message AND + phrase at index 2102 ---
C = [meta(t(40), "gamma-0001", "/fix/proj-gamma"),
     msg(t(41), "user", "gammaterm1 起头"),         # idx 0
     msg(t(42), "assistant", "gammaterm2 承接")]    # idx 1
for i in range(2100):                               # idx 2..2101
    C.append(msg(t(43 + i), "assistant", f"填充{i}"))
C.append(msg(t(2200), "user", "gammaterm1 gammaterm2 完整短语结尾"))  # idx 2102
(CODEX / "rollout-2026-09-06T10-00-40-gamma.jsonl").write_text("\n".join(C) + "\n", encoding="utf-8")

# --- Session E quiet ---
E = [meta(t(30), "quiet-0001", "/fix/proj-quiet"),
     msg(t(31), "user", "nothing special here")]
(CODEX / "rollout-2026-09-06T10-00-30-quiet.jsonl").write_text("\n".join(E) + "\n", encoding="utf-8")

# --- Session D: SAME id as A in claude source, distinct body ---
D = []
def cline(ts, typ, content, sid="alpha-0001"):
    D.append(json.dumps({"timestamp": ts, "sessionId": sid, "cwd": "/fix/proj-claude",
              "type": typ, "message": {"role": "user" if typ == "user" else "assistant",
              "content": content}}, ensure_ascii=False))
cline("2026-09-06T11:00:00.000Z", "user", "claudedistinct 同名会话另一来源")
cline("2026-09-06T11:00:05.000Z", "assistant", "claude 侧回复，正文含 claudedistinct 二次")
(CLAUDE / "alpha-0001.jsonl").write_text("\n".join(D) + "\n", encoding="utf-8")

print("fixture written:")
for p in sorted(CODEX.glob('*.jsonl')) + sorted(CLAUDE.glob('*.jsonl')):
    print(" ", p, p.stat().st_size, "bytes")
