"""Task-agnostic row differential and independence check for the v9 finish gate.

Exit semantics follow v7 `query_differential.py`: 0 = both sides nonempty and
equal as multisets, 1 = measured mismatch, 2 = unmeasured (a side failed or
produced no rows, or the submission is invalid). Refusals carry a literal
reason string so a negative test can pin why it refused.
"""

import re
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath

PATH_RE = re.compile(r'(/[A-Za-z0-9_.\-/]+)')
MAX_REPORTED_ROWS = 20


def canonical_field(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == '<' and value[-1] == '>':
        value = value[1:-1]
    if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
        value = value[1:-1]
    try:
        number = Decimal(value)
        if number.is_finite():
            normal = number.normalize()
            return format(normal, 'f') if normal == normal.to_integral() else str(normal)
    except InvalidOperation:
        pass
    return value


def parse_rows(text):
    """One row per nonblank line, tab-separated fields, no header."""
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        rows.append(tuple(canonical_field(field) for field in line.split('\t')))
    return rows


def compare(answer, derivation):
    """answer/derivation: {'exit_code': int, 'stdout': str}. Returns a receipt."""
    receipt = {'answer_rows': None, 'derivation_rows': None,
               'missing': [], 'extra': [], 'missing_count': 0, 'extra_count': 0}
    if answer.get('exit_code') != 0:
        return dict(receipt, exit=2, reason='answer-command-failed')
    if derivation.get('exit_code') != 0:
        return dict(receipt, exit=2, reason='derivation-command-failed')
    answer_rows = Counter(parse_rows(answer.get('stdout', '')))
    derived_rows = Counter(parse_rows(derivation.get('stdout', '')))
    receipt['answer_rows'] = sum(answer_rows.values())
    receipt['derivation_rows'] = sum(derived_rows.values())
    if not answer_rows:
        return dict(receipt, exit=2, reason='answer-produced-no-rows')
    if not derived_rows:
        return dict(receipt, exit=2, reason='derivation-produced-no-rows')
    missing = sorted((derived_rows - answer_rows).elements())
    extra = sorted((answer_rows - derived_rows).elements())
    receipt.update({'missing': [list(r) for r in missing[:MAX_REPORTED_ROWS]],
                    'extra': [list(r) for r in extra[:MAX_REPORTED_ROWS]],
                    'missing_count': len(missing), 'extra_count': len(extra)})
    if missing or extra:
        return dict(receipt, exit=1, reason='row-mismatch')
    return dict(receipt, exit=0, reason='rows-match')


def command_paths(command):
    return sorted(set(PATH_RE.findall(command or '')))


def forbidden_names(answer_command, required):
    """Basenames the derivation may not mention: required artifacts and answer inputs."""
    names = {PurePosixPath(p).name for p in required}
    names |= {PurePosixPath(p).name for p in command_paths(answer_command)
              if '.' in PurePosixPath(p).name}
    return sorted(n for n in names if n)


def independence_violations(pair, required, referenced_contents):
    """pair: submitted spec. referenced_contents: {path: text} for files the
    derivation command references. Returns a list of literal reasons."""
    reasons = []
    answer_cmd = pair.get('answer_command', '')
    derivation_cmd = pair.get('derivation_command', '')
    if answer_cmd.strip() == derivation_cmd.strip():
        reasons.append('derivation-identical-to-answer')
    answer_paradigm = str(pair.get('answer_paradigm', '')).strip().lower()
    derivation_paradigm = str(pair.get('derivation_paradigm', '')).strip().lower()
    if not answer_paradigm or not derivation_paradigm:
        reasons.append('paradigm-undeclared')
    elif answer_paradigm == derivation_paradigm:
        reasons.append('paradigm-not-distinct')
    names = forbidden_names(answer_cmd, required)
    for name in names:
        if name in derivation_cmd:
            reasons.append(f'derivation-command-mentions:{name}')
        for path, text in sorted(referenced_contents.items()):
            if name in text:
                reasons.append(f'derivation-file-mentions:{path}:{name}')
    return reasons


def coverage_gaps(pairs, uncovered, required):
    """Every required artifact must be referenced by an answer command or be
    declared uncovered with a nonempty reason."""
    referenced = set()
    for pair in pairs:
        text = pair.get('answer_command', '')
        referenced |= {p for p in required if p in text or PurePosixPath(p).name in text}
    declared = {item.get('path') for item in uncovered
                if isinstance(item, dict) and str(item.get('reason', '')).strip()}
    return sorted(p for p in required if p not in referenced and p not in declared)


def validate_submission(spec):
    """Shape check of the model's differential field. Returns (pairs, uncovered, reason)."""
    if not isinstance(spec, dict):
        return [], [], 'differential-not-object'
    pairs = spec.get('pairs')
    uncovered = spec.get('uncovered', [])
    if not isinstance(pairs, list) or not pairs:
        return [], [], 'differential-has-no-pairs'
    if not isinstance(uncovered, list):
        return [], [], 'uncovered-not-list'
    for pair in pairs:
        if not isinstance(pair, dict) or not all(
                isinstance(pair.get(k), str) and pair.get(k).strip()
                for k in ('name', 'answer_command', 'derivation_command')):
            return [], [], 'pair-missing-name-or-commands'
    return pairs[:6], uncovered, None
