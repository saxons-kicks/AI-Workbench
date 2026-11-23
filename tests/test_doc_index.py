import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from aiwh import doc_index  # noqa: E402
from aiwh.semantic import build_index, search_index  # noqa: E402


def make_docx(path, text):
    xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f'<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>')
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('word/document.xml', xml)


class DocIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'docs'
        self.home = Path(self.tmp.name) / 'home'
        self.root.mkdir()
        (self.root / 'a.md').write_text('# Zebrafish notes\nhello', encoding='utf-8')
        (self.root / 'b.html').write_text(
            '<html><script>evil()</script><p>Quokka <b>page</b></p></html>', encoding='utf-8')
        (self.root / 'c.csv').write_text('x,y\nnarwhal,2\n', encoding='utf-8')
        make_docx(self.root / 'd.docx', 'Axolotl report')
        (self.root / 'bin.txt').write_bytes(b'\x00\x01\x02')
        (self.root / 'big.txt').write_text('x' * 2000, encoding='utf-8')
        (self.root / '.git').mkdir()
        (self.root / '.git' / 'hidden.md').write_text('secret', encoding='utf-8')
        (self.root / 'node_modules').mkdir()
        (self.root / 'node_modules' / 'n.md').write_text('dep', encoding='utf-8')

    def test_extract_builtin_formats(self):
        skipped = []
        docs = doc_index.extract_documents([self.root], max_bytes=1000, skipped=skipped)
        self.assertEqual({d['title'] for d in docs}, {'a.md', 'b.html', 'c.csv', 'd.docx'})
        by = {d['title']: d for d in docs}
        self.assertIn('Quokka page', by['b.html']['body'])
        self.assertNotIn('evil', by['b.html']['body'])
        self.assertIn('Axolotl', by['d.docx']['body'])
        self.assertTrue(by['a.md']['url'].startswith('file:'))
        self.assertEqual(by['d.docx']['tags'], 'docx')
        reasons = ' '.join(s['reason'] for s in skipped)
        self.assertIn('binary', reasons)
        self.assertIn('too large', reasons)

    def test_pdf_without_backend_reports_reason(self):
        pdf = self.root / 'x.pdf'
        pdf.write_bytes(b'%PDF-1.4 fake')
        skipped = []
        with mock.patch.object(doc_index, '_backend_available', return_value=False):
            docs = doc_index.extract_documents([pdf], skipped=skipped)
        self.assertEqual(docs, [])
        self.assertIn('no backend', skipped[0]['reason'])

    def test_optional_backend_used(self):
        pdf = self.root / 'x.pdf'
        pdf.write_bytes(b'%PDF-1.4 fake')
        reader = mock.Mock()
        reader.pages = [mock.Mock(extract_text=lambda: 'pdf platypus text')]
        fake_mod = mock.Mock(PdfReader=lambda p: reader)
        with mock.patch.object(doc_index, '_backend_available', side_effect=lambda n: n == 'pypdf'), \
                mock.patch.dict(sys.modules, {'pypdf': fake_mod}):
            docs = doc_index.extract_documents([pdf])
        self.assertEqual(len(docs), 1)
        self.assertIn('platypus', docs[0]['body'])

    def test_registry_roundtrip(self):
        r = doc_index.add_doc_roots([self.root, self.root / 'nope'], home=self.home)
        self.assertEqual(len(r['added']), 1)
        self.assertEqual(len(r['missing']), 1)
        self.assertEqual(doc_index.add_doc_roots([self.root], home=self.home)['added'], [])
        self.assertEqual(len(doc_index.list_doc_roots(self.home)), 1)
        self.assertTrue(json.loads((self.home / 'docs.json').read_text())['roots'])
        doc_index.remove_doc_roots([self.root], home=self.home)
        self.assertEqual(doc_index.list_doc_roots(self.home), [])

    def test_search_integration(self):
        doc_index.add_doc_roots([self.root], home=self.home)
        info = build_index(home=self.home, source='docs', use_vectors=False)
        self.assertGreaterEqual(info['indexed'], 4)
        res = search_index('Axolotl', home=self.home, source='docs')
        self.assertTrue(res['results'])
        self.assertEqual(res['results'][0]['source'], 'docs')
        build_index(home=self.home, source='all', use_vectors=False)
        res = search_index('narwhal', home=self.home, source='all')
        self.assertTrue(any(r['source'] == 'docs' for r in res['results']))

    def test_no_roots_no_docs(self):
        info = build_index(home=self.home, source='docs', use_vectors=False)
        self.assertEqual(info['indexed'], 0)


if __name__ == '__main__':
    unittest.main()
