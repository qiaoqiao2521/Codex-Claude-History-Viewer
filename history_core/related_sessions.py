"""Conservative, presentation-only clues connecting bounded session candidates.

Only a nonempty exact project and an informative exact normalized title qualify.
Titles use Unicode NFKC, case folding and whitespace normalization; punctuation
is retained, so code names such as C and C++ remain different. There is no fuzzy
similarity, shared-file inference, transitive clustering, or time-window cutoff.
An older discussion of the same subject can still be useful, but this clue does
not establish that the sessions performed the same task.

Call before pagination, using all candidates in the current bounded query.
Counts describe those candidates, not the entire source history. Membership
changes may change the group ID; existing revision-bound pagination handles that
boundary. Work is linear in title text plus sorting the grouped member IDs.
"""

from collections import defaultdict
import hashlib
import json
import re
import unicodedata


_GENERIC_TITLES = frozenset({
    'chat', 'conversation', 'session', 'new', 'untitled', 'imported',
    'continue', 'resume', 'ok', 'okay', 'yes', 'hello', 'hi',
    '继续', '继续执行', '开始', '开始执行', '执行', '完成', '好的', '你好',
    '新建', '新建会话', '未命名', '会话', '对话', '聊天', '导入',
})
_GENERIC_PREFIXES = (
    'referencedchatgptconversation', 'referencedchatgpt',
    'importedchatgptconversation', 'importedchatgpt',
    'importedconversation', 'importedsession', 'importedchat',
    'newconversation', 'newsession', 'newchat', 'untitled',
    '新会话', '新对话', '新聊天', '导入对话', '导入会话',
)
_FALLBACK_TITLE = re.compile(r'(?:session|conversation|chat)[\s_-]+[a-f0-9-]{4,}$')
_REASON = '同一项目中的标题相同（规范化后）；这是相关线索，不代表同一任务'


def _title(value):
    if not isinstance(value, str) or len(value) > 512:
        return ''
    return ' '.join(unicodedata.normalize('NFKC', value).split()).casefold()


def _informative_title(title):
    # Removing punctuation is only for rejecting defaults, never for matching.
    compact = ''.join(char for char in title if char.isalnum())
    return (len(compact) >= 4 and compact not in _GENERIC_TITLES
            and not compact.startswith(_GENERIC_PREFIXES)
            and not _FALLBACK_TITLE.fullmatch(title)
            and not all(char in '0123456789abcdef-' for char in title))


def _identity(item):
    values = tuple(item.get(key) for key in ('system', 'source', 'store_id', 'id'))
    return values if all(isinstance(value, str) and value.strip() for value in values) else None


def annotate_related_sessions(items):
    """Return shallow item copies in their original order, without losing rows.

    Each group of at least two distinct full source identities receives
    ``related_group: {id, label, reason, total}``. ``label`` is the normalized
    shared title; ``total`` counts unique identities in the complete candidate
    set supplied by the caller. Ungrouped items omit the annotation. Inputs are
    not mutated, stale annotations are recomputed, and all other fields survive.

    Required identity fields: system, source, store_id, id (nonempty strings).
    ``project`` must be a nonblank string and is compared exactly, without path
    normalization or filesystem access. ``files_touched_json`` is not consumed:
    shared files alone cannot tell whether two conversations discuss one task.
    """
    result = [dict(item) for item in items]
    buckets = defaultdict(list)
    for position, item in enumerate(result):
        item.pop('related_group', None)
        project = item.get('project')
        identity = _identity(item)
        title = _title(item.get('title'))
        if (not isinstance(project, str) or not project.strip() or identity is None
                or not _informative_title(title) or title == _title(item.get('id'))):
            continue
        buckets[(project, title)].append((position, identity))

    for (project, title), members in buckets.items():
        identities = sorted({identity for _, identity in members})
        if len(identities) < 2:
            continue
        payload = json.dumps(['related-title-v1', project, title, identities],
                             ensure_ascii=False, separators=(',', ':'))
        group_id = 'related-' + hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]
        for position, _ in members:
            result[position]['related_group'] = {
                'id': group_id, 'label': title, 'reason': _REASON, 'total': len(identities),
            }
    return result
