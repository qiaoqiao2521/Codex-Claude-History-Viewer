"""Decode the supported AGY protobuf steps without a protobuf dependency.

Field numbers were verified against FileDescriptorProto records embedded in
the locally installed AGY ELF, not inferred from conversation strings:
  gemini_coder/proto/trajectory.proto: a8a56436e3c94e62c1e4e143a4c994a7316afcdd7da00597d0ef918817198d1a
  jetski/cortex_pb/cortex.proto: 0fc355a750c5c1fd625eda426dbb69199348aba8c46f553084bf52ae4688791a
  jetski/codeium_common_pb/codeium_common.proto: 1ebe27f616eca1871725c9fbb64fbc9c8684006b45860c648fe97f3e8c6cb3d2
Hashes cover the serialized descriptors. Unknown step kinds remain explicit.
Only text, thinking and tool fields are projected; media/Any payloads are not.
"""
import json

MAX_STEP_BYTES = 8 * 1024 * 1024
STEP_FIELDS = {14: 19, 15: 20, 17: 24, 23: 30, 101: 114, 132: 140}
STATUS_NAMES = {0: 'unknown', 1: 'pending', 2: 'running', 3: 'done', 4: 'invalid',
                5: 'cleared', 6: 'canceled', 7: 'error', 8: 'generating', 9: 'waiting',
                11: 'queued', 12: 'interrupted'}


def _varint(data, offset):
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise ValueError('agy_truncated_protobuf')
        part = data[offset]
        offset += 1
        if shift == 63 and part > 1:
            raise ValueError('agy_invalid_varint')
        value |= (part & 127) << shift
        if part < 128:
            return value, offset
    raise ValueError('agy_invalid_varint')


def protobuf_fields(data):
    """Bounded wire parsing, preserving repeated fields and unknown tags."""
    if not isinstance(data, bytes) or len(data) > MAX_STEP_BYTES:
        raise ValueError('agy_step_limit_exceeded')
    result = {}
    offset = count = 0
    while offset < len(data):
        tag, offset = _varint(data, offset)
        number, wire = tag >> 3, tag & 7
        count += 1
        if not number or number > 536870911 or count > 100000:
            raise ValueError('agy_invalid_protobuf')
        if wire == 0:
            value, offset = _varint(data, offset)
        elif wire in (1, 2, 5):
            if wire == 2:
                length, offset = _varint(data, offset)
            else:
                length = 8 if wire == 1 else 4
            end = offset + length
            if end > len(data):
                raise ValueError('agy_truncated_protobuf')
            value, offset = data[offset:end], end
        else:
            raise ValueError('agy_unsupported_wire_type')
        result.setdefault(number, []).append((wire, value))
    return result


def _get(fields, number, wire=2, default=b''):
    values = fields.get(number, [])
    if not values:
        return default
    if any(kind != wire for kind, _ in values):
        raise ValueError('agy_schema_wire_mismatch')
    return values[-1][1]


def _text(fields, number):
    return _get(fields, number).decode('utf-8', errors='strict')


def _nested(fields, number):
    return protobuf_fields(_get(fields, number))


def metadata_timestamp(metadata):
    stamp = _nested(protobuf_fields(metadata or b''), 1)
    seconds = _get(stamp, 1, 0, 0)
    nanos = _get(stamp, 2, 0, 0)
    if seconds > 253402300799 or nanos > 999999999:
        raise ValueError('agy_invalid_timestamp')
    return seconds * 1000 + nanos // 1000000


def _tool(fields):
    name = _text(fields, 2)
    if not name:
        return None
    raw = _text(fields, 3) or _text(fields, 4)
    try:
        arguments = json.loads(raw) if raw else {}
    except ValueError:
        arguments = {'raw_arguments': raw}
    return {'type': 'tool_use', 'id': _text(fields, 1), 'name': name, 'input': arguments}


def _error(fields):
    return '\n'.join(filter(None, (_text(fields, 1), _text(fields, 2), _text(fields, 3))))


