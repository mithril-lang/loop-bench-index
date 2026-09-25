"""Every pure generator is executed against a synthetic RDF bundle, both
passing and deliberately broken. Needs `uv` (rdflib is fetched per run):
  python3 -m unittest harness/tests/test_typed_actions.py"""

import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mithril_harness import typed_actions as T  # noqa: E402

ONTOLOGY = """@prefix ex: <http://example.org/o#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:Point a owl:Class .
ex:Border a owl:Class ; rdfs:subClassOf ex:Point .
ex:pid a owl:DatatypeProperty ; rdfs:domain ex:Point .
"""
DATA = """@prefix ex: <http://example.org/o#> .
ex:a a ex:Point ; ex:pid "A" .
ex:b a ex:Border ; ex:pid "B" .
"""
ENTRY = """import sys
from pathlib import Path
b = Path(sys.argv[1])
text = ''.join(p.read_text() + '\\n' for p in sorted(b.glob('*.owl')) + sorted(x for x in b.glob('*.ttl') if x.name != 'unified.ttl'))
text += EXTRA
(b / 'unified.ttl').write_text(text)
"""
QUERY = """PREFIX ex: <http://example.org/o#>
SELECT ?id WHERE { ?p ex:pid ?id } ORDER BY ?id
"""


def sh(command, cwd):
    return subprocess.run(['bash', '-c', command], cwd=cwd, capture_output=True, text=True, timeout=300,
                          env=dict(os.environ, PATH=f'{cwd}/bin:' + os.environ['PATH']))


class Generators(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix='typed-'))
        (cls.root / 'bin').mkdir()
        shim = cls.root / 'bin' / 'python3'
        shim.write_text("#!/bin/sh\nexec uv run --quiet --no-project --with 'rdflib>=7,<8' python \"$@\"\n")
        shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
        cls.bundle = cls.root / 'b1'; cls.bundle.mkdir()
        (cls.bundle / 'onto.owl').write_text(ONTOLOGY)
        (cls.bundle / 'data.ttl').write_text(DATA)
        (cls.root / 'q.rq').write_text(QUERY)

    def entry(self, extra):
        path = self.root / f'entry{abs(hash(extra))}.py'
        path.write_text('EXTRA = ' + repr(extra) + '\n' + ENTRY)
        r = sh(T.run_entrypoint(str(path), str(self.bundle)), self.root)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_inspection_ops(self):
        r = sh(T.list_files(str(self.bundle)), self.root)
        self.assertIn('data.ttl', r.stdout)
        self.assertIn('ex:pid', sh(T.grep_terms([str(self.bundle / 'data.ttl')], ['ex:pid']), self.root).stdout)
        self.assertEqual(sh(T.show_file(str(self.bundle / 'data.ttl'), 2, 2), self.root).stdout.strip(),
                         'ex:a a ex:Point ; ex:pid "A" .')
        r = sh(T.schema_summary(str(self.bundle)), self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('Border', r.stdout); self.assertIn('subClassOf', r.stdout)
        r = sh(T.term_usage(str(self.bundle)), self.root)
        self.assertRegex(r.stdout, r'predicate\t\S*pid\t2')
        r = sh(T.describe_class(str(self.bundle), 'http://example.org/o#Point'), self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('"A"', r.stdout); self.assertNotIn('"B"', r.stdout)  # asserted type only, no entailment

    def test_checks_pass_then_fail_for_the_named_reason(self):
        self.entry('')
        out = str(self.bundle / 'unified.ttl')
        r = sh(T.preservation_check(str(self.bundle)), self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr); self.assertIn('MISSING_FROM_OUTPUT\t0', r.stdout)
        self.assertEqual(sh(T.vocabulary_check(str(self.bundle)), self.root).returncode, 0)
        r = sh(T.run_queries(out, [str(self.root / 'q.rq')]), self.root)
        self.assertIn('ROWS\t2', r.stdout)
        contract = {str(self.root / 'q.rq'): ['id']}
        self.assertEqual(sh(T.result_contract(out, contract), self.root).returncode, 0)
        r = sh(T.result_contract(out, {str(self.root / 'q.rq'): ['identifier']}), self.root)
        self.assertEqual(r.returncode, 1); self.assertIn('MISMATCH', r.stdout)
        r = sh(T.acceptance_check(str(self.root / f'entry{abs(hash(""))}.py'), [str(self.bundle)], [str(self.root / 'q.rq')]), self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr); self.assertIn('ROWS\t2', r.stdout)
        # unknown vocabulary added by the output graph
        self.entry('@prefix ex: <http://example.org/o#> .\nex:a ex:invented "x" .\n')
        r = sh(T.vocabulary_check(str(self.bundle)), self.root)
        self.assertEqual(r.returncode, 1); self.assertIn('UNKNOWN\t<http://example.org/o#invented>', r.stdout)
        # a source triple dropped by the output graph
        path = self.root / 'drop.py'
        path.write_text("import sys\nfrom pathlib import Path\nb=Path(sys.argv[1])\n(b/'unified.ttl').write_text((b/'onto.owl').read_text())\n")
        sh(T.run_entrypoint(str(path), str(self.bundle)), self.root)
        r = sh(T.preservation_check(str(self.bundle)), self.root)
        self.assertEqual(r.returncode, 1); self.assertNotIn('MISSING_FROM_OUTPUT\t0', r.stdout)
        r = sh(T.acceptance_check(str(path), [str(self.bundle)], [str(self.root / 'q.rq')]), self.root)
        self.assertEqual(r.returncode, 1)

    def test_grep_refuses_empty_terms(self):
        with self.assertRaises(ValueError):
            T.grep_terms(['x'], [])

    def test_every_pure_op_is_declared_with_a_tier(self):
        self.assertTrue(all(tier in ('pure', 'authored', 'llm') for tier, _ in T.LIBRARY.values()))


if __name__ == '__main__':
    unittest.main()
