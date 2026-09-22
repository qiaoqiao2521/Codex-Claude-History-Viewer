"""Read CodeBuddy/cbc JSONL through the existing transcript renderer."""
from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path

from audit.codebuddy import normalize_codebuddy_record

CODEBUDDY_ALIASES = ("codebuddy", "cbc", "codebuddy-code")


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return 0
    if isinstance(value, float) and not math.isfinite(value):
        return 0
    return int(value)


def _usage(record):
    if record.get("type") != "function_call" and not (
            record.get("type") == "message" and record.get("role") == "assistant"):
        return None
    provider = record.get("providerData")
    provider = provider if isinstance(provider, dict) else {}
    message = record.get("message")
    message = message if isinstance(message, dict) else {}
    native = message.get("usage")
    native = native if isinstance(native, dict) else {}
    usage = provider.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    raw = provider.get("rawUsage")
    raw = raw if isinstance(raw, dict) else {}
    if not native and not usage and not raw:
        return None
    inputs = _number(native.get("input_tokens", usage.get("inputTokens", raw.get("prompt_tokens"))))
    outputs = _number(native.get("output_tokens", usage.get("outputTokens", raw.get("completion_tokens"))))
    total = native.get("total_tokens", usage.get("totalTokens", raw.get("total_tokens")))
    prompt_details = raw.get("prompt_tokens_details")
    prompt_details = prompt_details if isinstance(prompt_details, dict) else {}
    completion_details = raw.get("completion_tokens_details")
    completion_details = completion_details if isinstance(completion_details, dict) else {}
    cached = _number(native.get("cache_read_input_tokens", raw.get("cache_read_input_tokens",
                     raw.get("prompt_cache_hit_tokens", prompt_details.get("cached_tokens", raw.get("cached_tokens"))))))
    cached += _number(native.get("cache_creation_input_tokens", raw.get("cache_creation_input_tokens", raw.get("prompt_cache_write_tokens"))))
    return {"input": inputs, "output": outputs, "cached": cached,
            "reasoning": _number(raw.get("completion_thinking_tokens", completion_details.get("reasoning_tokens"))),
            # Native input already includes cache usage; never add cached twice.
            "total": _number(total) if total is not None else inputs + outputs}


class _NormalizedSource:
    """A streaming path adapter; no temporary copy of private history is made."""
    def __init__(self, path):
        self.path = Path(path)
        self.stem = self.path.stem
        self.usage_by_id = {}
        self.unkeyed_usage = {"input": 0, "output": 0, "cached": 0, "reasoning": 0, "total": 0}
        self.has_usage = False
        self.has_session_id = False
        self.native_title = None

    def __str__(self):
        return str(self.path)

    @contextmanager
    def open(self, mode="r", encoding="utf-8"):
        with self.path.open(mode, encoding=encoding) as stream:
            def lines():
                for line in stream:
                    try:
                        record = json.loads(line)
                    except (ValueError, TypeError):
                        yield line  # Keep the existing malformed-tail behaviour.
                        continue
                    if isinstance(record, dict):
                        self.has_session_id |= isinstance(record.get("sessionId"), str) and bool(record["sessionId"])
                        if record.get("type") == "ai-title" and isinstance(record.get("aiTitle"), str):
                            self.native_title = record["aiTitle"].strip()[:80] or self.native_title
                        usage = _usage(record)
                        if usage is not None:
                            self.has_usage = True
                            provider = record.get("providerData")
                            provider = provider if isinstance(provider, dict) else {}
                            key = provider.get("messageId") or record.get("id")
                            if isinstance(key, str) and key:
                                previous = self.usage_by_id.get(key)
                                if previous is None or usage["total"] > previous["total"]:
                                    self.usage_by_id[key] = usage
                            else:
                                for field, value in usage.items():
                                    self.unkeyed_usage[field] += value
                    yield json.dumps(normalize_codebuddy_record(record), ensure_ascii=False) + "\n"
            yield lines()


def parse_codebuddy_session_file(path, display_root=None):
    """Same indexer payload as ``parse_claude_session_file``, native accounting.

    Default discovery excludes ``agent-*`` sidecars: their records often carry
    the parent session ID. Direct parsing still keeps such files under their
    own filename identity, preventing accidental parent-session replacement.
    ``display_root`` scopes only the fallback identity when no native ID exists;
    an encoded project directory is never guessed into a working directory.
    """
    from .sources import parse_claude_session_file
    adapted = _NormalizedSource(path)
    session = parse_claude_session_file(adapted)
    if session is None:
        return None
    actual = Path(path)
    if actual.name.startswith("agent-"):
        session["id"] = actual.stem
    elif not adapted.has_session_id:
        identity = str(actual.absolute())
        if display_root is not None:
            try:
                identity = str(actual.absolute().relative_to(Path(display_root).absolute()))
            except ValueError:
                pass
        session["id"] = "file-" + hashlib.sha256(identity.encode()).hexdigest()[:24]
    if adapted.native_title:
        session["title"] = adapted.native_title
    if adapted.has_usage:
        totals = dict(adapted.unkeyed_usage)
        for usage in adapted.usage_by_id.values():
            for field, value in usage.items():
                totals[field] += value
        session["usage"] = totals
    else:
        session["usage"] = None
    return session
