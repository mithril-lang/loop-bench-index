"""railmini generator, verifier controls and usage accounting (no Podman).
  python3 -m unittest harness/tests/test_micro.py   (needs uv; fetches rdflib)"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

MICRO = Path(__file__).resolve().parents[1] / 'micro'
sys.path.insert(0, str(MICRO))
import railmini  # noqa: E402

UV = ['uv', 'run', '--quiet', '--no-project', '--with', 'rdflib==7.1.4', 'python']


def verify(task, solution):
    app = Path(tempfile.mkdtemp()) / 'app'
    shutil.copytree(MICRO / solution, app)
    pristine = task / 'pristine'
    if not pristine.exists():
        pristine.mkdir()
        shutil.copytree(task / 'app' / '2031-q2', pristine / '2031-q2')
        shutil.copytree(task / 'hidden' / '2031-q3', pristine / '2031-q3')
    r = subprocess.run(UV + [str(MICRO / 'verify.py'), str(task / 'expected.json'), str(pristine)],
                       capture_output=True, text=True, env=dict(os.environ, RAILMINI_APP=str(app)), timeout=300)
    return json.loads(r.stdout.strip().splitlines()[-1])


class Generator(unittest.TestCase):
    def test_deterministic_and_seed_sensitive(self):
        a, b, c = (Path(tempfile.mkdtemp()) for _ in range(3))
        railmini.generate(5, a); railmini.generate(5, b); railmini.generate(6, c)
        read = lambda d: {p.relative_to(d).as_posix(): p.read_text() for p in sorted(d.rglob('*')) if p.is_file()}
        self.assertEqual(read(a), read(b))
        self.assertNotEqual(read(a)['expected.json'], read(c)['expected.json'])
        rows = json.loads((a / 'expected.json').read_text())['queries']['cross_border_points.rq']['rows']
        self.assertTrue(all(len(rows[k]) > 0 for k in ('2031-q2', '2031-q3')))
        self.assertNotIn('2031-q3', (a / 'instruction.md').read_text())  # hidden bundle is never named

    def test_controls_at_every_difficulty(self):
        for difficulty, total in ((1, 10), (2, 10), (3, 13)):
            task = Path(tempfile.mkdtemp()); railmini.generate(11, task, difficulty)
            good = verify(task, 'reference')
            self.assertEqual((good['passed'], good['total']), (total, total), difficulty)
            bad = verify(task, 'naive')
            failed = sorted(k for k, v in bad['assertions'].items() if not v)
            self.assertTrue(failed and all('_rows_' in k for k in failed), (difficulty, failed))
            q2 = json.loads((task / 'expected.json').read_text())['queries'].get('qualified_points.rq')
            if difficulty == 3:
                self.assertTrue(all(q2['rows'][b] for b in ('2031-q2', '2031-q3')), 'level 3 second query must be nonempty')

    def test_level_one_is_unchanged_by_later_levels(self):
        a, b = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        railmini.generate(101, a)
        (b / 'x').mkdir(); railmini.generate(101, b / 'x', 1)
        read = lambda d: {p.relative_to(d).as_posix(): p.read_text() for p in sorted(d.rglob('*')) if p.is_file()}
        self.assertEqual(read(a), read(b / 'x'))
        self.assertNotIn('rl:submittedIn', (a / 'app' / '2031-q2' / 'ontology_core.owl').read_text())


class Usage(unittest.TestCase):
    def test_totals_split_cache_and_count_failures(self):
        sys.path.insert(0, str(MICRO))
        from run_micro import usage_totals
        d = Path(tempfile.mkdtemp())
        (d / 'call-000.json').write_text(json.dumps({'input_tokens': 100, 'cache_read_tokens': 900, 'output_tokens': 50,
                                                     'estimated_cost_usd': 0.001}))
        (d / 'call-001-failed-0.json').write_text(json.dumps({'input_tokens': 10, 'partial': True}))
        t = usage_totals(d)
        self.assertEqual((t['calls'], t['failed_attempts'], t['cache_read_tokens'], t['cost_missing']), (1, 1, 900, 1))
        self.assertEqual(t['cache_hit_ratio'], round(900 / 1010, 4))


if __name__ == '__main__':
    unittest.main()
