"""Minimal stdlib encoder for TOON (Token-Oriented Object Notation).

Implements the common subset of the public TOON format (github.com/toon-format/toon)
used to hand compact state to LLM agents: indented ``key: value`` objects, inline
primitive arrays ``key[N]: a,b``, tabular arrays of uniform flat objects
``key[N]{f1,f2}:`` with one comma-separated row per item, and ``- `` list items
otherwise. Encoding only; JSON remains the canonical machine format.
"""
from __future__ import annotations

import json
import re

_SAFE = re.compile(r'^[^\s,:"\\\[\]{}#\-][^,:"\\\[\]{}\n\r\t]*(?<!\s)$')
_KEY = re.compile(r'^[A-Za-z_][A-Za-z0-9_.]*$')
_RESERVED = {'true', 'false', 'null'}


def _primitive(value):
    return value is None or isinstance(value, (str, int, float, bool))


def _scalar(value):
    if value is None:
        return 'null'
    if value is True:
        return 'true'
    if value is False:
        return 'false'
    if isinstance(value, (int, float)):
        return json.dumps(value)
    text = str(value)
    if (text and _SAFE.match(text) and text not in _RESERVED
            and not re.fullmatch(r'-?\d+(\.\d+)?([eE][+-]?\d+)?', text)):
        return text
    return json.dumps(text, ensure_ascii=False)


def _key(key):
    key = str(key)
    return key if _KEY.match(key) else json.dumps(key, ensure_ascii=False)


def _tabular_fields(items):
    if not items or not all(isinstance(i, dict) and i for i in items):
        return None
    fields = list(items[0])
    for item in items:
        if list(item) != fields or not all(_primitive(v) for v in item.values()):
            return None
    return fields


def _encode(value, indent, lines, prefix=''):
    pad = '  ' * indent
    if isinstance(value, dict):
        if prefix:
            lines.append(f'{pad}{prefix}:')
            indent += 1
            pad = '  ' * indent
        for k, v in value.items():
            _field(_key(k), v, indent, lines)
        return
    lines.append(f'{pad}{prefix}: {_scalar(value)}' if prefix else f'{pad}{_scalar(value)}')


def _field(key, value, indent, lines):
    pad = '  ' * indent
    if isinstance(value, dict):
        if not value:
            lines.append(f'{pad}{key}: {{}}')
            return
        _encode(value, indent, lines, prefix=key)
    elif isinstance(value, list):
        _array(key, value, indent, lines)
    else:
        lines.append(f'{pad}{key}: {_scalar(value)}')


def _array(key, items, indent, lines):
    pad = '  ' * indent
    n = len(items)
    if all(_primitive(i) for i in items):
        lines.append(f'{pad}{key}[{n}]:' + (' ' + ','.join(_scalar(i) for i in items) if items else ''))
        return
    fields = _tabular_fields(items)
    if fields:
        lines.append(f'{pad}{key}[{n}]{{{",".join(_key(f) for f in fields)}}}:')
        for item in items:
            lines.append(f'{pad}  ' + ','.join(_scalar(item[f]) for f in fields))
        return
    lines.append(f'{pad}{key}[{n}]:')
    for item in items:
        if isinstance(item, dict) and item:
            sub = []
            for k, v in item.items():
                _field(_key(k), v, indent + 2, sub)
            sub[0] = f'{pad}  - ' + sub[0].lstrip()
            lines.extend(sub)
        elif isinstance(item, list):
            sub = []
            _array('', item, indent + 2, sub)
            lines.append(f'{pad}  - ' + sub[0].lstrip())
            lines.extend(sub[1:])
        else:
            lines.append(f'{pad}  - {_scalar(item if not isinstance(item, dict) else {})}')


def dumps(value):
    """Encode JSON-compatible data as TOON text (newline-terminated)."""
    lines = []
    if isinstance(value, dict):
        _encode(value, 0, lines)
    elif isinstance(value, list):
        _array('', value, 0, lines)
    else:
        lines.append(_scalar(value))
    return '\n'.join(lines) + '\n'
