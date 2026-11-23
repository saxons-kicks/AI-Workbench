import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from aiwh.cli import _utf8_stdout, main  # noqa: E402
from aiwh import references as refs  # noqa: E402
from aiwh.references import (CATALOG_PATH, DESCRIPTION_LIMIT, document_is_current, reference_catalog,  # noqa: E402
                             references_markdown, validate_references, write_document)


def _catalog_with(**changes):
    """Copy of the real catalog with the first reference's fields replaced or extended."""
    data = json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
    key = next(iter(data['references']))
    data['references'][key].update(changes)
    return data


def _run(argv):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = main(argv)
    return code, output.getvalue()


class ValidateReferencesTests(unittest.TestCase):
    def test_real_catalog_is_valid(self):
        stats = validate_references(reference_catalog())
        self.assertGreater(stats['references'], 0)

    def test_null_group_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'group must be a non-empty string'):
            validate_references(_catalog_with(group=None))

    def test_blank_group_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'group must be a non-empty string'):
            validate_references(_catalog_with(group='   '))

    def test_string_group_is_accepted(self):
        self.assertTrue(validate_references(_catalog_with(group='Frameworks')))

    def test_string_areas_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'areas must be a list of strings'):
            validate_references(_catalog_with(areas='security'))

    def test_non_string_area_items_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'areas must be a list of strings'):
            validate_references(_catalog_with(areas=[1]))

    def test_non_list_risk_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'risk must be a list of strings'):
            validate_references(_catalog_with(risk='authorized-only'))

    def test_unknown_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unknown keys'):
            validate_references(_catalog_with(notes='typo'))

    def test_non_string_url_is_value_error(self):
        with self.assertRaisesRegex(ValueError, 'url must be a string'):
            validate_references(_catalog_with(url=123))

    def test_non_string_title_is_value_error(self):
        with self.assertRaisesRegex(ValueError, 'title must be a string'):
            validate_references(_catalog_with(title=['x']))


class ReferenceDocumentTests(unittest.TestCase):
    def test_write_uses_lf_and_matches_generated_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'REFERENCES.md'
            write_document(target)
            self.assertEqual(target.read_bytes(), references_markdown().encode('utf-8'))
            self.assertNotIn(b'\r', target.read_bytes())

    def test_check_detects_missing_equal_and_changed_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'REFERENCES.md'
            self.assertFalse(document_is_current(target))
            write_document(target)
            self.assertTrue(document_is_current(target))
            target.write_text(references_markdown() + 'drift\n', encoding='utf-8', newline='\n')
            self.assertFalse(document_is_current(target))

    def test_check_is_byte_strict_about_crlf(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'REFERENCES.md'
            target.write_bytes(references_markdown().replace('\n', '\r\n').encode('utf-8'))
            self.assertFalse(document_is_current(target))

    def test_cli_write_then_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'REFERENCES.md'
            code, _ = _run(['references', '--write', str(target)])
            self.assertEqual(code, 0)
            self.assertEqual(target.read_bytes(), references_markdown().encode('utf-8'))
            code, out = _run(['references', '--check', str(target)])
            self.assertEqual(code, 0)
            self.assertIn('Current', out)

    def test_cli_check_exits_one_when_out_of_date(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'REFERENCES.md'
            target.write_text('# stale\n', encoding='utf-8', newline='\n')
            code, out = _run(['references', '--check', str(target)])
            self.assertEqual(code, 1)
            self.assertIn('Out of date', out)

    def test_cli_check_exits_one_when_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            code, _ = _run(['references', '--check', str(Path(temporary) / 'absent.md')])
            self.assertEqual(code, 1)

    def test_cli_write_and_check_together_is_usage_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            code, _ = _run(['references', '--write', str(Path(temporary) / 'a.md'),
                            '--check', str(Path(temporary) / 'a.md')])
            self.assertEqual(code, 2)

    def test_stdout_markdown_uses_lf_newlines(self):
        buffer = io.BytesIO()
        wrapper = io.TextIOWrapper(buffer, encoding='cp1252', newline=None)
        with mock.patch.object(sys, 'stdout', wrapper):
            _utf8_stdout()
            print('line one')
            print('line two')
            wrapper.flush()
        self.assertEqual(buffer.getvalue(), b'line one\nline two\n')


def _tmp_catalog(test):
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    path = Path(tmp.name) / 'catalog.json'
    path.write_bytes(CATALOG_PATH.read_bytes())
    return path


def _entry(**changes):
    data = reference_catalog()
    category = next(iter(data['categories']))
    area = data['categories'][category]['areas'][0]
    return {'url': 'https://github.com/Some-Owner/New-Repo', 'category': category, 'areas': [area], **changes}


class AcceptReferenceTests(unittest.TestCase):
    def test_accept_adds_valid_entry_with_defaults_and_lf(self):
        path = _tmp_catalog(self)
        key = refs.accept_reference(_entry(), catalog_path=path, today='2026-01-02')
        self.assertEqual(key, 'some-owner-new-repo')
        data = json.loads(path.read_text(encoding='utf-8'))
        ref = data['references'][key]
        self.assertEqual(ref['kind'], 'repository')
        self.assertEqual(ref['title'], 'Some-Owner/New-Repo')
        self.assertEqual(ref['reviewed'], '2026-01-02')
        validate_references(data)
        raw = path.read_bytes()
        self.assertNotIn(b'\r\n', raw)
        self.assertTrue(raw.endswith(b'\n'))

    def test_non_github_defaults_to_site(self):
        path = _tmp_catalog(self)
        key = refs.accept_reference(_entry(url='https://example.org/guide'), catalog_path=path, today='2026-01-02')
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['references'][key]['kind'], 'site')

    def test_duplicate_incl_case_variant_is_rejected(self):
        path = _tmp_catalog(self)
        existing = next(iter(reference_catalog()['references'].values()))['url']
        for url in (existing, existing.upper().replace('HTTPS', 'https'), existing.lower() + '/'):
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, 'Already in catalog'):
                refs.accept_reference(_entry(url=url), catalog_path=path)
            self.assertEqual(path.read_bytes(), before)

    def test_sensitive_url_is_rejected(self):
        path = _tmp_catalog(self)
        with self.assertRaisesRegex(ValueError, 'Refusing'):
            refs.accept_reference(_entry(url='https://tokenized.play.google.com/x'), catalog_path=path)

    def test_credential_params_are_stripped(self):
        path = _tmp_catalog(self)
        key = refs.accept_reference(_entry(url='https://example.org/g?token=abc&q=1'), catalog_path=path)
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['references'][key]['url'],
                         'https://example.org/g?q=1')

    def test_invalid_entry_does_not_write(self):
        path = _tmp_catalog(self)
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            refs.accept_reference(_entry(category='nope'), catalog_path=path)
        with self.assertRaises(ValueError):
            refs.accept_reference({'url': ''}, catalog_path=path)
        self.assertEqual(path.read_bytes(), before)

    def test_description_is_truncated_and_stored(self):
        path = _tmp_catalog(self)
        key = refs.accept_reference(_entry(description='x ' * 400), catalog_path=path)
        desc = json.loads(path.read_text(encoding='utf-8'))['references'][key]['description']
        self.assertLessEqual(len(desc), DESCRIPTION_LIMIT)

    def test_key_collision_needs_explicit_key(self):
        path = _tmp_catalog(self)
        existing = next(iter(reference_catalog()['references']))
        with self.assertRaisesRegex(ValueError, 'already exists'):
            refs.accept_reference(_entry(key=existing), catalog_path=path)


