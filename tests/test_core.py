import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aiwh.core import (canonical_url, chromelike_bookmarks, merged_index,
                       github_stars, browser_html_export, attach, project_profile,
                       sensitive_url_reason, redact_url, sanitize_resources, read_catalog, MAX_URL_LENGTH)


class CatalogTests(unittest.TestCase):
    def test_dedup_and_tracking_params(self):
        items = merged_index([], [
            {'url': 'https://github.com/Owner/Repo?utm_source=x#readme', 'title': 'Vulkan Renderer', 'source': 'browser'},
            {'url': 'https://github.com/owner/Repo', 'title': 'Vulkan Renderer', 'source': 'github:starred'}])
        self.assertEqual(len(items), 1)
        self.assertEqual(len(items[0]['sources']), 2)
        self.assertIn('game-port', items[0]['categories'])

    def test_bookmark_tree(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'Bookmarks'
            f.write_text(json.dumps({'roots': {'bookmark_bar': {'type': 'folder', 'name': 'Bar', 'children': [
                {'type': 'folder', 'name': 'QA', 'children': [
                    {'type': 'url', 'name': 'NUnit', 'url': 'https://nunit.org'}]}]}}}), encoding='utf-8')
            data = chromelike_bookmarks(f, 'chrome', 'Default')
            self.assertEqual(len(data), 1)
            self.assertIn('QA', data[0]['folder'])

    def test_stars_paginated(self):
        got = github_stars([[{'html_url':'https://github.com/a/b','full_name':'a/b', 'topics':['mcp']}],
                           [{'html_url':'https://github.com/a/c','full_name':'a/c'}]])
        self.assertEqual(len(got), 2)

    def test_html_export(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'bookmarks.html'
            f.write_text('<!DOCTYPE NETSCAPE-Bookmark-file-1><DL><p><DT><H3>Dev</H3><DL><p><DT><A HREF="https://test.com">Example</A></DL><p></DL>', encoding='utf-8')
            got = browser_html_export(f)
            self.assertEqual(len(got), 1)
            self.assertEqual(got[0]['title'], 'Example')
            self.assertIn('Dev', got[0]['folder'])

    def test_attach_respects_existing_agents(self):
        with tempfile.TemporaryDirectory() as d:
            project = Path(d)
            (project/'AGENTS.md').write_text('# Original\n', encoding='utf-8')
            index = merged_index([], [{'url':'https://github.com/x/vulkan', 'title':'vulkan-shader', 'source':'browser'}])
            result = attach(project, index, profiles=['game-port'])
            self.assertTrue(result['written'])
            self.assertEqual(len(result['plan']['resources']), 1)
            txt = (project/'AGENTS.md').read_text(encoding='utf-8')
            self.assertIn('# Original', txt)
            self.assertEqual(txt.count('<!-- AIWH:BEGIN -->'), 1)
            attach(project, index, profiles=['game-port'])
            self.assertEqual((project/'AGENTS.md').read_text(encoding='utf-8').count('<!-- AIWH:BEGIN -->'), 1)
            self.assertTrue((project/'.ai-workbench/RESOURCES.md').is_file())
            self.assertIn('.ai-workbench/', (project/'.gitignore').read_text(encoding='utf-8'))

    def test_profile_detection(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'MySolution.sln').write_text('', encoding='utf-8')
            self.assertIn('qa-dotnet', project_profile(d))


class SensitiveUrlTests(unittest.TestCase):
    PAY = 'https://tokenized.play.google.com/eventmanager/v1/pay?x=1'

    def test_reason_for_sensitive_host_and_length(self):
        self.assertIn('tokenized.play.google.com', sensitive_url_reason(self.PAY))
        self.assertIn('longer', sensitive_url_reason('https://example.com/' + 'a' * MAX_URL_LENGTH))
        self.assertEqual(sensitive_url_reason('https://example.com/ok'), '')
        self.assertEqual(sensitive_url_reason(None), '')

    def test_redact_strips_credential_params_only(self):
        self.assertEqual(redact_url('https://example.com/p?authuser=0&q=x'), 'https://example.com/p?q=x')
        self.assertEqual(redact_url('https://example.com/p?Token=a&rpctoken=b'), 'https://example.com/p')
        benign = 'https://example.com/p?q=x&page=2#frag'
        self.assertEqual(redact_url(benign), benign)

    def test_sanitize_resources(self):
        items = [{'url': self.PAY, 'title': 'pay'},
                 {'url': 'https://example.com/p?authuser=0&q=x', 'title': 'a'},
                 {'url': 'https://example.com/ok', 'title': 'b'}]
        kept, dropped = sanitize_resources(items)
        self.assertEqual(dropped, 1)
        self.assertEqual([x['url'] for x in kept], ['https://example.com/p?q=x', 'https://example.com/ok'])
        self.assertEqual(items[1]['url'], 'https://example.com/p?authuser=0&q=x')

    def test_merged_index_drops_and_redacts(self):
        items = merged_index(
            [{'id': 'old', 'url': self.PAY, 'title': 'pay'}],
            [{'url': self.PAY, 'title': 'pay2', 'source': 'browser'},
             {'url': 'https://example.com/p?authuser=0&q=x', 'title': 'Doc', 'source': 'browser'}])
        self.assertEqual([x['url'] for x in items], ['https://example.com/p?q=x'])

    def test_read_catalog_omits_sensitive_items(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'catalog.json').write_text(json.dumps({'items': [
                {'id': '1', 'url': self.PAY, 'title': 'pay'},
                {'id': '2', 'url': 'https://example.com/ok?token=s', 'title': 'ok'}]}), encoding='utf-8')
            got = read_catalog(d)
            self.assertEqual([x['id'] for x in got], ['2'])
            self.assertEqual(got[0]['url'], 'https://example.com/ok')


if __name__ == '__main__':
    unittest.main()
