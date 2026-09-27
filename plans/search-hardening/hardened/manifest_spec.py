"""Construction-defined independent expectations: no imports from product code.

Store identity protocol: SHA256(UTF-8 JSON [system, source, resolved source root]),
using ensure_ascii=False and default separators. The browser uses these same
whole provider roots (.codex/sessions and .claude/projects), not a child folder.
G1/G2 record current observable behavior; they are not a ranking product decision.
"""
import hashlib
import json


def manifest(root):
    roots = {'codex': root / 'home/.codex/sessions', 'claude': root / 'home/.claude/projects'}
    stores = {src: hashlib.sha256(json.dumps(['linux', src, str(path.resolve())], ensure_ascii=False).encode()).hexdigest() for src, path in roots.items()}
    def snippet(index, role, text, truncated=False):
        return {'message_index': index, 'role': role, 'text': text, 'truncated': truncated}
    def item(src, sid, snippets, status='matched'):
        return {'system': 'linux', 'source': src, 'store_id': stores[src], 'id': sid, 'snippet_status': status, 'snippets': snippets}
    def case(name, query, items, **kwargs):
        return {'name': name, 'query': query, 'items': items, 'errors': [], 'partial': False, 'truncated': False,
                'pagination_status': 'available', 'freshness': 'unknown', **kwargs}
    alpha = lambda snaps: item('codex', 'alpha-0001', snaps)
    claude = item('claude', 'alpha-0001', [snippet(0, 'user', 'sharedneedle claude source introduction')])
    literal = item('codex', 'literal-0001', [snippet(1, 'assistant', 'under_score percent%done slash\\path')])
    cases = [
        case('duplicate_ids_distinct_stores', 'sharedneedle', [claude, alpha([snippet(0, 'user', 'sharedneedle codex source introduction')])]),
        case('two_million_tail', 'after2mneedle', [alpha([snippet(1, 'assistant', 'x' * 70 + 'after2mneedle 后置系统', True)])]),
        case('chinese_two_million_tail', '后置系统', [alpha([snippet(1, 'assistant', 'x' * 56 + 'after2mneedle 后置系统', True)])]),
        case('8192_tail', 'tailneedle', [alpha([snippet(3, 'assistant', 'y' * 70 + 'tailneedle' + 'y' * 160, True)])]),
        case('chinese_after_context', '双千兆', [alpha([snippet(4, 'assistant', '在双千兆网卡上验证 OpenWrt 前先核对驱动')])]),
        case('context_excluded', 'ctxonlyneedle', []),
        case('literal_underscore', 'under_score', [literal]),
        case('literal_percent', 'percent%done', [literal]),
        case('literal_backslash', 'slash\\path', [literal]),
        case('ascii_fold', 'TAILNEEDLE', [alpha([snippet(3, 'assistant', 'y' * 70 + 'tailneedle' + 'y' * 160, True)])]),
        case('G1_non_ascii_upper', 'CAFÉ', []),
        case('G1_non_ascii_exact', 'café', [alpha([snippet(5, 'assistant', 'Café café Ωω 🎯 end')])]),
        case('metadata_only', 'cwdmetaneedle', [item('codex', 'metadata-0001', [], 'metadata_match_or_excerpt_unavailable')]),
        case('cross_message_AND', 'crosstermone crosstermtwo', [item('codex', 'cross-0001', [snippet(0, 'user', 'crosstermone first'), snippet(1, 'assistant', 'crosstermtwo second')])]),
        case('G2_early_any_term_order', 'gammaterm1 gammaterm2', [item('codex', 'delta-0001', [snippet(i + 1, 'assistant', f'Weak {i} gammaterm1') for i in range(3)])]),
        case('clean_no_match', 'doesnotexistneedle', []),
        case('source_query_error', 'sharedneedle', [claude], fault='codex_query', errors=[{'system': 'linux', 'source': 'codex', 'error': 'source_schema_unavailable'}], partial=True, pagination_status='restart_after_source_error'),
        case('snippet_query_error', '双千兆', [item('codex', 'alpha-0001', [], 'query_budget_exceeded')], fault='snippet_query', partial=True),
        case('pagination_25', 'paginationneedle', [item('codex', f'page-{i:02}', [snippet(0, 'user', f'paginationneedle case {i:02}')]) for i in range(24, -1, -1)]),
    ]
    return {'schema_version': 1, 'roots': {k: str(v) for k, v in roots.items()}, 'cases': cases,
            'deep_message': {'source': 'codex', 'id': 'delta-0001', 'index': 2106, 'text': 'gammaterm1 gammaterm2 完整短语在深处'},
            'scope': 'synthetic Codex and Claude; current G1/G2 observations, no product change'}
