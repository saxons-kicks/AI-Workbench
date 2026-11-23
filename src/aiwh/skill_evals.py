"""Opt-in behavioral regression evals for canonical skills, expressed as a promptfoo config.

Nothing here runs a model or third-party code. Cases live in an optional
``evals.yaml`` beside each ``SKILL.md``; this module validates them and renders a
promptfoo configuration that the user may run explicitly (default provider: local Ollama).
"""
import os
from pathlib import Path

import yaml

from .workbench import registry

EVALS_FILE = 'evals.yaml'
DEFAULT_PROVIDER = 'ollama:chat:llama3.1'
PROVIDER_ENV = 'AIWH_EVAL_PROVIDER'
# The skill body is embedded with nunjucks' `dump` filter so quotes and newlines stay valid JSON.
PROMPT_TEMPLATE = ('[{"role": "system", "content": {{ skill | dump }}}, '
                   '{"role": "user", "content": {{ task | dump }}}]')
_CASE_KEYS = {'description', 'prompt', 'assert'}
_VALUELESS = {'is-json', 'contains-json'}


def resolve_provider(provider=None, env=None):
    """Argument wins, then AIWH_EVAL_PROVIDER, then the local Ollama default."""
    env = os.environ if env is None else env
    return (provider or '').strip() or env.get(PROVIDER_ENV, '').strip() or DEFAULT_PROVIDER


def _skill_body(skill_md):
    lines = skill_md.read_text(encoding='utf-8').splitlines()
    end = lines.index('---', 1)  # registry() already guarantees the delimiters exist
    return '\n'.join(lines[end + 1:]).strip() + '\n'


def validate_evals(data, source='evals.yaml'):
    """Return the validated case list or raise ValueError naming the source and field."""
    if not isinstance(data, list) or not data:
        raise ValueError(f'Invalid evals {source}: top level must be a non-empty list of cases')
    seen = set()
    for index, case in enumerate(data, 1):
        where = f'Invalid evals {source}: case {index}'
        if not isinstance(case, dict):
            raise ValueError(f'{where} must be a mapping')
        unknown = sorted(set(case) - _CASE_KEYS)
        if unknown:
            raise ValueError(f'{where} has unknown keys: {", ".join(map(str, unknown))}')
        for key in ('description', 'prompt'):
            if not isinstance(case.get(key), str) or not case[key].strip():
                raise ValueError(f'{where}: {key} must be a non-empty string')
        if case['description'] in seen:
            raise ValueError(f'{where}: duplicate description {case["description"]!r}')
        seen.add(case['description'])
        checks = case.get('assert')
        if not isinstance(checks, list) or not checks:
            raise ValueError(f'{where}: assert must be a non-empty list')
        for number, check in enumerate(checks, 1):
            if (not isinstance(check, dict) or not isinstance(check.get('type'), str)
                    or not check['type'].strip()):
                raise ValueError(f'{where}: assert {number} must be a mapping with a string type')
            bare = check['type'].removeprefix('not-')
            if bare not in _VALUELESS and (check.get('value') in (None, '')):
                raise ValueError(f'{where}: assert {number} ({check["type"]}) requires a value')
    return data


def load_evals(skill_dir):
    """Cases for one skill directory, or None when it has no evals.yaml."""
    path = Path(skill_dir) / EVALS_FILE
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ValueError(f'Invalid evals {path}: {error}') from error
    return validate_evals(data, str(path))


def eval_coverage(skills=None):
    """Names of skills with and without evals.yaml (cases are not validated here)."""
    available = registry()['skills']
    names = _select(available, skills)
    with_evals = [n for n in names if (available[n] / EVALS_FILE).is_file()]
    return {'with_evals': with_evals, 'without': [n for n in names if n not in with_evals]}


def _select(available, skills):
    if not skills:
        return sorted(available)
    unknown = sorted(set(skills) - set(available))
    if unknown:
        raise ValueError(f'Unknown skill(s): {", ".join(unknown)}')
    return sorted(set(skills))


def build_promptfoo_config(skills=None, provider=None):
    """Build the promptfoo config dict. Skills without evals are skipped and listed in
    ``config['metadata']['aiwh_skills_skipped']``."""
    available = registry()['skills']
    names = _select(available, skills)
    tests, covered, skipped = [], [], []
    for name in names:
        cases = load_evals(available[name])
        if cases is None:
            skipped.append(name)
            continue
        covered.append(name)
        body = _skill_body(available[name] / 'SKILL.md')
        for case in cases:
            tests.append({'description': f'{name}: {case["description"]}',
                          'vars': {'skill': body, 'task': case['prompt']},
                          'assert': case['assert']})
    return {
        'description': 'AI Workbench skill behavioral evals (opt-in)',
        'prompts': [PROMPT_TEMPLATE],
        'providers': [resolve_provider(provider)],
        'tests': tests,
        'metadata': {'aiwh_skills_with_evals': covered, 'aiwh_skills_skipped': skipped},
    }


def write_promptfoo_config(path, skills=None, provider=None):
    """Write the config as YAML with LF endings; returns the config dict."""
    config = build_promptfoo_config(skills, provider)
    text = yaml.safe_dump(config, sort_keys=False, allow_unicode=True, width=100)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(text)
    return config
