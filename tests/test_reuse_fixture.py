"""Regression gates for frozen questions, corpus integrity and score calculation."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from history_core.sources import parse_codex_session_file, parse_claude_session_file
from scripts.reuse_fixture import (QUESTIONS, TARGET_BYTES, generate_dataset,
                                  load_questions, session_bytes, sha256, verify_dataset)
from scripts.run_reuse_benchmark import evaluate_responses, expected_stores, nearest_rank


class ReuseFixtureTests(unittest.TestCase):
    def test_frozen_tasks_are_complete_and_do_not_rewrite_hard_queries(self):
        spec = load_questions()
        self.assertEqual(sha256(QUESTIONS), 'aa9be670049bd3ff4eb13e6f41eb327849cf43698d399a3085985d1ed4417b82')
        self.assertEqual(len(spec['queries']), 20)
        self.assertEqual(len(spec['negatives']), 4)
        self.assertEqual(len(spec['projects']), 3)
        self.assertEqual(sum(q['kind'] == 'paraphrase' for q in spec['queries']), 4)
        self.assertEqual(len(set(q['id'] for q in spec['queries'] + spec['negatives'])), 24)
        self.assertEqual(spec['thresholds']['positive_hit_at_5'], .8)
        self.assertEqual(spec['thresholds']['http_p95_ms'], 1000)
        self.assertEqual(spec['projects'][0].split('/')[-1], spec['projects'][1].split('/')[-1])
        targets = {(s['source'], s['id']): s for s in spec['sessions']}
        for q in spec['queries']:
            record = targets[q['source'], q['session']]
            self.assertIn(q['message_index'], dict(record['evidence']))
        self.assertIn(('codex', 'shared-repair-01'), targets)
        self.assertIn(('claude', 'shared-repair-01'), targets)

    def test_both_native_parsers_observe_exact_message_targets_and_size(self):
        spec = load_questions()
        with tempfile.TemporaryDirectory() as tmp:
            for number, record in enumerate(spec['sessions']):
                path = Path(tmp) / (record['source'] + '.jsonl')
                data = session_bytes(record['source'], record['id'], spec['projects'][record['project']], record['evidence'], number)
                self.assertEqual(len(data), TARGET_BYTES)
                self.assertEqual(data, session_bytes(record['source'], record['id'], spec['projects'][record['project']], record['evidence'], number))
                path.write_bytes(data)
                parser = parse_codex_session_file if record['source'] == 'codex' else parse_claude_session_file
                parsed = parser(path)
                self.assertEqual(parsed['id'], record['id'])
                self.assertEqual(parsed['message_count'], 20)
                self.assertEqual(len(parsed['messages']), 20)
                for index, text in record['evidence']:
                    self.assertIn(text, parsed['messages'][index]['text'])

    def test_manifest_detects_tampering_and_rejects_small_performance_corpus(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'corpus'
            manifest = generate_dataset(root)
            self.assertEqual(manifest['counts'], {'codex': 5, 'claude': 5})
            self.assertEqual(verify_dataset(root)['dataset_sha256'], manifest['dataset_sha256'])
            with self.assertRaisesRegex(ValueError, '10k'):
                verify_dataset(root, require_performance=True)
            with self.assertRaisesRegex(ValueError, 'empty'):
                generate_dataset(root)
            target = root / manifest['files'][0]['path']
            data = target.read_bytes()
            target.write_bytes(data.replace(b'xxxxxxxx', b'yyyyyyyy', 1))
            with self.assertRaisesRegex(ValueError, 'file_changed'):
                verify_dataset(root)

    def _responses(self):
        spec = load_questions()
        responses = {}
        for q in spec['queries']:
            responses[q['id']] = {'items': [{'system': spec['system'], 'source': q['source'], 'store_id': expected_stores(spec, '/synthetic-fixture')[q['source']],
                'id': q['session'], 'snippets': [{'message_index': q['message_index'], 'text': 'evidence'}]}]}
        for q in spec['negatives']:
            responses[q['id']] = {'items': []}
        return spec, responses

    def test_score_requires_source_store_session_and_message_not_just_title(self):
        spec, good = self._responses()
        self.assertTrue(evaluate_responses(spec, good, expected_stores(spec, '/synthetic-fixture'))['pass'])
        for field, replacement in [('system', 'wrong'), ('source', 'wrong'), ('store_id', 'wrong'), ('id', 'wrong'), ('snippets', [])]:
            bad = copy.deepcopy(good)
            for q in spec['queries'][:5]:
                bad[q['id']]['items'][0][field] = replacement
            self.assertFalse(evaluate_responses(spec, bad, expected_stores(spec, '/synthetic-fixture'))['pass'], field)
        # A target at rank six is not a Hit@5.
        bad = copy.deepcopy(good)
        for q in spec['queries'][:5]:
            bad[q['id']]['items'] = [{'id': 'distractor'}] * 5 + bad[q['id']]['items']
        self.assertFalse(evaluate_responses(spec, bad, expected_stores(spec, '/synthetic-fixture'))['pass'])

    def test_negatives_and_payload_bounds_are_independent_hard_gates(self):
        spec, bad = self._responses()
        bad['N01']['items'] = [{'id': 'manufactured'}]
        self.assertFalse(evaluate_responses(spec, bad, expected_stores(spec, '/synthetic-fixture'))['pass'])
        spec, bad = self._responses()
        bad['Q01']['items'][0]['snippets'][0]['text'] = '证' * 241
        self.assertFalse(evaluate_responses(spec, bad, expected_stores(spec, '/synthetic-fixture'))['pass'])
        spec, bad = self._responses()
        bad['Q01']['items'] *= 21
        self.assertFalse(evaluate_responses(spec, bad, expected_stores(spec, '/synthetic-fixture'))['pass'])

    def test_nearest_rank_uses_95th_sample_and_preserves_slow_results(self):
        self.assertEqual(nearest_rank(list(range(1, 101))), 95)
        self.assertEqual(nearest_rank([1] * 94 + [1001] * 6), 1001)
        with self.assertRaises(ValueError):
            nearest_rank([])

    def test_store_locator_resolves_real_root_and_matches_public_contract(self):
        from history_core.evidence import source_store_id
        spec = load_questions()
        with tempfile.TemporaryDirectory() as tmp:
            stores = expected_stores(spec, tmp)
            for source, details in spec['stores'].items():
                indexer = SimpleNamespace(sessions_dir=Path(tmp) / details['relative_root'])
                self.assertEqual(stores[source], source_store_id('linux', source, indexer))
                self.assertEqual(len(stores[source]), 64)
                self.assertNotEqual(stores[source], 'linux')
            self.assertNotEqual(stores, expected_stores(spec, Path(tmp) / 'another-root'))


if __name__ == '__main__':
    unittest.main()
