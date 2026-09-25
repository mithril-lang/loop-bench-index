"""Classifier cases, including each misclassification found while measuring.
  python3 -m unittest harness/tests/test_action_coverage.py"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
import action_coverage as ac  # noqa: E402

A = lambda kind, command: {'action': kind, 'command': command, 'result': {'exit_code': 0}}
ACCEPT = ("python3 /app/pipeline.py /app/b && python3 - <<'PY'\nfrom rdflib.compare import isomorphic\n"
          "g.query(Path('/app/q.rq').read_text())\nPY")


class Classify(unittest.TestCase):
    def tier(self, kind, command, mode='signature'):
        return ac.classify_action(A(kind, command), mode)[0]

    def test_shell_inspection_is_pure(self):
        self.assertEqual(self.tier('inspect', "find /app -maxdepth 2 -type f | sort; grep -nE 'a|b' /app/x.ttl"), 'pure')

    def test_quoted_semicolon_does_not_split(self):
        self.assertEqual(self.tier('inspect', "python3 -c 'import rdflib; print(rdflib.__version__)'"), 'pure')

    def test_bash_c_wrapper_is_unwrapped(self):
        self.assertEqual(self.tier('verify', "bash -lc 'set -e\nfind /app -type f'"), 'pure')

    def test_redirecting_printf_is_a_write(self):
        self.assertEqual(self.tier('modify', "printf 'rdflib>=7\\n' > /app/requirements.txt"), 'llm')
        self.assertIsNone(ac.classify_shell("printf '%s\\n' '--- header ---'"))

    def test_acceptance_signature_versus_strict(self):
        self.assertEqual(self.tier('verify', ACCEPT), 'pure')
        self.assertEqual(self.tier('verify', ACCEPT, 'strict'), 'authored')

    def test_inline_sparql_is_authored(self):
        cmd = "python3 - <<'PY'\ng.query('''PREFIX a: <x#> SELECT ?s WHERE {?s ?p ?o}''')\nPY"
        self.assertEqual(self.tier('inspect', cmd), 'authored')

    def test_heredoc_writes_are_llm(self):
        self.assertEqual(self.tier('modify', "cat > /app/q.rq <<'RQ'\nSELECT * {}\nRQ"), 'llm')

    def test_harness_entries_are_internal(self):
        self.assertEqual(self.tier('verify', 'critical review gate'), 'internal')
        self.assertEqual(self.tier('verify', 'differential'), 'authored')


class Cli(unittest.TestCase):
    def run_cli(self, *paths):
        return subprocess.run([sys.executable, str(TOOLS / 'action_coverage.py'), *paths], capture_output=True, text=True)

    def test_counts_and_refusals(self):
        d = Path(tempfile.mkdtemp())
        good = d / 'r.json'
        good.write_text(json.dumps({'actions': [A('inspect', 'ls /app'), A('modify', "cat > /f <<'X'\nx\nX"),
                                                A('verify', 'critical review gate'), A('finish', 'true')]}))
        r = self.run_cli(str(good))
        self.assertEqual(r.returncode, 0, r.stderr)
        report = json.loads(r.stdout)
        self.assertEqual((report['signature']['model_actions'], report['internal_entries']), (2, 1))
        self.assertEqual(report['signature']['tiers'], {'pure': 1, 'llm': 1})
        empty = d / 'e.json'; empty.write_text(json.dumps({'actions': [A('finish', 'true')]}))
        r = self.run_cli(str(empty))
        self.assertEqual(r.returncode, 2); self.assertIn('SCANNED\t0 model actions', r.stderr)
        bad = d / 'b.json'; bad.write_text('{not json')
        r = self.run_cli(str(bad))
        self.assertEqual(r.returncode, 2); self.assertIn('UNREADABLE', r.stderr)


if __name__ == '__main__':
    unittest.main()
