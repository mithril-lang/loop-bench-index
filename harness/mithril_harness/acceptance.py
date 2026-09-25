"""Acceptance spec: typed parameters of the task's own acceptance conditions.

The model proposes the spec once (one metered call). `validate_spec` admits it
only if every path, file name and column name appears verbatim in the
instruction, the entrypoint and query files are required artifacts, and the
target bundle is one of the bundles. Otherwise it refuses with literal
reasons. `acceptance_command` turns an admitted spec into one harness-generated
command built only from `typed_actions` generators. Non-target bundles are
copied first, so the check never writes into them.
"""

import hashlib
import json
import os
from pathlib import PurePosixPath

from .typed_actions import acceptance_check, result_contract

COPY_ROOT = os.environ.get('HARNESS_ACCEPTANCE_COPY_ROOT', '/tmp/harness-acceptance')  # inside the task container
SPEC_KEYS = ('entrypoint', 'bundles', 'target_bundle', 'output_file', 'queries')


def spec_prompt(instruction):
    return ('Extract the acceptance parameters this task states. Return exactly one JSON object and no markdown: '
            '{"entrypoint":"absolute path of the script that builds the output",'
            '"bundles":["absolute paths of every input directory the task names"],'
            '"target_bundle":"the directory the solution must process",'
            '"output_file":"file name the script writes into a bundle",'
            '"queries":[{"path":"absolute path of a query file","columns":["exact result column names, if stated"]}]}. '
            'Copy every value verbatim from the task text; use [] for columns the task does not name. '
            'Do not solve the task.\nTASK:\n' + instruction)


def validate_spec(spec, instruction, required):
    """Returns (normalized_spec, reasons). reasons == [] means admitted."""
    reasons = []
    if not isinstance(spec, dict) or any(k not in spec for k in SPEC_KEYS):
        return None, ['spec-missing-keys']
    verbatim = lambda value: isinstance(value, str) and value.strip() and value.strip().rstrip('/') in instruction
    entry = spec['entrypoint']
    if not verbatim(entry):
        reasons.append(f'not-in-instruction:entrypoint:{entry}')
    elif entry not in required:
        reasons.append(f'entrypoint-not-required-artifact:{entry}')
    bundles = spec['bundles'] if isinstance(spec['bundles'], list) else []
    if not bundles:
        reasons.append('no-bundles')
    for bundle in bundles:
        if not verbatim(bundle):
            reasons.append(f'not-in-instruction:bundle:{bundle}')
    target = spec['target_bundle']
    if not isinstance(target, str) or target.rstrip('/') not in [str(b).rstrip('/') for b in bundles]:
        reasons.append(f'target-not-a-bundle:{target}')
    if not verbatim(spec['output_file']) or '/' in str(spec['output_file']):
        reasons.append(f'not-in-instruction:output_file:{spec["output_file"]}')
    queries = spec['queries'] if isinstance(spec['queries'], list) else []
    if not queries:
        reasons.append('no-queries')
    normalized_queries = []
    for query in queries:
        path = query.get('path') if isinstance(query, dict) else None
        columns = query.get('columns', []) if isinstance(query, dict) else []
        if not verbatim(path):
            reasons.append(f'not-in-instruction:query:{path}')
        elif path not in required:
            reasons.append(f'query-not-required-artifact:{path}')
        if not isinstance(columns, list):
            reasons.append(f'columns-not-list:{path}')
            columns = []
        for column in columns:
            if not isinstance(column, str) or f'`{column}`' not in instruction:
                reasons.append(f'column-not-in-instruction:{path}:{column}')
        normalized_queries.append({'path': path, 'columns': columns})
    if reasons:
        return None, reasons
    normalized = {'entrypoint': entry, 'bundles': [b.rstrip('/') for b in bundles],
                  'target_bundle': target.rstrip('/'), 'output_file': spec['output_file'],
                  'queries': normalized_queries}
    return normalized, []


def spec_digest(spec):
    return 'sha256:' + hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()


def acceptance_command(spec):
    target = spec['target_bundle']
    copies = [f'{COPY_ROOT}/{PurePosixPath(b).name}' for b in spec['bundles'] if b != target]
    setup = [f'rm -rf {COPY_ROOT} && mkdir -p {COPY_ROOT}']
    for bundle, copy in zip([b for b in spec['bundles'] if b != target], copies):
        setup.append(f'cp -R {bundle} {copy} && rm -f {copy}/{spec["output_file"]}')
    checks = acceptance_check(spec['entrypoint'], [target] + copies,
                              [q['path'] for q in spec['queries']], spec['output_file'])
    contracts = {q['path']: q['columns'] for q in spec['queries'] if q['columns']}
    tail = []
    if contracts:
        for bundle in [target] + copies:
            tail += [f'echo "== columns {bundle}"', result_contract(f'{bundle}/{spec["output_file"]}', contracts)]
    return 'set -e\n' + '\n'.join(setup) + '\n' + checks + ('\n' + '\n'.join(tail) if tail else '')
