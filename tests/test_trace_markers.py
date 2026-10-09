"""Marker detection records observable events, not execution or effectiveness."""

import hashlib
import json
import unittest

from history_core.trace_markers import (
    DECLARATION_CHARS,
    DECLARED_MARKER_PREFIX,
    FIELD_CHARS,
    LEARNING_OUTPUT_STYLE_PREFIX,
    declared_skill_markers,
    skill_tool_markers,
    style_markers,
)


class TraceMarkerTests(unittest.TestCase):
    def declaration(self, **fields):
        return DECLARED_MARKER_PREFIX + json.dumps(fields)

    def test_native_learning_context_hashes_the_complete_original_prompt(self):
        text = '\n' + LEARNING_OUTPUT_STYLE_PREFIX + '\nAdditional installed instructions.\n'
        for role in ('system', 'developer'):
            with self.subTest(role=role):
                marker, = style_markers(role, text)
                self.assertEqual(marker, {
                    'kind': 'output_style', 'name': 'learning-output-style',
                    'event': 'context_injected', 'evidence_origin': 'recorded_prompt',
                    'content_hash': hashlib.sha256(text.encode()).hexdigest(),
                })
        self.assertNotEqual(style_markers('system', text)[0]['content_hash'],
                            style_markers('system', text.strip())[0]['content_hash'])

    def test_learning_style_mentions_examples_and_config_are_not_injection(self):
        for role, text in (
            ('assistant', LEARNING_OUTPUT_STYLE_PREFIX),
            ('user', LEARNING_OUTPUT_STYLE_PREFIX),
            ('tool', LEARNING_OUTPUT_STYLE_PREFIX),
            ('developer', 'Example:\n' + LEARNING_OUTPUT_STYLE_PREFIX),
            ('system', '```text\n' + LEARNING_OUTPUT_STYLE_PREFIX + '\n```'),
            ('system', 'learning-output-style enabled=true'),
            ('system', '★ Insight\nExplanation'),
            ('developer', LEARNING_OUTPUT_STYLE_PREFIX.replace("'learning'", 'learning')),
            ('developer', None),
        ):
            with self.subTest(role=role, text=text):
                self.assertEqual(style_markers(role, text), [])

    def test_native_skill_invocation_is_a_request_with_unknown_path_and_version(self):
        for tool, raw in (
            ('Skill', {'skill': 'plugin:tool-reuse', 'args': 'token=ARGUMENT_SECRET'}),
            ('sKiLl', '{"skill":"plugin:tool-reuse","args":"token=ARGUMENT_SECRET"}'),
        ):
            with self.subTest(tool=tool):
                marker, = skill_tool_markers(tool, raw)
                self.assertEqual(marker['kind'], 'skill')
                self.assertEqual(marker['name'], 'plugin:tool-reuse')
                self.assertEqual(marker['event'], 'invocation_requested')
                self.assertEqual(marker['evidence_origin'], 'native_tool_call')
                self.assertEqual(marker['path'], 'unknown')
                self.assertEqual(marker['version'], 'unknown')
                self.assertNotIn('ARGUMENT_SECRET', json.dumps(marker))
                self.assertNotIn('args', marker)

    def test_skill_reads_mentions_other_tools_and_malformed_inputs_are_not_invocations(self):
        cases = [
            ('Read', {'file_path': '/skills/tool-reuse/SKILL.md'}),
            ('exec_command', {'cmd': 'cat /skills/tool-reuse/SKILL.md'}),
            ('plugin:Skill', {'skill': 'tool-reuse'}),
            (' Skill ', {'skill': 'tool-reuse'}),
            ('Skill', {'name': 'tool-reuse'}),
            ('Skill', {'skill': ' \n '}),
            ('Skill', {'skill': 42}),
            ('Skill', 'I will use tool-reuse'),
            ('Skill', '[{"skill":"tool-reuse"}]'),
            ('Skill', 'null'),
            ('Skill', '[' * 2000),
            ('Skill', None),
            (None, {'skill': 'tool-reuse'}),
        ]
        for tool, raw in cases:
            with self.subTest(tool=tool, raw_type=type(raw).__name__):
                self.assertEqual(skill_tool_markers(tool, raw), [])

    def test_whole_assistant_declaration_preserves_declared_identity_without_verifying_it(self):
        text = self.declaration(name='plugin:tool-reuse', path='/skills/tool-reuse/SKILL.md',
                                version='v2', content_hash='AB' * 32)
        marker, = declared_skill_markers('assistant', text)
        self.assertEqual(marker['name'], 'plugin:tool-reuse')
        self.assertEqual(marker['path'], '/skills/tool-reuse/SKILL.md')
        self.assertEqual(marker['version'], 'v2')
        self.assertEqual(marker['content_hash'], 'ab' * 32)
        self.assertEqual(marker['event'], 'agent_declared')
        self.assertEqual(marker['evidence_origin'], 'agent_marker')
        self.assertEqual(declared_skill_markers('assistant', ' \n' + text + '\n '), [marker])

    def test_skill_alias_and_missing_declared_path_version_remain_unknown(self):
        marker, = declared_skill_markers('assistant', self.declaration(skill='tool-reuse'))
        self.assertEqual(marker['name'], 'tool-reuse')
        self.assertEqual(marker['path'], 'unknown')
        self.assertEqual(marker['version'], 'unknown')
        self.assertNotIn('content_hash', marker)

    def test_declaration_in_user_tool_result_normal_prose_or_fence_is_not_a_marker(self):
        text = self.declaration(name='tool-reuse')
        for role, candidate in (
            ('user', text), ('tool', text), ('system', text), ('developer', text),
            ('assistant', 'I used the skill.\n' + text),
            ('assistant', text + '\nTask complete.'),
            ('assistant', '```json\n' + text + '\n```'),
            ('assistant', 'Read /skills/tool-reuse/SKILL.md'),
            ('assistant', '★ Insight\nTool reuse improved the result.'),
            ('assistant', 'learning-output-style'),
        ):
            with self.subTest(role=role, candidate=candidate):
                self.assertEqual(declared_skill_markers(role, candidate), [])

    def test_invalid_declaration_fields_are_rejected_without_coercion(self):
        cases = [
            {}, {'name': ''}, {'name': None}, {'name': ['tool-reuse']},
            {'name': 'tool-reuse', 'skill': 'other'},
            {'name': 'tool-reuse', 'skill': 2},
            {'name': 'tool-reuse', 'path': 42},
            {'name': 'tool-reuse', 'version': ''},
            {'name': 'tool-reuse', 'content_hash': 'sha256:' + 'a' * 64},
            {'name': 'tool-reuse', 'content_hash': 'a' * 63},
            {'name': 'tool-reuse', 'content_hash': None},
            {'name': 'tool-reuse', 'args': 'token=SECRET'},
            {'name': 'tool-reuse', 'effective': True},
        ]
        for fields in cases:
            with self.subTest(fields=fields):
                self.assertEqual(declared_skill_markers('assistant', self.declaration(**fields)), [])
        for body in ('[]', 'null', '{"name":"one","name":"two"}', '[' * 2000,
                     '{"name":"one"} {"name":"two"}'):
            with self.subTest(body=body[:80]):
                self.assertEqual(declared_skill_markers('assistant', DECLARED_MARKER_PREFIX + body), [])

    def test_declared_message_limit_applies_before_trimming_or_parsing(self):
        short = self.declaration(name='tool-reuse')
        exact = short + ' ' * (DECLARATION_CHARS - len(short))
        self.assertEqual(len(declared_skill_markers('assistant', exact)), 1)
        self.assertEqual(declared_skill_markers('assistant', exact + ' '), [])

    def test_secret_fields_are_redacted_before_clipping_and_have_explicit_limits(self):
        secret = 'SYNTHETIC_SECRET_' + 'S' * 300
        name = 'n' * 110 + '\ntoken=' + secret
        marker, = skill_tool_markers('Skill', {'skill': name, 'args': secret})
        self.assertIn('[REDACTED]', marker['name'])
        self.assertNotIn('SYNTHETIC_SECRET', json.dumps(marker))
        fields = {key: key[0] * 300 for key in ('name', 'path', 'version')}
        declared, = declared_skill_markers('assistant', self.declaration(**fields))
        for key in fields:
            self.assertEqual(len(declared[key]), FIELD_CHARS)
            self.assertTrue(declared[key + '_truncated'])
        declared, = declared_skill_markers('assistant', self.declaration(
            name='token=' + secret, path='password=' + secret, version='secret=' + secret))
        self.assertNotIn('SYNTHETIC_SECRET', json.dumps(declared))
        self.assertEqual(declared['path'], 'password=[REDACTED]')
        self.assertFalse(declared['path_truncated'])

    def test_events_do_not_claim_effect_installation_or_successful_execution(self):
        markers = style_markers('system', LEARNING_OUTPUT_STYLE_PREFIX)
        markers += skill_tool_markers('Skill', {'skill': 'tool-reuse'})
        markers += declared_skill_markers('assistant', self.declaration(name='tool-reuse'))
        for marker in markers:
            with self.subTest(event=marker['event']):
                self.assertNotIn('effective', marker)
                self.assertNotIn('execution_status', marker)
                self.assertNotIn('installed', marker)
                self.assertNotIn('plugin_version', marker)
        self.assertEqual({marker['event'] for marker in markers},
                         {'context_injected', 'invocation_requested', 'agent_declared'})


if __name__ == '__main__':
    unittest.main()