class ReferenceKeyTests(unittest.TestCase):
    def test_github_and_site_keys(self):
        self.assertEqual(refs.reference_key('https://github.com/Owner/Repo.git'), 'owner-repo')
        self.assertEqual(refs.reference_key('https://www.GitHub.com/Owner/Repo/'), 'owner-repo')
        self.assertEqual(refs.reference_key('https://example.org/a/b?x=1'), 'example-org-a-b-x-1')


class DescriptionValidationTests(unittest.TestCase):
    def test_valid_description(self):
        self.assertTrue(validate_references(_catalog_with(description='Short text.')))

    def test_limit_boundary(self):
        self.assertTrue(validate_references(_catalog_with(description='x' * DESCRIPTION_LIMIT)))
        with self.assertRaisesRegex(ValueError, 'description must be'):
            validate_references(_catalog_with(description='x' * (DESCRIPTION_LIMIT + 1)))

    def test_blank_or_non_string_description(self):
        for bad in ('  ', '', 5, None):
            with self.assertRaisesRegex(ValueError, 'description must be'):
                validate_references(_catalog_with(description=bad))


class DecisionsTests(unittest.TestCase):
    def _write(self, name, text):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / name
        path.write_text(text, encoding='utf-8')
        return path

    def test_json_list_with_decision_field(self):
        path = self._write('d.json', json.dumps([
            {'url': 'https://a.example/1'},
            {'url': 'https://a.example/2', 'decision': 'accept'},
            {'url': 'https://a.example/3', 'decision': 'reject', 'reason': 'noise'}]))
        got = refs.load_decisions(path)
        self.assertEqual([d['url'] for d in got['accept']], ['https://a.example/1', 'https://a.example/2'])
        self.assertEqual([d['url'] for d in got['reject']], ['https://a.example/3'])

    def test_json_mapping_form(self):
        path = self._write('d.json', json.dumps({'accept': [{'url': 'u1'}], 'reject': [{'url': 'u2'}]}))
        got = refs.load_decisions(path)
        self.assertEqual((len(got['accept']), len(got['reject'])), (1, 1))
        path = self._write('e.json', json.dumps({'accept': None}))
        self.assertEqual(refs.load_decisions(path), {'accept': [], 'reject': []})

    def test_yaml(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest('PyYAML not installed')
        path = self._write('d.yaml', '- url: https://a.example/1\n- url: https://a.example/2\n  decision: reject\n')
        got = refs.load_decisions(path)
        self.assertEqual((len(got['accept']), len(got['reject'])), (1, 1))

    def test_invalid_shapes(self):
        with self.assertRaises(ValueError):
            refs.load_decisions(self._write('d.json', '["x"]'))
        with self.assertRaises(ValueError):
            refs.load_decisions(self._write('d.json', '"x"'))


class RejectionTests(unittest.TestCase):
    def test_reject_and_read_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d) / 'hub'
            self.assertEqual(refs.read_rejections(home), {})
            key = refs.reject_reference(home, 'https://github.com/A/B', 'not   relevant', today='2026-01-02')
            self.assertEqual(key, 'github.com/a/b')
            got = refs.read_rejections(home)
            self.assertEqual(got[key], {'reason': 'not relevant', 'at': '2026-01-02'})
            refs.reject_reference(home, 'https://example.org/z')
            self.assertEqual(len(refs.read_rejections(home)), 2)
            self.assertTrue((home / 'curation-rejections.json').is_file())

    def test_curate_skips_rejected_urls(self):
        incoming = [{'url': 'https://github.com/zz/one', 'title': 'one'},
                    {'url': 'https://github.com/zz/two', 'title': 'two'}]
        base = refs.curate(incoming, known=set())
        self.assertEqual(len(base), 2)
        got = refs.curate(incoming, known=set(), rejected=['https://GitHub.com/ZZ/One'])
        self.assertEqual([c['url'] for c in got], ['https://github.com/zz/two'])


