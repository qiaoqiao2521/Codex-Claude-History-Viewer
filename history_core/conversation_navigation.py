"""Bounded, revision-bound navigation hints in one indexed conversation.

Hints recognise wording, not successful tests, resolved failures or final
decisions. Full indexed text is searched before excerpts are cut. Source
transcripts, audit events and native flatteners are never loaded here.
"""
from .evidence import source_store_id
from .providers import canonical_source, uses_message_index
from .reuse import index_revision, query_budget


MAX_MARKERS = 80
MAX_EXCERPT_CHARS = 240
EXCERPT_CONTEXT = 70

# Deliberately narrow cues avoid treating e.g. "没有错误" / "no errors" as
# failures. These remain wording hints: "pytest has not run" is a test mention,
# never evidence that a test ran or passed.
_DECISION = ("决定采用", "决定使用", "选择采用", "选择使用", "改用", "最终选择", "建议采用",
             "we decided", "decision:", "decided to", "switch to")
_FAILURE = ("失败：", "失败:", "失败了", "报错：", "报错:", "报错了", "错误：", "错误:", "error:",
            "exception:", "permission denied", "traceback (most recent call last)",
            "test failed", "tests failed", "failed with", "exit code: 1")
_VERIFICATION = ("测试通过", "测试结果", "验证结果", "测试失败", "pytest", "unittest",
                 "npm test", "node --test", "tests passed", "test passed", "tests failed")
_KIND_ORDER = ("request", "decision", "failure", "verification", "last_response")


def _position(needles):
    # Constants are owned here, never query parameters or transcript contents.
    cases = []
    for needle in needles:
        literal = "'" + needle.replace("'", "''") + "'"
        occurrence = f"instr(lower(COALESCE(m.text,'')),{literal})"
        cases.append(f"WHEN {occurrence}>0 THEN {occurrence}")
    return "CASE " + " ".join(cases) + " ELSE 0 END"


_DECISION_SQL = _position(_DECISION)
_FAILURE_SQL = _position(_FAILURE)
_VERIFICATION_SQL = _position(_VERIFICATION)
_ORDERED = """
    WITH ordered AS (
        SELECT id, ROW_NUMBER() OVER (ORDER BY ts_ms ASC,id ASC)-1 AS message_index
        FROM messages WHERE session_id=?
    )
"""


def _marked_query(anchor=None):
    """Keep numbering before role/kind filtering, as in the full reader."""
    if anchor == "first_user":
        select = """SELECT o.id,o.message_index FROM ordered o JOIN messages m ON m.id=o.id
                    WHERE m.role='user' AND m.kind='message' AND trim(COALESCE(m.text,''))<>''
                    ORDER BY o.message_index ASC LIMIT 1"""
    elif anchor == "last_assistant":
        select = """SELECT o.id,o.message_index FROM ordered o JOIN messages m ON m.id=o.id
                    WHERE m.role='assistant' AND m.kind='message' AND trim(COALESCE(m.text,''))<>''
                    ORDER BY o.message_index DESC LIMIT 1"""
    else:
        select = """SELECT o.id,o.message_index FROM ordered o JOIN messages m ON m.id=o.id
                    WHERE ((m.kind='message' AND m.role IN ('user','assistant'))
                           OR m.kind='tool_result') AND trim(COALESCE(m.text,''))<>''"""
    eligible_signal = "(m.kind='tool_result' OR (m.kind='message' AND m.role='assistant'))"
    query = _ORDERED + f""",
        selected AS ({select}),
        signals AS MATERIALIZED (
            SELECT s.id,s.message_index,m.role,
                   m.role='user' AND m.kind='message' AS request,
                   CASE WHEN m.role='assistant' AND m.kind='message' THEN {_DECISION_SQL} ELSE 0 END AS decision,
                   CASE WHEN {eligible_signal} THEN {_FAILURE_SQL} ELSE 0 END AS failure,
                   CASE WHEN {eligible_signal} THEN {_VERIFICATION_SQL} ELSE 0 END AS verification
            FROM selected s JOIN messages m ON m.id=s.id
        )
        SELECT s.message_index,s.role,s.request,s.decision,s.failure,s.verification,
               substr(COALESCE(m.text,''), max(1,
                   CASE WHEN s.request THEN 1 ELSE
                       COALESCE(NULLIF(s.decision,0),NULLIF(s.failure,0),NULLIF(s.verification,0),1)
                   END - ?), ?) AS text,
               length(COALESCE(m.text,''))>? AS truncated
        FROM signals s JOIN messages m ON m.id=s.id
    """
    if anchor is None:
        query += " WHERE s.request OR s.decision>0 OR s.failure>0 OR s.verification>0"
    return query + " ORDER BY s.message_index ASC LIMIT ?"


