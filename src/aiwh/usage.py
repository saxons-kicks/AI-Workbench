"""Offline token-usage aggregation over local Claude Code transcripts (JSONL).

Only numeric counters, model names and timestamps are read; message content is
never retained or returned. No network access and no pricing.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from .skilltools import _frontmatter_and_body, estimate_tokens
from .workbench import skill_paths

FIELDS = ('input_tokens', 'output_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens')


def default_root():
    return Path.home() / '.claude' / 'projects'


def encode_project(path):
    """Claude Code project directory name: ':', '\\' and '/' become '-' (C:\\a\\b -> C--a-b)."""
    return str(path).replace(':', '-').replace('\\', '-').replace('/', '-')


def _zero():
    return {**{f: 0 for f in FIELDS}, 'messages': 0}


def _add(bucket, counts):
    for f in FIELDS:
        bucket[f] += counts[f]
    bucket['messages'] += 1


def _total(bucket):
    bucket['total_tokens'] = sum(bucket[f] for f in FIELDS)
    return bucket


def _int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _parse_since(since):
    if since is None or since == '':
        return None
    if isinstance(since, datetime):
        return since.date()
    if isinstance(since, date):
        return since
    return date.fromisoformat(str(since)[:10])


def _day(timestamp):
    if not isinstance(timestamp, str) or len(timestamp) < 10:
        return None
    try:
        return date.fromisoformat(timestamp[:10])
    except ValueError:
        return None


def _records(path):
    """Yield (counts, model, day, dedupe_key) per assistant usage line; skip invalid lines."""
    try:
        handle = open(path, encoding='utf-8', errors='replace')
    except OSError:
        return
    with handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            message = row.get('message')
            usage = message.get('usage') if isinstance(message, dict) else None
            if not isinstance(usage, dict):
                continue
            counts = {f: _int(usage.get(f)) for f in FIELDS}
            model = message.get('model')
            model = model if isinstance(model, str) and model else 'unknown'
            mid, rid = message.get('id'), row.get('requestId')
            key = (mid, rid) if isinstance(mid, str) and isinstance(rid, str) else None
            yield counts, model, _day(row.get('timestamp')), key


def usage_report(root=None, *, project=None, since=None):
    """Aggregate token counts by model and day across ``<root>/*/*.jsonl``.

    ``project`` is a project path (encoded like Claude Code) or an already encoded
    directory name; ``since`` is a date or ISO date string (inclusive).
    """
    root = Path(root) if root else default_root()
    cutoff = _parse_since(since)
    wanted = encode_project(project) if project else None
    totals, by_model, by_day, sessions = _zero(), {}, {}, []
    files = 0
    if root.is_dir():
        dirs = sorted(d for d in root.iterdir() if d.is_dir() and (wanted is None or d.name == wanted))
        for directory in dirs:
            for path in sorted(directory.glob('*.jsonl')):
                files += 1
                seen, session = set(), _zero()
                for counts, model, day, key in _records(path):
                    if cutoff and (day is None or day < cutoff):
                        continue
                    if key:
                        if key in seen:
                            continue
                        seen.add(key)
                    _add(totals, counts)
                    _add(session, counts)
                    _add(by_model.setdefault(model, _zero()), counts)
                    _add(by_day.setdefault(day.isoformat() if day else 'unknown', _zero()), counts)
                if session['messages']:
                    sessions.append(session)
    n = len(sessions)
    avg_input = (sum(s['input_tokens'] + s['cache_creation_input_tokens'] + s['cache_read_input_tokens']
                     for s in sessions) / n) if n else 0.0
    return {'root': str(root), 'project': wanted, 'since': cutoff.isoformat() if cutoff else None,
            'files': files, 'sessions': n, 'totals': _total(totals),
            'avg_input_tokens_per_session': round(avg_input, 1),
            'by_model': {k: _total(v) for k, v in sorted(by_model.items())},
            'by_day': {k: _total(v) for k, v in sorted(by_day.items())}}


def format_usage(report):
    """Short plain-text table."""
    def row(label, b):
        return (f"{label[:28]:<28} {b['input_tokens']:>11,} {b['output_tokens']:>11,} "
                f"{b['cache_creation_input_tokens']:>12,} {b['cache_read_input_tokens']:>12,} {b['total_tokens']:>13,}")
    lines = [f"Claude Code usage: {report['sessions']} sessions, {report['totals']['messages']} messages"
             + (f", since {report['since']}" if report.get('since') else ''),
             f"{'':<28} {'input':>11} {'output':>11} {'cache write':>12} {'cache read':>12} {'total':>13}"]
    for label, section in (('model', 'by_model'), ('day', 'by_day')):
        lines.append(f'-- by {label}')
        lines += [row(k, v) for k, v in report[section].items()]
    lines += ['-- total', row('all', report['totals']),
              f"avg input per session (incl. cache): {report['avg_input_tokens_per_session']:,.0f}"]
    return '\n'.join(lines)


def skill_token_comparison(project, *, root=None, since=None):
    """Estimated token cost of skills installed in a project vs average input per session.

    Looks in every skill directory Workbench knows (``skill_paths('all')``). Estimates are
    characters/4 (see ``skilltools.estimate_tokens``): metadata is always in context, the
    body only when a skill is invoked.
    """
    project = Path(project)
    skills, metadata_total, body_total = [], 0, 0
    for rel in skill_paths('all'):
        base = project / rel
        if not base.is_dir():
            continue
        for directory in sorted(p for p in base.iterdir() if (p / 'SKILL.md').is_file()):
            try:
                description, body = _frontmatter_and_body(directory / 'SKILL.md')
            except (OSError, ValueError):
                continue
            meta, body_t = estimate_tokens(directory.name + ' ' + description), estimate_tokens(body)
            metadata_total += meta
            body_total += body_t
            skills.append({'name': directory.name, 'dir': rel, 'metadata_tokens': meta, 'body_tokens': body_t})
    avg = usage_report(root, project=project, since=since)['avg_input_tokens_per_session']

    def pct(value):
        return round(100 * value / avg, 2) if avg else None

    return {'project': str(project), 'skills': skills, 'skill_count': len(skills),
            'metadata_tokens': metadata_total, 'body_tokens_if_all_loaded': body_total,
            'avg_input_tokens_per_session': avg,
            'metadata_pct_of_avg_input': pct(metadata_total),
            'bodies_pct_of_avg_input': pct(body_total),
            'method': 'approximate: characters / 4; actual tokenization varies by model'}
