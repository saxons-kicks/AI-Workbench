"""Index user-chosen local documents for ``aiwh search --source docs``.

Only explicitly registered paths are read (never an automatic home scan).
Built-in stdlib extractors cover text-like formats and .docx; PDF and other
formats use optional backends (docling, markitdown, unstructured, pypdf) when importable.
Registered roots persist in ``<home>/docs.json``.
"""
from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

from .core import DEFAULT_HOME

MAX_BYTES = 5_000_000
MAX_BODY_CHARS = 20_000
SKIP_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', 'venv'}
TEXT_EXTS = {'.md', '.txt', '.rst', '.json', '.yaml', '.yml', '.csv', '.html', '.htm'}
OPTIONAL_EXTS = {'.pdf', '.pptx', '.xlsx', '.epub', '.odt', '.rtf'}
BACKENDS = ('docling', 'markitdown', 'unstructured', 'pypdf')
_W_NS = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


# ---------------------------------------------------------------- registry
def _registry_file(home):
    return Path(home) / 'docs.json'


def list_doc_roots(home=DEFAULT_HOME):
    try:
        data = json.loads(_registry_file(home).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    roots = data.get('roots', []) if isinstance(data, dict) else []
    return [r for r in roots if isinstance(r, str)]


def _save(home, roots):
    Path(home).mkdir(parents=True, exist_ok=True)
    _registry_file(home).write_text(
        json.dumps({'roots': roots}, indent=2) + '\n', encoding='utf-8')


def add_doc_roots(paths, home=DEFAULT_HOME):
    """Register existing files/dirs. Idempotent."""
    roots = list_doc_roots(home)
    added, existing, missing = [], [], []
    for p in paths:
        path = Path(p).expanduser()
        if not path.exists():
            missing.append(str(p))
            continue
        resolved = str(path.resolve())
        if resolved in roots:
            existing.append(resolved)
        else:
            roots.append(resolved)
            added.append(resolved)
    if added:
        _save(home, roots)
    return {'added': added, 'existing': existing, 'missing': missing, 'roots': roots}


def remove_doc_roots(paths, home=DEFAULT_HOME):
    roots = list_doc_roots(home)
    removed = []
    for p in paths:
        resolved = str(Path(p).expanduser().resolve())
        if resolved in roots:
            roots.remove(resolved)
            removed.append(resolved)
    if removed:
        _save(home, roots)
    return {'removed': removed, 'roots': roots}


# -------------------------------------------------------------- extractors
class _Stripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def _read_text(path, max_bytes):
    with open(path, 'rb') as fh:
        raw = fh.read(max_bytes)
    if b'\x00' in raw[:4096]:
        raise ValueError('binary content')
    return raw.decode('utf-8', errors='replace')


def _extract_html(path, max_bytes):
    p = _Stripper()
    p.feed(_read_text(path, max_bytes))
    return ' '.join(p.parts)


def _extract_csv(path, max_bytes):
    text = _read_text(path, max_bytes)
    return '\n'.join(' '.join(row) for row in csv.reader(io.StringIO(text)))


def _extract_docx(path, max_bytes):
    with zipfile.ZipFile(path) as z:
        if z.getinfo('word/document.xml').file_size > max_bytes * 4:
            raise ValueError('document.xml too large')
        root = ElementTree.fromstring(z.read('word/document.xml'))
    return '\n'.join(
        ''.join(t.text or '' for t in p.iter(f'{_W_NS}t')) for p in root.iter(f'{_W_NS}p'))


def _backend_available(name):
    try:
        __import__(name)
        return True
    except Exception:  # ImportError or broken install
        return False


def _extract_optional(path, max_bytes):
    """Try optional backends in order; raise LookupError if none importable."""
    errors = []
    for name in BACKENDS:
        if not _backend_available(name):
            continue
        try:
            if name == 'docling':
                from docling.document_converter import DocumentConverter
                return DocumentConverter().convert(str(path)).document.export_to_markdown()
            if name == 'markitdown':
                from markitdown import MarkItDown
                return MarkItDown(enable_plugins=False).convert_local(str(path)).text_content
            if name == 'unstructured':
                from unstructured.partition.auto import partition
                return '\n'.join(str(e) for e in partition(filename=str(path)))
            if name == 'pypdf':
                if Path(path).suffix.lower() != '.pdf':
                    continue
                from pypdf import PdfReader
                return '\n'.join((pg.extract_text() or '') for pg in PdfReader(str(path)).pages)
        except Exception as exc:
            errors.append(f'{name}: {exc}')
    if errors:
        raise ValueError('; '.join(errors))
    raise LookupError('no backend installed (pip install ai-workbench[docs], [ingest] or [docs-lite])')


def _extract(path, ext, max_bytes):
    if ext == '.docx':
        return _extract_docx(path, max_bytes)
    if ext in ('.html', '.htm'):
        return _extract_html(path, max_bytes)
    if ext == '.csv':
        return _extract_csv(path, max_bytes)
    if ext in TEXT_EXTS:
        return _read_text(path, max_bytes)
    return _extract_optional(path, max_bytes)


# ------------------------------------------------------------------ walking
def _iter_files(root):
    if root.is_file():
        yield root
        return
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            entries = sorted(d.iterdir(), key=lambda e: e.name)
        except OSError:
            continue
        for e in entries:
            if e.is_dir() and not e.is_symlink():
                if e.name.startswith('.') or e.name in SKIP_DIRS:
                    continue
                stack.append(e)
            elif e.is_file() and not e.name.startswith('.'):
                yield e


def extract_documents(paths, *, max_bytes=MAX_BYTES, max_chars=MAX_BODY_CHARS, skipped=None):
    """Extract searchable docs from explicit files/dirs.

    ``skipped``, if a list, receives ``{'path', 'reason'}`` entries.
    """
    docs, seen = [], set()

    def skip(path, reason):
        if skipped is not None:
            skipped.append({'path': str(path), 'reason': reason})

    for root in paths:
        root = Path(root).expanduser()
        if not root.exists():
            skip(root, 'missing')
            continue
        for f in _iter_files(root):
            ext = f.suffix.lower()
            if ext not in TEXT_EXTS and ext != '.docx' and ext not in OPTIONAL_EXTS:
                if root.is_file():
                    skip(f, f'unsupported extension {ext or "(none)"}')
                continue
            resolved = str(f.resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                size = f.stat().st_size
            except OSError as exc:
                skip(f, f'stat failed: {exc}')
                continue
            if size > max_bytes:
                skip(f, f'too large ({size} bytes > {max_bytes})')
                continue
            try:
                text = _extract(f, ext, max_bytes)
            except LookupError as exc:
                skip(f, str(exc))
                continue
            except (OSError, ValueError, zipfile.BadZipFile, KeyError,
                    ElementTree.ParseError) as exc:
                skip(f, f'extract failed: {exc}')
                continue
            text = re.sub(r'\s+', ' ', text or '').strip()
            if not text:
                skip(f, 'empty')
                continue
            docs.append({
                'key': f'doc:{resolved}',
                'source': 'docs',
                'title': f.name,
                'url': f.resolve().as_uri(),
                'tags': ext.lstrip('.'),
                'body': text[:max_chars],
            })
    return docs


def collect_registered_documents(home=DEFAULT_HOME, **kwargs):
    """Extract docs for every root registered in ``<home>/docs.json``."""
    return extract_documents(list_doc_roots(home), **kwargs)
