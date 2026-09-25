"""Acceptance spec admission and the generated acceptance command.
  python3 -m unittest harness/tests/test_acceptance.py   (needs uv; fetches rdflib)"""

import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(tempfile.mkdtemp(prefix='acceptance-'))
os.environ['HARNESS_ACCEPTANCE_COPY_ROOT'] = str(ROOT / 'copies')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mithril_harness.acceptance import acceptance_command, validate_spec  # noqa: E402

ONTOLOGY = """@prefix ex: <http://example.org/o#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
ex:Point a owl:Class .
ex:pid a owl:DatatypeProperty .
"""
DATA = '@prefix ex: <http://example.org/o#> .\nex:a a ex:Point ; ex:pid "A" .\n'
ENTRY = """import sys
from pathlib import Path
b = Path(sys.argv[1])
parts = [(b / 'onto.owl').read_text()] + [p.read_text() for p in sorted(x for x in b.glob('*.ttl') if x.name != 'unified.ttl')]
(b / 'unified.ttl').write_text('\\n'.join(parts))
"""
SHAPES = '@prefix sh: <http://www.w3.org/ns/shacl#> .\n<http://example.org/o#PointShape> a sh:NodeShape .\n'
QUERY = 'PREFIX ex: <http://example.org/o#>\nSELECT ?pointId WHERE { ?p ex:pid ?pointId }\n'


def setup_task():
    (ROOT / 'bin').mkdir(exist_ok=True)
    shim = ROOT / 'bin' / 'python3'
    shim.write_text("#!/bin/sh\nexec uv run --quiet --no-project --with 'rdflib>=7,<8' python \"$@\"\n")
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    for name in ('cur', 'old'):
        d = ROOT / name; d.mkdir(exist_ok=True)
        (d / 'onto.owl').write_text(ONTOLOGY); (d / 'data.ttl').write_text(DATA)
        (d / 'shapes.owl').write_text(SHAPES)  # not a source: must not be required in the output
    (ROOT / 'build.py').write_text(ENTRY)
    (ROOT / 'q.rq').write_text(QUERY)
    instruction = (f'Bundles `{ROOT}/cur/` (current) and `{ROOT}/old/` (example).\n'
                   f'Create the following files:\n- `{ROOT}/build.py`\n- `{ROOT}/q.rq`\n\n'
                   f'`{ROOT}/build.py` reads `onto.owl` and every `.ttl` file and writes `unified.ttl`. '
                   f'Other files such as `shapes.owl` are not inputs. `{ROOT}/q.rq` uses exactly these columns: `pointId`.')
    required = [f'{ROOT}/build.py', f'{ROOT}/q.rq']
    spec = {'entrypoint': f'{ROOT}/build.py', 'bundles': [f'{ROOT}/cur/', f'{ROOT}/old/'],
            'target_bundle': f'{ROOT}/cur/', 'output_file': 'unified.ttl',
            'sources': ['onto.owl', '*.ttl'],
            'queries': [{'path': f'{ROOT}/q.rq', 'columns': ['pointId']}]}
    return instruction, required, spec


INSTRUCTION, REQUIRED, SPEC = setup_task()


def run(command):
    return subprocess.run(['bash', '-c', command], capture_output=True, text=True, timeout=300,
                          env=dict(os.environ, PATH=f'{ROOT}/bin:' + os.environ['PATH']))


class Admission(unittest.TestCase):
    def test_admits_verbatim_spec(self):
        spec, reasons = validate_spec(SPEC, INSTRUCTION, REQUIRED)
        self.assertEqual(reasons, [])
        self.assertEqual(spec['target_bundle'], f'{ROOT}/cur')

    def test_refusals_are_literal(self):
        cases = [
            (dict(SPEC, entrypoint='/app/other.py'), 'not-in-instruction:entrypoint:/app/other.py'),
            (dict(SPEC, target_bundle='/elsewhere'), 'target-not-a-bundle:/elsewhere'),
            (dict(SPEC, queries=[{'path': f'{ROOT}/q.rq', 'columns': ['id']}]), f'column-not-in-instruction:{ROOT}/q.rq:id'),
            (dict(SPEC, output_file='out.ttl'), 'not-in-instruction:output_file:out.ttl'),
            ({'entrypoint': 'x'}, 'spec-missing-keys'),
            (dict(SPEC, sources=['*.owl']), 'source-not-in-instruction:*.owl'),
            (dict(SPEC, sources=['../etc/passwd']), 'source-not-in-instruction:../etc/passwd'),
            (dict(SPEC, sources=[]), 'no-sources'),
        ]
        for spec, reason in cases:
            self.assertIn(reason, validate_spec(spec, INSTRUCTION, REQUIRED)[1])
        self.assertIn(f'entrypoint-not-required-artifact:{ROOT}/build.py',
                      validate_spec(SPEC, INSTRUCTION, [f'{ROOT}/q.rq'])[1])


class Command(unittest.TestCase):
    def test_passes_then_fails_on_columns_and_leaves_example_bundle_untouched(self):
        spec, _ = validate_spec(SPEC, INSTRUCTION, REQUIRED)
        r = run(acceptance_command(spec))
        self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-2000:])
        self.assertIn('MISSING_FROM_OUTPUT\t0', r.stdout)
        self.assertIn('CONTRACT', r.stdout)
        self.assertTrue((ROOT / 'cur' / 'unified.ttl').exists())
        self.assertFalse((ROOT / 'old' / 'unified.ttl').exists())
        (ROOT / 'q.rq').write_text(QUERY.replace('?pointId', '?id'))
        try:
            r = run(acceptance_command(spec))
            self.assertEqual(r.returncode, 1)
            self.assertIn('MISMATCH', r.stdout)
        finally:
            (ROOT / 'q.rq').write_text(QUERY)


if __name__ == '__main__':
    unittest.main()
