"""Narrow recorded markers, without inferring successful loading or effects.

Callers must pass the original native role, prompt and tool input. A request or
agent declaration is evidence of that event only; it does not establish that a
skill ran, a plugin was installed, or the completed work benefited from it.
"""

import hashlib
import json
import re

from .evidence import redact_text

LEARNING_OUTPUT_STYLE_PREFIX = (
    "You are in 'learning' output style mode, which combines interactive "
    "learning with educational explanations."
)
DECLARED_MARKER_PREFIX = '[[tracemesh:skill-trigger]] '
DECLARATION_CHARS = 2048
FIELD_CHARS = 128
_DECLARED_FIELDS = {'name', 'skill', 'path', 'version', 'content_hash'}
_SHA256 = re.compile(r'[0-9a-fA-F]{64}\Z')


def _text_field(marker, key, value):
    """Redact complete values before clipping, so clipping cannot split secrets."""
    safe = redact_text(value)
    marker[key] = safe[:FIELD_CHARS]
    marker[key + '_truncated'] = len(safe) > FIELD_CHARS


def _skill_marker(name, event, origin, *, path='unknown', version='unknown'):
    marker = {'kind': 'skill', 'event': event, 'evidence_origin': origin}
    for key, value in (('name', name), ('path', path), ('version', version)):
        _text_field(marker, key, value)
    return marker


def _nonempty_text(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def style_markers(role, text):
    """Recognise the installed learning prompt in native system/developer text."""
    if role not in ('system', 'developer') or not isinstance(text, str):
        return []
    if not text.strip().startswith(LEARNING_OUTPUT_STYLE_PREFIX):
        return []
    return [{'kind': 'output_style', 'name': 'learning-output-style',
             'event': 'context_injected', 'evidence_origin': 'recorded_prompt',
             'content_hash': hashlib.sha256(text.encode('utf-8')).hexdigest()}]


def skill_tool_markers(tool_name, raw_input):
    """Record native Skill requests; ordinary reads and mentions are not calls."""
    if not isinstance(tool_name, str) or tool_name.casefold() != 'skill':
        return []
    if isinstance(raw_input, str):
        try:
            raw_input = json.loads(raw_input)
        except (TypeError, ValueError, RecursionError):
            return []
    if not isinstance(raw_input, dict):
        return []
    name = _nonempty_text(raw_input.get('skill'))
    if not name:
        return []
    return [_skill_marker(name, 'invocation_requested', 'native_tool_call')]


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_marker_field')
        result[key] = value
    return result


def declared_skill_markers(role, text):
    """Accept only a complete standalone assistant declaration, never examples."""
    if role != 'assistant' or not isinstance(text, str) or len(text) > DECLARATION_CHARS:
        return []
    body = text.strip()
    if not body.startswith(DECLARED_MARKER_PREFIX):
        return []
    try:
        value = json.loads(body[len(DECLARED_MARKER_PREFIX):], object_pairs_hook=_unique_fields)
    except (TypeError, ValueError, RecursionError):
        return []
    if not isinstance(value, dict) or not value.keys() <= _DECLARED_FIELDS:
        return []
    name = _nonempty_text(value.get('name'))
    skill = _nonempty_text(value.get('skill'))
    if ('name' in value and not name) or ('skill' in value and not skill):
        return []
    if not (name or skill) or (name and skill and name != skill):
        return []
    fields = {}
    for key in ('path', 'version'):
        fields[key] = _nonempty_text(value[key]) if key in value else 'unknown'
        if not fields[key]:
            return []
    content_hash = value.get('content_hash')
    if 'content_hash' in value and (
        not isinstance(content_hash, str) or not _SHA256.fullmatch(content_hash)
    ):
        return []
    marker = _skill_marker(name or skill, 'agent_declared', 'agent_marker', **fields)
    if content_hash is not None:
        marker['content_hash'] = content_hash.lower()
    return [marker]