def decode_agy_step(payload, *, step_type=None, status=None):
    """Return Claude-compatible envelopes plus honest decoding coverage.

    The database's step_payload is a full gemini_coder.Step, not merely the
    concrete oneof member. DB type/status must agree with the encoded values.
    DONE means a finished AGY step; it never invents a shell exit code.
    """
    outer = protobuf_fields(payload)
    kind = _get(outer, 1, 0, 0)
    native_status = _get(outer, 4, 0, 0)
    if (step_type is not None and kind != step_type) or (status is not None and native_status != status):
        raise ValueError('agy_step_envelope_mismatch')
    meta = _nested(outer, 5)
    timestamp = metadata_timestamp(_get(outer, 5))
    records = []

    def emit(role, content):
        if content:
            records.append({'type': role, 'timestamp': timestamp,
                            'message': {'role': role, 'content': content}})

    supported = kind in STEP_FIELDS and STEP_FIELDS[kind] in outer
    if not supported:
        return {'step_type': kind, 'status': STATUS_NAMES.get(native_status, 'unknown'),
                'timestamp': timestamp, 'records': [], 'supported': False}
    body = _nested(outer, STEP_FIELDS[kind])
    if kind == 14:
        text = []
        for wire, item in body.get(3, []):
            if wire != 2:
                raise ValueError('agy_schema_wire_mismatch')
            value = _text(protobuf_fields(item), 1)
            if value:
                text.append(value)
        # query is the deprecated representation; avoid duplicating items.
        if not text and _text(body, 1):
            text.append(_text(body, 1))
        if _text(body, 2):
            text.append(_text(body, 2))
        emit('user', [{'type': 'text', 'text': '\n'.join(text)}] if text else [])
    elif kind == 15:
        content = []
        if _text(body, 3):
            content.append({'type': 'thinking', 'thinking': _text(body, 3)})
        if _text(body, 1):
            content.append({'type': 'text', 'text': _text(body, 1)})
        for wire, raw in body.get(7, []):
            if wire != 2:
                raise ValueError('agy_schema_wire_mismatch')
            tool = _tool(protobuf_fields(raw))
            if tool:
                content.append(tool)
        emit('assistant', content)
    elif kind == 132:
        tool = _tool(_nested(meta, 4))
        if tool:
            emit('assistant', [tool])
        result = _nested(body, 2)
        text = _text(result, 1)
        error = _error(_nested(outer, 31))
        if text or error:
            item = {'type': 'tool_result', 'tool_use_id': tool['id'] if tool else '',
                    'content': '\n'.join(filter(None, (text, error)))}
            if native_status == 7 or error:
                item['is_error'] = True
            emit('user', [item])
        # ArgsEntry is a map<string,string>. Without a metadata tool name, it
        # still remains visible as data, never fabricated into a command.
        if not tool and body.get(1):
            arguments = {}
            for wire, raw in body[1]:
                if wire != 2:
                    raise ValueError('agy_schema_wire_mismatch')
                entry = protobuf_fields(raw)
                arguments[_text(entry, 1)] = _text(entry, 2)
            emit('system', [{'type': 'text', 'text': json.dumps(arguments, ensure_ascii=False)}])
    elif kind == 101:
        emit('system', [{'type': 'text', 'text': _text(body, 1)}] if _text(body, 1) else [])
    elif kind == 17:
        text = _error(_nested(body, 3))
        emit('system', [{'type': 'text', 'text': text}] if text else [])
    elif kind == 23:
        # Checkpoint summaries are historical derived text, not user messages.
        text = '\n'.join(filter(None, (_text(body, 4), _text(body, 5), _text(body, 6))))
        if text:
            records.append({'type': 'summary', 'timestamp': timestamp, 'summary': text})
    return {'step_type': kind, 'status': STATUS_NAMES.get(native_status, 'unknown'),
            'timestamp': timestamp, 'records': records, 'supported': True}
