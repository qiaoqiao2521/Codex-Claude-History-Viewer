#!/usr/bin/env python3
"""Build synthetic conversations for real-reader acceptance; never reuse a root."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

BASE = datetime(2026, 9, 27, tzinfo=timezone.utc)


def stamp(second):
    return (BASE + timedelta(seconds=second)).isoformat()


def message(role, text):
    return {"type": "message", "role": role, "content": [{"type": "input_text" if role == "user" else "output_text", "text": text}]}


def build(root):
    root.mkdir(parents=True, exist_ok=False)
    codex = root / "home/.codex/sessions"
    claude = root / "home/.claude/projects/synthetic"
    codex.mkdir(parents=True)
    claude.mkdir(parents=True)

    def write_codex(sid, start, project, payloads):
        rows = [{"type": "session_meta", "timestamp": stamp(start), "payload": {"id": sid, "cwd": project}}]
        rows += [{"type": "response_item", "timestamp": stamp(start + n + 1), "payload": payload} for n, payload in enumerate(payloads)]
        (codex / (sid + ".jsonl")).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))

    title = "修复登录刷新失败"
    write_codex("shared-session", 1000, "/synthetic/login", [
        message("user", "<permissions instructions>测试上下文，不是用户请求</permissions instructions>"),
        message("user", title),
        message("assistant", "决定采用显式刷新，保留旧失败记录。"),
        {"type": "function_call", "name": "shell", "call_id": "synthetic-call", "arguments": "{\"command\": \"pytest\"}"},
        {"type": "function_call_output", "call_id": "synthetic-call", "output": "Error: LoginExpired — tests failed（合成旧失败）"},
        message("assistant", "验证结果：pytest tests passed（合成复测陈述，不代表当前版本）。"),
        message("assistant", "最后回复：请用户检查真实登录环境，仍待人工确认。"),
    ])
    rows = [{"timestamp": stamp(500 + n), "sessionId": "shared-session", "cwd": "/synthetic/login", "type": role, "message": {"role": role, "content": text}} for n, (role, text) in enumerate([
        ("user", title), ("assistant", "报错：旧刷新仍然失败，等待后续排查。"),
    ])]
    (claude / "shared-session.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    write_codex("unrelated", 100, "/synthetic/login", [message("user", "检查图片缓存大小"), message("assistant", "这个问题单独保留。")])
    for n in range(51):
        write_codex(f"page-{n:02}", 2000 + n * 10, "/synthetic/paging", [message("user", "排查同一数据库连接问题"), message("assistant", f"第 {n} 次独立记录，均需保留。")])
    print(root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    build(parser.parse_args().root.resolve())