class ReadmeCountsTests(unittest.TestCase):
    TEXT = ('Validates **5** canonical skills\nFilter 7 curated public references\n'
            '**9** curated public references and profiles, 3 skills, end\n')
    COUNTS = {'references': 11, 'skills': 22}

    def test_with_counts_rewrites_tokens(self):
        out = refs.readme_with_counts(self.TEXT, self.COUNTS)
        self.assertIn('Validates **22** canonical skills', out)
        self.assertIn('Filter 11 curated public references', out)
        self.assertIn('**11** curated public references', out)
        self.assertIn('profiles, 22 skills,', out)
        self.assertEqual(refs.readme_with_counts(out, self.COUNTS), out)

    def test_is_current_and_write(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'README.md'
            path.write_bytes(self.TEXT.replace('\n', '\r\n').encode('utf-8'))
            with mock.patch.object(refs, 'readme_counts', return_value=self.COUNTS):
                self.assertFalse(refs.readme_is_current(path))
                self.assertTrue(refs.write_readme_counts(path))
                self.assertTrue(refs.readme_is_current(path))
                self.assertFalse(refs.write_readme_counts(path))
            self.assertIn(b'\r\n', path.read_bytes())

    def test_real_readme_is_current(self):
        self.assertTrue(refs.readme_is_current(), 'README counts are stale; run aiwh references --write')


class CurateCliTests(unittest.TestCase):
    def _err(self, argv):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code, out = _run(argv)
        return code, out, err.getvalue()

    def test_reject_records_private_rejection(self):
        with tempfile.TemporaryDirectory() as d:
            code, out, _ = self._err(['--home', d, 'curate', '--reject', 'https://github.com/a/b', '--reason', 'x'])
            self.assertEqual(code, 0)
            self.assertIn('Rejected (private)', out)
            self.assertEqual(refs.read_rejections(d)['github.com/a/b']['reason'], 'x')

    def test_missing_browser_json_is_friendly(self):
        with tempfile.TemporaryDirectory() as d:
            code, _, err = self._err(['--home', d, 'curate', '--browser-json', str(Path(d) / 'missing.json')])
            self.assertEqual(code, 2)
            self.assertIn('aiwh curate', err)
            self.assertNotIn('Traceback', err)

    def test_accept_cli_writes_only_temp_files(self):
        path = _tmp_catalog(self)
        entry = _entry()
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.object(refs, 'CATALOG_PATH', path), \
                mock.patch.object(refs, 'write_document', return_value='doc.md') as wd, \
                mock.patch.object(refs, 'write_readme_counts', return_value=True) as wr:
            code, out, err = self._err(['--home', home, 'curate', '--accept', entry['url'], '--category', entry['category'],
                                        '--areas', *entry['areas']])
            self.assertEqual(code, 0, err)
            self.assertIn('Accepted: some-owner-new-repo', out)
            wd.assert_called_once()
            wr.assert_called_once()
        self.assertIn('some-owner-new-repo', json.loads(path.read_text(encoding='utf-8'))['references'])

    def test_accept_cli_failure_returns_1_without_writing_docs(self):
        path = _tmp_catalog(self)
        existing = next(iter(reference_catalog()['references'].values()))['url']
        entry = _entry()
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.object(refs, 'CATALOG_PATH', path), \
                mock.patch.object(refs, 'write_document') as wd, \
                mock.patch.object(refs, 'write_readme_counts') as wr:
            code, _, err = self._err(['--home', home, 'curate', '--accept', existing, '--category', entry['category'],
                                      '--areas', *entry['areas']])
            self.assertEqual(code, 1)
            self.assertIn('Not accepted', err)
            wd.assert_not_called()
            wr.assert_not_called()


if __name__ == '__main__':
    unittest.main()
