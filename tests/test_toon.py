import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from aiwh.toon import dumps  # noqa: E402
from aiwh.handoff_export import export_handoff  # noqa: E402


class ToonEncoderTests(unittest.TestCase):
    def test_objects_and_primitive_arrays(self):
        self.assertEqual(dumps({'a': 1, 'b': None, 'tags': ['x', 'y'], 'e': []}),
                         'a: 1\nb: null\ntags[2]: x,y\ne[0]:\n')

    def test_tabular_array(self):
        text = dumps({'rows': [{'id': 1, 'n': 'a b'}, {'id': 2, 'n': 'c,d'}]})
        self.assertEqual(text, 'rows[2]{id,n}:\n  1,a b\n  2,"c,d"\n')

    def test_quotes_ambiguous_strings(self):
        text = dumps({'s': 'true', 'n': '42', 'colon': 'a: b', 'lead': ' x', 'dash': '-x', 'empty': ''})
        for line in ('s: "true"', 'n: "42"', 'colon: "a: b"', 'lead: " x"', 'dash: "-x"', 'empty: ""'):
            self.assertIn(line, text)

    def test_nested_and_mixed_lists(self):
        text = dumps({'o': {'k': {'z': 1}}, 'm': [{'k': {'z': 1}}, 3]})
        self.assertEqual(text, 'o:\n  k:\n    z: 1\nm[2]:\n  - k:\n      z: 1\n  - 3\n')

    def test_handoff_toon_is_smaller_than_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            subprocess.run(['git', 'init', '-q'], cwd=project, check=True)
            (project / 'README.md').write_text('# demo\n\n- [ ] T-1 first task\n', encoding='utf-8')
            toon = export_handoff(project, 'toon')['files']
            js = export_handoff(project, 'json')['files']['handoff.json']
            self.assertIn('handoff.toon', toon)
            self.assertTrue(toon['handoff.toon'].startswith('schema: aiwh-handoff/1\n'))
            self.assertLess(len(toon['handoff.toon']), len(js))
            self.assertEqual(json.loads(js)['schema'], 'aiwh-handoff/1')
            self.assertFalse((project / '.ai-workbench').exists())


if __name__ == '__main__':
    unittest.main()
