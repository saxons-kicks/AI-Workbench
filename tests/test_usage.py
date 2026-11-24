import json
import tempfile
import unittest
from pathlib import Path

from aiwh.usage import encode_project, format_usage, skill_token_comparison, usage_report


def line(ts, model, i, o, cw, cr, mid=None):
    msg = {'model': model, 'content': 'SECRET', 'usage': {
        'input_tokens': i, 'output_tokens': o,
        'cache_creation_input_tokens': cw, 'cache_read_input_tokens': cr}}
    if mid:
        msg['id'] = mid
    row = {'type': 'assistant', 'timestamp': ts, 'message': msg}
    if mid:
        row['requestId'] = 'r-' + mid
    return json.dumps(row)


class UsageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / 'projects'
        proj = self.root / encode_project('C:\\projetos\\X')
        other = self.root / 'C--projetos-Y'
        proj.mkdir(parents=True)
        other.mkdir()
        (proj / 's1.jsonl').write_text('\n'.join([
            line('2026-01-01T10:00:00Z', 'opus', 10, 5, 100, 1000),
            'not json {{{',
            json.dumps({'type': 'user', 'message': {'content': 'hi'}}),
            line('2026-01-02T10:00:00Z', 'sonnet', 1, 2, 3, 4, mid='a'),
            line('2026-01-02T10:00:01Z', 'sonnet', 1, 2, 3, 4, mid='a'),  # duplicate
        ]) + '\n', encoding='utf-8')
        (other / 's2.jsonl').write_text(line('2026-01-02T00:00:00Z', 'opus', 7, 0, 0, 0) + '\n',
                                        encoding='utf-8')

    def test_encode(self):
        self.assertEqual(encode_project('C:\\projetos\\X'), 'C--projetos-X')

    def test_totals_models_days(self):
        r = usage_report(self.root)
        self.assertEqual(r['sessions'], 2)
        self.assertEqual(r['totals']['input_tokens'], 18)
        self.assertEqual(r['by_model']['opus']['input_tokens'], 17)
        self.assertEqual(r['by_model']['sonnet']['messages'], 1)
        self.assertEqual(r['by_day']['2026-01-02']['input_tokens'], 8)
        self.assertEqual(r['totals']['total_tokens'], 18 + 7 + 103 + 1004)
        self.assertNotIn('SECRET', json.dumps(r))

    def test_project_and_since(self):
        r = usage_report(self.root, project='C:\\projetos\\X')
        self.assertEqual(r['totals']['input_tokens'], 11)
        r = usage_report(self.root, project='C--projetos-X', since='2026-01-02')
        self.assertEqual(r['totals']['input_tokens'], 1)
        self.assertEqual(usage_report(self.root, project='nope')['sessions'], 0)

    def test_missing_root_and_format(self):
        r = usage_report(Path(self._tmp.name) / 'missing')
        self.assertEqual(r['totals']['total_tokens'], 0)
        text = format_usage(usage_report(self.root))
        self.assertIn('opus', text)
        self.assertIn('2026-01-02', text)

    def test_skill_comparison(self):
        project = Path(self._tmp.name) / 'X'
        skill = project / '.claude' / 'skills' / 'demo'
        skill.mkdir(parents=True)
        (skill / 'SKILL.md').write_text('---\nname: demo\ndescription: A demo\n---\n' + 'body ' * 100,
                                        encoding='utf-8')
        r = skill_token_comparison(project, root=self.root)
        self.assertEqual(r['skill_count'], 1)
        self.assertGreater(r['body_tokens_if_all_loaded'], 100)
        empty = skill_token_comparison(Path(self._tmp.name) / 'none', root=self.root)
        self.assertEqual(empty['skill_count'], 0)


if __name__ == '__main__':
    unittest.main()
