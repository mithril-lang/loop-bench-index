"""reachmini generator, verifier controls, and graphkit (no Podman; needs uv for rdflib).
  python3 -m unittest harness/tests/test_reachmini.py"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ATTACK = Path(__file__).resolve().parents[1] / 'attack'
sys.path.insert(0, str(ATTACK)); sys.path.insert(0, str(ATTACK / 'container'))
import reachmini  # noqa: E402
import graphkit  # noqa: E402

UV = ['uv', 'run', '--quiet', '--no-project', '--with', 'rdflib==7.1.4', 'python']
# break name -> (old, new, noise levels where it must fail)
BREAKS = {'no-deny': ("    if (key(a), key(b)) not in denied:\n", "    if True:\n", {1, 2, 3}),
          'no-expiry': ("    if str(next(g.objects(d, RC.validUntil))) >= CURRENT:\n", "    if True:\n", {1, 2, 3}),
          'no-normalize': ("    return str(name).lower().split('.')[0]\n", "    return str(name)\n", {2}),
          'off-by-one': ("dd <= LIMIT", "dd < LIMIT", {0, 1, 2, 3}),
          'no-alias': ("    return alias_map.get(name, norm(name))\n", "    return norm(name)\n", {3})}


def solution(task, breaks=None):
    k = json.loads((task / 'expected.json').read_text())['k']
    app = Path(tempfile.mkdtemp()) / 'app'; app.mkdir()
    text = (ATTACK / 'reference' / 'solve.py').read_text().replace('__K__', str(k))
    if breaks:
        old, new, _ = BREAKS[breaks]
        assert old in text, breaks
        text = text.replace(old, new, 1)
    (app / 'solve.py').write_text(text); (app / 'requirements.txt').write_text('')
    return app


def verify(task, app):
    pristine = task / 'pristine'
    if not pristine.exists():
        pristine.mkdir(); shutil.copytree(task / 'app' / 'env-t', pristine / 'env-t'); shutil.copytree(task / 'hidden' / 'env-h', pristine / 'env-h')
    r = subprocess.run(UV + [str(ATTACK / 'verify.py'), str(task / 'expected.json'), str(pristine)], capture_output=True,
                       text=True, env=dict(os.environ, REACHMINI_APP=str(app)), timeout=300)
    return json.loads(r.stdout.strip().splitlines()[-1])


class Generator(unittest.TestCase):
    def test_deterministic_and_hidden_not_named(self):
        a, b = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        reachmini.generate(5, a, 6, 30, 3)
        subprocess.run([sys.executable, str(ATTACK / 'reachmini.py'), '--seed', '5', '--depth', '6', '--size', '30',
                        '--noise', '3', '--out', str(b)], check=True, capture_output=True)  # fresh process: no hash randomness
        read = lambda d: {p.relative_to(d).as_posix(): p.read_text() for p in sorted(d.rglob('*')) if p.is_file()}
        self.assertEqual(read(a), read(b))
        self.assertNotIn('env-h', (a / 'instruction.md').read_text())
        rows = json.loads((a / 'expected.json').read_text())['rows']
        self.assertTrue(rows['env-t']['exposure_paths.tsv'] and rows['env-h']['exposure_paths.tsv'])

    def test_controls_every_noise_level(self):
        for noise in (0, 1, 2, 3):
            task = Path(tempfile.mkdtemp()); reachmini.generate(21, task, 6, 30, noise)
            good = verify(task, solution(task))
            self.assertEqual((good['passed'], good['total']), (7, 7), noise)
            for name, (_, _, level) in BREAKS.items():
                if noise in level:
                    bad = verify(task, solution(task, name))
                    self.assertLess(bad['passed'], 7, (noise, name))


class Graphkit(unittest.TestCase):
    def test_bfs_minimum_hops_with_cycle(self):
        adj = {'a': ['b', 'c'], 'b': ['d'], 'c': ['d'], 'd': ['a', 'e'], 'e': []}
        self.assertEqual(graphkit.bfs(adj, 'a'), {'a': 0, 'b': 1, 'c': 1, 'd': 2, 'e': 3})
        self.assertEqual(graphkit.within(graphkit.bfs(adj, 'a'), 2), {'b', 'c', 'd'})


if __name__ == '__main__':
    unittest.main()
