import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from aiwh import skill_evals  # noqa: E402
from aiwh.skill_evals import (DEFAULT_PROVIDER, build_promptfoo_config, eval_coverage,  # noqa: E402
                              load_evals, resolve_provider, validate_evals,
                              write_promptfoo_config)

CASE = {'description': 'd', 'prompt': 'p', 'assert': [{'type': 'icontains', 'value': 'x'}]}


class ConfigTests(unittest.TestCase):
    def test_default_provider_and_env_and_argument_precedence(self):
        self.assertEqual(resolve_provider(None, env={}), DEFAULT_PROVIDER)
        self.assertEqual(resolve_provider(None, env={'AIWH_EVAL_PROVIDER': 'ollama:chat:qwen'}),
                         'ollama:chat:qwen')
        self.assertEqual(resolve_provider('x:y', env={'AIWH_EVAL_PROVIDER': 'ollama:chat:qwen'}), 'x:y')

    def test_config_uses_skill_body_as_system_prompt(self):
        cfg = build_promptfoo_config(['wb-debug-rigorous'], provider='ollama:chat:test')
        self.assertEqual(cfg['providers'], ['ollama:chat:test'])
        self.assertTrue(cfg['tests'])
        for test in cfg['tests']:
            self.assertTrue(test['description'].startswith('wb-debug-rigorous: '))
            self.assertIn('## Procedure', test['vars']['skill'])
            self.assertNotIn('name: wb-debug-rigorous', test['vars']['skill'])
            self.assertTrue(test['assert'])
        self.assertIn('skill | dump', cfg['prompts'][0])

    def test_env_provider_is_used(self):
        with mock.patch.dict('os.environ', {'AIWH_EVAL_PROVIDER': 'ollama:chat:env'}):
            self.assertEqual(build_promptfoo_config(['wb-pr-release'])['providers'], ['ollama:chat:env'])

    def test_skills_without_evals_are_skipped_and_listed(self):
        meta = build_promptfoo_config()['metadata']
        self.assertGreaterEqual(len(meta['aiwh_skills_with_evals']), 8)
        self.assertTrue(meta['aiwh_skills_skipped'])
        self.assertFalse(set(meta['aiwh_skills_with_evals']) & set(meta['aiwh_skills_skipped']))

    def test_unknown_skill_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Unknown skill'):
            build_promptfoo_config(['nope'])

    def test_write_is_lf_yaml_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / 'sub' / 'promptfooconfig.yaml'
            cfg = write_promptfoo_config(target, ['wb-pr-release'])
            raw = target.read_bytes()
            self.assertNotIn(b'\r', raw)
            self.assertEqual(yaml.safe_load(raw.decode('utf-8'))['tests'], cfg['tests'])

    def test_coverage(self):
        cov = eval_coverage()
        self.assertIn('wb-debug-rigorous', cov['with_evals'])
        self.assertEqual(len(cov['with_evals']) + len(cov['without']), len(skill_evals.registry()['skills']))
        self.assertEqual(eval_coverage(['wb-pr-release'])['without'], [])

    def test_shipped_evals_are_valid(self):
        skills = skill_evals.registry()['skills']
        for name in eval_coverage()['with_evals']:
            self.assertTrue(load_evals(skills[name]), name)


class ValidationTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(validate_evals([CASE]), [CASE])

    def test_invalid_shapes(self):
        bad = {
            'top level': {},
            'non-empty list': [],
            'case 1 must be a mapping': ['x'],
            'unknown keys': [{**CASE, 'extra': 1}],
            'prompt must be': [{**CASE, 'prompt': ' '}],
            'description must be': [{k: v for k, v in CASE.items() if k != 'description'}],
            'assert must be a non-empty list': [{**CASE, 'assert': []}],
            'string type': [{**CASE, 'assert': [{'value': 'x'}]}],
            'requires a value': [{**CASE, 'assert': [{'type': 'icontains'}]}],
            'duplicate description': [CASE, CASE],
        }
        for message, data in bad.items():
            with self.subTest(message), self.assertRaisesRegex(ValueError, message):
                validate_evals(data, 'src.yaml')

    def test_load_reports_path_and_yaml_errors(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(load_evals(d))
            (Path(d) / 'evals.yaml').write_text('- [unclosed', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'evals.yaml'):
                load_evals(d)


if __name__ == '__main__':
    unittest.main()