def _items(conn, session_id, anchor=None):
    rows = conn.execute(_marked_query(anchor),
                        (session_id, EXCERPT_CONTEXT, MAX_EXCERPT_CHARS,
                         MAX_EXCERPT_CHARS, 1 if anchor else MAX_MARKERS + 1)).fetchall()
    result = []
    for row in rows:
        kinds = [kind for kind in _KIND_ORDER[:-1] if row[kind]]
        if anchor == "last_assistant":
            kinds.append("last_response")
        result.append({"message_index": row["message_index"], "role": row["role"],
                       "text": row["text"], "kinds": kinds,
                       "truncated": bool(row["truncated"])})
    return result


def key_messages(indexers, *, system, source, session_id, store_id=None, source_revision=None):
    """Return navigation candidates for precisely the revision the user saw.

    An absent store is accepted only when system/source resolve uniquely.
    Native adapters lacking the common message index report unsupported rather
    than inventing offsets. Query errors propagate for the HTTP error surface.
    """
    if not source_revision:
        raise ValueError("source_revision_required")
    if not isinstance(session_id, str) or not session_id or len(session_id) > 4096:
        raise ValueError("invalid_session_id")
    source = canonical_source(source)
    matches = [entry for entry in indexers if entry[0] == system and entry[1] == source]
    if store_id is not None:
        matches = [entry for entry in matches if source_store_id(*entry) == store_id]
    if len(matches) != 1:
        raise ValueError("selection_source_ambiguous" if matches else "selection_source_unavailable")
    system, source, indexer = matches[0]
    revision = index_revision(indexer)
    if source_revision != revision:
        raise ValueError("index_revision_changed: reload the conversation")
    result = {"system": system, "source": source, "store_id": source_store_id(*matches[0]),
              "id": session_id, "source_revision": revision,
              "status": "available", "items": [], "total_messages": None,
              "indexed_messages": None, "partial": False, "truncated": False,
              "interpretation": "wording_hints_only",
              "limits": {"max_marker_messages": MAX_MARKERS, "max_anchor_messages": 2,
                         "max_excerpt_chars": MAX_EXCERPT_CHARS}}
    if not uses_message_index(indexer):
        result.update(status="unsupported", reason="source_message_index_unsupported")
        if index_revision(indexer) != revision:
            raise ValueError("index_revision_changed: reload the conversation")
        return result

    with query_budget(indexer) as conn:
        if conn.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone() is None:
            raise ValueError("session_not_found")
        total = conn.execute("SELECT COUNT(*) FROM messages WHERE session_id=?", (session_id,)).fetchone()[0]
        markers = _items(conn, session_id)
        truncated = len(markers) > MAX_MARKERS
        by_index = {item["message_index"]: item for item in markers[:MAX_MARKERS]}
        for anchor in ("first_user", "last_assistant"):
            for item in _items(conn, session_id, anchor):
                existing = by_index.get(item["message_index"])
                if existing:
                    kinds = set(existing["kinds"] + item["kinds"])
                    existing["kinds"] = [kind for kind in _KIND_ORDER if kind in kinds]
                else:
                    by_index[item["message_index"]] = item
    if index_revision(indexer) != revision:
        raise ValueError("index_revision_changed: reload the conversation")
    result.update(items=sorted(by_index.values(), key=lambda item: item["message_index"]),
                  total_messages=total, indexed_messages=total,
                  partial=truncated, truncated=truncated)
    coverage = getattr(indexer, "_coverage", {}).get(session_id)
    if coverage and coverage.get("content_status") != "decoded_text":
        result.update(partial=True, content_status=coverage.get("content_status", "unknown"))
    return result
