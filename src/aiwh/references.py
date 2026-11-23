"""Curated public reference catalog, risk labels, freshness checks and curation.

Safety properties:
- References are suggestions; nothing is cloned, installed or executed.
- Freshness checks only read public repository metadata through an already
  authenticated ``gh`` binary, and only when the user explicitly runs them.
- Curation reads user-selected sources and prints candidates. Only an explicit
  ``--accept``/``--decisions`` edits the canonical catalog, and it stores public
  fields only (never folders, dates added or other personal bookmark metadata).
- Rejections live in the private home directory, never in the repository.
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .core import canonical_url, md_target, md_text, repo_key
from .handoff_checks import parse_day
from .workbench import CAPABILITIES, ROOT

CATALOG_PATH = CAPABILITIES / 'references' / 'catalog.json'
KINDS = {'repository', 'list', 'guide', 'site', 'tool', 'book', 'paper', 'course'}
REFERENCE_KEYS = {'title', 'url', 'category', 'kind', 'areas', 'risk', 'group', 'reviewed', 'license',
                  'description'}
DESCRIPTION_LIMIT = 300
DEFAULT_LIMIT = 10
DEFAULT_DOCUMENT = ROOT / 'docs' / 'REFERENCES.md'


def _string_list(key, name, value):
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f'Reference {key} {name} must be a list of strings')
    return value


def reference_catalog():
    data = json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
    if data.get('schema_version') != 1:
        raise ValueError(f'Unsupported reference catalog version: {CATALOG_PATH}')
    return data


def validate_references(data=None):
    from .areas import catalog as area_catalog
    data = data or reference_catalog()
    areas = set(area_catalog())
    labels = set(data.get('risk_labels', {}))
    categories = data.get('categories', {})
    seen = {}
    reviewed = 0
    for category, entry in categories.items():
        missing = set(entry.get('areas', [])) - areas
        if not entry.get('label') or missing:
            raise ValueError(f'Invalid reference category {category}: label or areas {sorted(missing)}')
    for key, ref in data.get('references', {}).items():
        if not isinstance(ref, dict):
            raise ValueError(f'Reference {key} must be an object')
        unknown_keys = set(ref) - REFERENCE_KEYS
        if unknown_keys:
            raise ValueError(f'Reference {key} has unknown keys {sorted(unknown_keys)}')
        for field in ('url', 'title', 'category', 'kind'):
            if not isinstance(ref.get(field, ''), str):
                raise ValueError(f'Reference {key} {field} must be a string')
        url = ref.get('url', '')
        if not url.startswith('https://'):
            raise ValueError(f'Reference {key} must use an https URL')
        if ref.get('category') not in categories:
            raise ValueError(f'Reference {key} has unknown category {ref.get("category")}')
        if ref.get('kind') not in KINDS:
            raise ValueError(f'Reference {key} has invalid kind {ref.get("kind")}')
        ref_areas = _string_list(key, 'areas', ref.get('areas', []))
        ref_risk = _string_list(key, 'risk', ref.get('risk', []))
        if not ref.get('title') or not ref_areas:
            raise ValueError(f'Reference {key} needs a title and at least one area')
        if set(ref_areas) - areas:
            raise ValueError(f'Reference {key} has unknown areas {sorted(set(ref_areas) - areas)}')
        if set(ref_risk) - labels:
            raise ValueError(f'Reference {key} has unknown risk labels')
        if 'group' in ref and (not isinstance(ref['group'], str) or not ref['group'].strip()):
            raise ValueError(f'Reference {key} group must be a non-empty string when present')
        if 'reviewed' in ref and (not isinstance(ref['reviewed'], str) or parse_day(ref['reviewed']) is None):
            raise ValueError(f'Reference {key} reviewed date must be YYYY-MM-DD')
        if 'license' in ref and (not isinstance(ref['license'], str) or not ref['license'].strip()):
            raise ValueError(f'Reference {key} license note must be a non-empty string')
        if 'description' in ref and (not isinstance(ref['description'], str) or not ref['description'].strip()
                                     or len(ref['description']) > DESCRIPTION_LIMIT):
            raise ValueError(f'Reference {key} description must be a non-empty string of at most '
                             f'{DESCRIPTION_LIMIT} characters')
        reviewed += 'reviewed' in ref
        canonical = canonical_url(url)
        if canonical in seen:
            raise ValueError(f'Duplicate reference URL in {seen[canonical]} and {key}')
        seen[canonical] = key
    return {'references': len(data.get('references', {})), 'categories': len(categories),
            'risk_labels': len(labels), 'reviewed': reviewed}


def references_for(areas=None, risk=None, limit=None):
    """Return references for areas (all when None); unlabeled items rank first."""
    data = reference_catalog()
    wanted = set(areas or [])
    rows = []
    for key, ref in data['references'].items():
        if wanted and not wanted & set(ref['areas']):
            continue
        if risk and risk not in ref.get('risk', []):
            continue
        overlap = len(wanted & set(ref['areas'])) if wanted else 0
        rows.append({'id': key, **ref, '_rank': (-overlap, len(ref.get('risk', [])), ref['title'].lower())})
    rows.sort(key=lambda row: row['_rank'])
    for row in rows:
        row.pop('_rank')
    return rows[:limit] if limit else rows


def risk_index():
    data = reference_catalog()
    return {canonical_url(ref['url']): ref.get('risk', []) for ref in data['references'].values()}


def risk_suffix(labels):
    return f' (risk: {", ".join(labels)})' if labels else ''


def references_markdown():
    """Deterministic document generated from the catalog (docs/REFERENCES.md)."""
    data = reference_catalog()
    lines = ['# Curated references', '',
             '<!-- Generated by `aiwh references --markdown`; edit capabilities/references/catalog.json instead. -->', '',
             'Public references curated from reviewed sources. They are evaluation candidates, not endorsements;',
             'nothing is installed, cloned or executed by AI Workbench. Descriptions are self-reported by authors.',
             'Reviewed is the date the entry was last read by a maintainer, with the license its README stated then;',
             '`-` means no review date is recorded.', '',
             '## Risk labels', '']
    lines += [f'- `{label}`: {text}' for label, text in data['risk_labels'].items()]
    for category, entry in data['categories'].items():
        rows = [r for r in data['references'].values() if r['category'] == category]
        if not rows:
            continue
        lines += ['', f'## {entry["label"]}', '', f'Areas: {", ".join(f"`{a}`" for a in entry["areas"])}', '',
                  '| Reference | Kind | Areas | Risk | Reviewed |', '|---|---|---|---|---|']
        for ref in sorted(rows, key=lambda r: (r.get('group') or '', r['title'].lower())):
            title = ref['title'].replace('|', '\\|')
            group = f'{ref["group"]}: ' if ref.get('group') else ''
            review = ref.get('reviewed', '-')
            if ref.get('license'):
                review += f' ({ref["license"].replace("|", "/")})'
            lines.append(f'| {group}[{title}]({ref["url"]}) | {ref["kind"]} | {", ".join(ref["areas"])} | '
                         f'{", ".join(ref.get("risk", [])) or "-"} | {review} |')
    return '\n'.join(lines) + '\n'


def write_document(path=DEFAULT_DOCUMENT):
    """Write the generated document with LF line endings; returns the path written."""
    path = Path(path)
    path.write_text(references_markdown(), encoding='utf-8', newline='\n')
    return path


def document_is_current(path=DEFAULT_DOCUMENT):
    """True only when the file exists and matches the generated output byte-for-byte."""
    try:
        current = Path(path).read_bytes()
    except FileNotFoundError:
        return False
    return current == references_markdown().encode('utf-8')


GITHUB_RESERVED = {'topics', 'collections', 'orgs', 'users', 'marketplace', 'sponsors', 'features',
                   'settings', 'explore', 'trending', 'apps', 'enterprise'}


def _github_slug(url):
    match = re.match(r'https://github\.com/([^/#?]+)/([^/#?]+)/?$', url.rstrip('/'))
    if not match or match.group(1).lower() in GITHUB_RESERVED:
        return None
    name = match.group(2)
    if name.lower().endswith('.git'):
        name = name[:-4]
    return f'{match.group(1)}/{name}' if name else None


def _gh_repo(slug):
    result = subprocess.run(['gh', 'api', f'repos/{slug}'], capture_output=True, text=True,
                            encoding='utf-8', timeout=30, check=False)
    if result.returncode != 0:
        return {'_error': (result.stderr or result.stdout).strip()[:200]}
    return json.loads(result.stdout)


def check_references(*, stale_days=365, fetch=None, today=None):
    """Explicit, read-only freshness check of GitHub references (network via gh)."""
    fetch = fetch or _gh_repo
    today = today or datetime.now(timezone.utc)
    if today.tzinfo is None:
        today = today.replace(tzinfo=timezone.utc)
    report = []
    for key, ref in reference_catalog()['references'].items():
        slug = _github_slug(ref['url'])
        if not slug:
            report.append({'id': key, 'url': ref['url'], 'status': 'not-checked',
                           'reason': 'not a GitHub repository URL'})
            continue
        try:
            repo = fetch(slug)
        except (OSError, subprocess.TimeoutExpired, ValueError) as error:
            repo = {'_error': str(error)[:200]}
        if '_error' in repo:
            missing = bool(re.search(r'HTTP 404\b|\bNot Found\b', repo['_error']))
            report.append({'id': key, 'url': ref['url'], 'status': 'missing' if missing else 'error',
                           'reason': repo['_error']})
            continue
        pushed = repo.get('pushed_at') or ''
        age = None
        if pushed:
            try:
                parsed = datetime.fromisoformat(pushed.replace('Z', '+00:00'))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                age = (today - parsed).days
            except ValueError:
                age = None
        status = 'archived' if repo.get('archived') else 'stale' if age is not None and age > stale_days else 'ok'
        moved = canonical_url(repo.get('html_url', ref['url'])) != canonical_url(ref['url'])
        report.append({'id': key, 'url': ref['url'], 'status': status, 'pushed_at': pushed,
                       'days_since_push': age, 'license': (repo.get('license') or {}).get('spdx_id') or 'none',
                       'fork': bool(repo.get('fork')), 'renamed_to': repo.get('html_url') if moved else None})
    return report


README_PATH = ROOT / 'README.md'
_README_COUNTS = {
    'references': [r'(\*\*)(\d+)(\*\* curated public references)', r'(Filter )(\d+)( curated public references)'],
    'skills': [r'(Validates \*\*)(\d+)(\*\* canonical skills)', r'(profiles, )(\d+)( skills,)'],
}


def readme_counts():
    """Counts the README states, computed from the catalogs it describes."""
    from .workbench import registry
    return {'references': len(reference_catalog()['references']), 'skills': len(registry()['skills'])}


def readme_with_counts(text, counts=None):
    counts = counts or readme_counts()
    for name, patterns in _README_COUNTS.items():
        for pattern in patterns:
            text = re.sub(pattern, lambda m, n=name: f'{m.group(1)}{counts[n]}{m.group(3)}', text)
    return text


def readme_is_current(path=README_PATH):
    text = Path(path).read_bytes().decode('utf-8')
    return text == readme_with_counts(text)


def write_readme_counts(path=README_PATH):
    """Rewrite only the count tokens in README; returns True when the file changed."""
    path = Path(path)
    raw = path.read_bytes().decode('utf-8')
    updated = readme_with_counts(raw)
    if updated == raw:
        return False
    path.write_bytes(updated.encode('utf-8'))
    return True


def reference_key(url):
    """Stable catalog key: ``owner-repo`` for GitHub, host-and-path slug otherwise."""
    base = re.sub(r'^https?://', '', repo_key(url))
    base = re.sub(r'^github\.com/', '', base)
    return re.sub(r'[^a-z0-9]+', '-', base.lower()).strip('-')[:80]


def _today():
    return datetime.now(timezone.utc).date().isoformat()


def accept_reference(entry, *, catalog_path=None, today=None):
    """Add one reviewed reference to the canonical catalog; returns its key.

    ``entry`` needs url, category and areas; title defaults to the GitHub slug or URL,
    kind to ``repository`` for GitHub and ``site`` otherwise. Raises ValueError on
    duplicates or invalid fields; the file is only written after validation passes.
    """
    from .core import redact_url, sensitive_url_reason
    path = Path(catalog_path or CATALOG_PATH)
    data = json.loads(path.read_text(encoding='utf-8'))
    url = str(entry.get('url', '')).strip()
    if not url:
        raise ValueError('accept needs a url')
    reason = sensitive_url_reason(url)
    if reason:
        raise ValueError(f'Refusing to add {url[:80]}: {reason}')
    url = redact_url(url)
    wanted = repo_key(url)
    for key, ref in data['references'].items():
        if repo_key(ref['url']) == wanted:
            raise ValueError(f'Already in catalog as {key}')
    slug = _github_slug(url)
    ref = {'title': entry.get('title') or slug or url,
           'url': url,
           'category': entry.get('category'),
           'kind': entry.get('kind') or ('repository' if slug else 'site'),
           'areas': list(entry.get('areas') or []),
           'risk': list(entry.get('risk') or []),
           'reviewed': entry.get('reviewed') or today or _today()}
    for optional in ('group', 'license', 'description'):
        if entry.get(optional):
            value = ' '.join(str(entry[optional]).split())
            ref[optional] = value[:DESCRIPTION_LIMIT] if optional == 'description' else value
    key = entry.get('key') or reference_key(url)
    if key in data['references']:
        raise ValueError(f'Catalog key {key} already exists; pass an explicit key')
    data['references'][key] = ref
    validate_references(data)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    return key


def load_decisions(path):
    """Read a curation decisions file (JSON or YAML).

    Either a mapping ``{accept: [...], reject: [...]}`` or a list whose items carry
    ``decision: accept|reject`` (accept is the default).
    """
    path = Path(path)
    text = path.read_text(encoding='utf-8')
    if path.suffix.lower() in {'.yaml', '.yml'}:
        import yaml
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if isinstance(data, list):
        if not all(isinstance(d, dict) for d in data):
            raise ValueError(f'{path}: every decision must be a mapping')
        data = {'accept': [d for d in data if d.get('decision', 'accept') == 'accept'],
                'reject': [d for d in data if d.get('decision') == 'reject']}
    if not isinstance(data, dict):
        raise ValueError(f'{path}: expected a list or a mapping with accept/reject')
    return {'accept': list(data.get('accept') or []), 'reject': list(data.get('reject') or [])}


def rejections_path(home):
    return Path(home) / 'curation-rejections.json'


def read_rejections(home):
    path = rejections_path(home)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    return data.get('rejected', {}) if isinstance(data, dict) else {}


def reject_reference(home, url, reason='', today=None):
    """Record a private rejection so curate stops listing the URL; returns its key."""
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    rejected = read_rejections(home)
    key = repo_key(url)
    rejected[key] = {'reason': ' '.join(str(reason or '').split()), 'at': today or _today()}
    path = rejections_path(home)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps({'version': 1, 'rejected': dict(sorted(rejected.items()))},
                              indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    tmp.replace(path)
    return key


def known_urls():
    """Every URL referenced by canonical capabilities and public docs."""
    text = []
    for path in [*CAPABILITIES.rglob('*.json'), *CAPABILITIES.rglob('*.md'),
                 *(ROOT / 'docs').glob('*.md'), ROOT / 'README.md']:
        if path.is_file():
            text.append(path.read_text(encoding='utf-8', errors='replace'))
    found = re.findall(r'https?://[^\s)\]"\'<>|]+', '\n'.join(text))
    return {repo_key(url.rstrip('.,;')) for url in found}


def suggest_areas(item, area_entries=None):
    from .areas import catalog as area_catalog, _word_occurs
    area_entries = area_entries or area_catalog()
    text = ' '.join([str(item.get('title', '')), str(item.get('description', '')),
                     ' '.join(item.get('topics', []) or []), str(item.get('url', ''))]).lower()
    scored = []
    for key, entry in area_entries.items():
        hits = [term for term in entry.get('signals', {}).get('keywords', []) if _word_occurs(term, text)]
        if hits:
            scored.append((len(hits), key, hits))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [{'area': key, 'terms': hits[:4]} for _, key, hits in scored[:3]]


def curate(incoming, *, baseline=(), known=None, rejected=()):
    """Return reference candidates new to the repository (and baseline), minus private rejections."""
    from .core import sanitize_resources
    known = known if known is not None else known_urls()
    incoming, _ = sanitize_resources(incoming)
    skip = ({repo_key(url) for url in known} | {repo_key(item.get('url')) for item in baseline}
            | {repo_key(url) for url in rejected})
    candidates, seen = [], set()
    for item in incoming:
        url = repo_key(item.get('url'))
        if not canonical_url(item.get('url')).startswith('http') or url in skip or url in seen:
            continue
        seen.add(url)
        candidates.append({'url': item.get('url'), 'title': item.get('title', ''),
                           'description': (item.get('description') or '')[:200],
                           'source': item.get('source', 'unknown'),
                           'suggested_areas': suggest_areas(item)})
    return candidates


def curate_markdown(candidates):
    lines = ['# Reference curation candidates', '',
             'Review each candidate before adding it to `capabilities/references/catalog.json`.',
             'Suggested areas are keyword heuristics, not classifications. Do not commit personal folders or dates.', '',
             f'Candidates: {len(candidates)}', '']
    groups = {}
    for item in candidates:
        area = item['suggested_areas'][0]['area'] if item['suggested_areas'] else '(unclassified)'
        groups.setdefault(area, []).append(item)
    for area in sorted(groups, key=lambda a: (a == '(unclassified)', a)):
        lines += [f'## {area}', '']
        for item in groups[area]:
            title = md_text(item['title'] or item['url'])
            why = '; '.join(f'{s["area"]}: {", ".join(s["terms"])}' for s in item['suggested_areas'])
            desc = f' — {item["description"]}' if item['description'] else ''
            lines.append(f'- [{title}]({md_target(item["url"])}){desc}' + (f' _(signals: {why})_' if why else ''))
        lines.append('')
    return '\n'.join(lines).rstrip() + '\n'
