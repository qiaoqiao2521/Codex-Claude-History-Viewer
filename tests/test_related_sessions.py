import copy
from pathlib import Path
import random
import sys
import unittest


REPO_DIR = Path(__file__).resolve().parents[1]
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from history_core.related_sessions import annotate_related_sessions


def session(sid, title='Repair large session search', project='/project', **extra):
    return dict(system='linux', source='codex', store_id='codex-store', id=sid,
                title=title, project=project, **extra)


def identity(item):
    return tuple(item[key] for key in ('system', 'source', 'store_id', 'id'))


class RelatedSessionTests(unittest.TestCase):
    def test_exact_title_groups_without_mutating_or_reordering_records(self):
        items = [session('b'), session('a'), session('different', title='Fix login callback')]
        items[0]['snippets'] = [{'message_index': 4, 'text': 'failure then retry'}]
        original = copy.deepcopy(items)
        result = annotate_related_sessions(items)
        self.assertEqual(items, original)
        self.assertEqual([identity(item) for item in result], [identity(item) for item in items])
        group = result[0]['related_group']
        self.assertEqual(group, result[1]['related_group'])
        self.assertEqual(group['total'], 2)
        self.assertIn('不代表同一任务', group['reason'])
        self.assertNotIn('related_group', result[2])
        for before, after in zip(items, result):
            self.assertEqual(before, {key: value for key, value in after.items() if key != 'related_group'})

    def test_title_normalization_preserves_technical_punctuation(self):
        items = [session('a', 'Ｆｉｘ  Ｃ＋＋ cache'), session('b', 'fix c++\tcache'),
                 session('c', 'fix c cache')]
        result = annotate_related_sessions(items)
        self.assertEqual(result[0]['related_group'], result[1]['related_group'])
        self.assertNotIn('related_group', result[2])

    def test_same_project_or_same_file_is_not_enough(self):
        files = '{"local":[{"path":"app.py"}]}'
        items = [session('a', 'Repair search', files_touched_json=files),
                 session('b', 'Improve search ranking', files_touched_json=files),
                 session('c', 'Repair payment callback', files_touched_json=files)]
        self.assertTrue(all('related_group' not in item for item in annotate_related_sessions(items)))

    def test_different_projects_are_never_joined(self):
        items = [session('a', project='/one'), session('b', project='/two'),
                 session('c', project='/one/'), session('d', project='/one/../one')]
        self.assertTrue(all('related_group' not in item for item in annotate_related_sessions(items)))

    def test_missing_project_or_identity_does_not_create_false_group(self):
        for field, value in [('project', ''), ('project', '  '), ('project', None),
                             ('store_id', ''), ('source', None), ('system', ''), ('id', '')]:
            with self.subTest(field=field, value=value):
                items = [session('a'), session('b')]
                for item in items:
                    item[field] = value
                self.assertTrue(all('related_group' not in item for item in annotate_related_sessions(items)))

    def test_generic_import_and_placeholder_titles_do_not_group(self):
        for title in ['Imported', 'Referenced ChatGPT conversation', 'ReferencedChatGPT',
                      'New conversation', 'New Chat 123', 'Untitled session',
                      'Session 01aabcde', '继续', '继续执行', '开始执行', '你好',
                      '导入会话', '2026-09-27', 'a' * 513, '🙂🙂🙂🙂', '', None]:
            with self.subTest(title=title):
                self.assertTrue(all('related_group' not in item for item in
                                    annotate_related_sessions([session('a', title), session('b', title)])))

    def test_distinct_source_and_store_identities_survive_shared_session_ids(self):
        items = [session('same-id'), session('same-id'), session('same-id'), session('same-id')]
        items[1]['source'], items[1]['store_id'] = 'claude', 'claude-store'
        items[2]['store_id'] = 'other-codex-store'
        items[3]['system'] = 'wsl'
        result = annotate_related_sessions(items)
        self.assertEqual(len(result), 4)
        self.assertEqual(len({identity(item) for item in result}), 4)
        self.assertEqual({item['related_group']['total'] for item in result}, {4})
        self.assertEqual(len({item['related_group']['id'] for item in result}), 1)

    def test_duplicate_identity_alone_does_not_establish_a_second_session(self):
        items = [session('a'), session('a')]
        self.assertEqual(annotate_related_sessions(items), items)

    def test_deterministic_annotation_under_arbitrary_input_order(self):
        items = [session(str(n), '修复大文件检索' if n % 2 else '验证登录回调') for n in range(90)]
        expected = {identity(item): item['related_group'] for item in annotate_related_sessions(items)}
        random.Random(42).shuffle(items)
        actual = {identity(item): item['related_group'] for item in annotate_related_sessions(items)}
        self.assertEqual(actual, expected)

    def test_full_candidate_annotations_survive_page_slicing(self):
        result = annotate_related_sessions([session(str(n)) for n in range(65)])
        pages = [result[offset:offset + 20] for offset in range(0, len(result), 20)]
        self.assertEqual(sum(map(len, pages)), 65)
        self.assertEqual({item['related_group']['total'] for page in pages for item in page}, {65})
        self.assertEqual(len({item['related_group']['id'] for page in pages for item in page}), 1)

    def test_large_bounded_candidate_set_retains_all_rows(self):
        items = [session(str(n), 'Topic ' + str(n % 200)) for n in range(6500)]
        result = annotate_related_sessions(items)
        self.assertEqual([identity(item) for item in result], [identity(item) for item in items])
        self.assertTrue(all(item['related_group']['total'] in (32, 33) for item in result))

    def test_no_time_cutoff_and_existing_annotations_are_recomputed(self):
        items = [session('a', updated_at=1), session('b', updated_at=2_000_000_000_000)]
        result = annotate_related_sessions(items)
        self.assertEqual(result, annotate_related_sessions(result))
        result[1]['title'] = 'A completely different question'
        self.assertTrue(all('related_group' not in item for item in annotate_related_sessions(result)))

    def test_empty_input(self):
        self.assertEqual(annotate_related_sessions([]), [])


if __name__ == '__main__':
    unittest.main()
