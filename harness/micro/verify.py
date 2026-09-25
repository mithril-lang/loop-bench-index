"""railmini verifier. Runs inside the task container, after the agent stops:
  python3 verify.py <expected.json> <pristine-bundles-dir>
Each bundle is copied fresh (never the agent's working copy), the agent's
pipeline runs on it, and the query runs over its unified.ttl. Prints one JSON
object: {"assertions": {name: bool}, "passed": n, "total": n}. Exit 0 always
when it measured; exit 2 when it could not measure (bad arguments)."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

APP = os.environ.get('RAILMINI_APP', '/app')
BASE_REQUIRED = [f'{APP}/pipeline.py', f'{APP}/requirements.txt']


def load(paths):
    from rdflib import Graph
    g = Graph()
    for p in paths:
        g.parse(p, format='turtle')
    return g


def norm(value):
    if value is None:
        return None
    text = str(value)
    try:
        return f'{float(text):.4f}'
    except ValueError:
        return text


def check_bundle(src, name, queries, out):
    """queries: {file: expected rows for this bundle}. Returns {file: columns or None}."""
    from rdflib import BNode, RDF
    work = Path(tempfile.mkdtemp()) / name
    shutil.copytree(src, work)
    sources = sorted(work.glob('*.owl')) + sorted(p for p in work.glob('*.ttl') if p.name != 'unified.ttl')
    run = subprocess.run([sys.executable, f'{APP}/pipeline.py', str(work)], capture_output=True, text=True, timeout=120)
    unified = work / 'unified.ttl'
    out[f'{name}_pipeline_runs'] = run.returncode == 0 and unified.exists()
    columns = {}
    if not out[f'{name}_pipeline_runs']:
        out[f'{name}_preserves_sources'] = out[f'{name}_vocabulary'] = False
        for q in queries:
            out[f'{name}_rows_{q}'] = False
            columns[q] = None
        return columns
    src_g, out_g = load(sources), load([unified])
    out[f'{name}_preserves_sources'] = all(t in out_g for t in src_g if not any(isinstance(x, BNode) for x in t))
    known = set(src_g.predicates()) | set(src_g.objects(None, RDF.type)) | set(src_g.subjects())
    added = set(out_g) - set(src_g)
    out[f'{name}_vocabulary'] = all(p in known and (p != RDF.type or o in known) for s, p, o in added)
    for q, expected in queries.items():
        try:
            result = out_g.query(Path(f'{APP}/{q}').read_text())
            rows = [[norm(v) for v in row] for row in result]
            columns[q] = [str(v) for v in result.vars]
        except Exception:  # a failing query is a failed assertion, not an unmeasured run
            out[f'{name}_rows_{q}'] = False
            columns[q] = None
            continue
        out[f'{name}_rows_{q}'] = rows == [[norm(v) for v in row] for row in expected]
    return columns


def main():
    if len(sys.argv) != 3:
        print('usage: verify.py <expected.json> <pristine-bundles-dir>', file=sys.stderr)
        raise SystemExit(2)
    spec = json.loads(Path(sys.argv[1]).read_text())
    root = Path(sys.argv[2])
    queries = spec['queries']
    out = {'files_exist': all(Path(p).is_file() for p in BASE_REQUIRED + [f'{APP}/{q}' for q in queries])}
    target_columns = {}
    for name in ('2031-q2', '2031-q3'):  # target and hidden; the example bundle is not scored
        got = check_bundle(root / name, name, {q: v['rows'][name] for q, v in queries.items()}, out)
        if name == '2031-q2':
            target_columns = got
    for q, v in queries.items():
        out[f'columns_{q}'] = target_columns.get(q) == v['columns']
    passed = sum(bool(v) for v in out.values())
    print(json.dumps({'assertions': out, 'passed': passed, 'total': len(out)}))


if __name__ == '__main__':
    main()
