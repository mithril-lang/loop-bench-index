"""Resident Mithril server gives the same answers as the frozen CLI helpers.
Needs kbb and the Mithril runtime (MITHRIL_RUNTIME, MITHRIL_CLASSPATH or `kbb -Spath` there).
  PYTHONPATH=harness/tests <harbor-venv>/bin/python -m unittest harness/tests/test_mithril_server.py"""

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

RUNTIME = Path(os.environ.get('MITHRIL_RUNTIME', '/Users/junkawasaki/.hermes/runtime/mithril'))
if not os.environ.get('MITHRIL_CLASSPATH') and RUNTIME.exists() and shutil.which(os.environ.get('KBB_BIN', 'kbb')):
    os.environ['MITHRIL_CLASSPATH'] = subprocess.run([os.environ.get('KBB_BIN', 'kbb'), '-Spath'], cwd=RUNTIME,
                                                     capture_output=True, text=True).stdout.strip()
import scripted  # noqa: F401,E402
from mithril_harness import loop  # noqa: E402

FIX = Path(__file__).resolve().parent / 'fixtures'
A = 'https://mithril.fund/id/action/terminal/'
SEQUENCE = [('enabled', '', 'true'), ('select', A + 'inspect', 'ls /app'), ('complete', A + 'inspect', 'true'),
            ('enabled', '', 'true'), ('select', A + 'modify', 'echo x > /app/f'), ('complete', A + 'modify', 'false'),
            ('select', A + 'verify', 'true'), ('complete', A + 'verify', 'true'),
            ('select', A + 'finish', 'true'), ('complete', A + 'finish', 'true'), ('enabled', '', 'true')]


@unittest.skipUnless(os.environ.get('MITHRIL_CLASSPATH'), 'Mithril runtime/classpath unavailable: parity not measured')
class Parity(unittest.TestCase):
    def cli(self, script, args):
        started = time.monotonic()
        p = subprocess.run([loop.KBB, '--classpath', loop.CLASSPATH or os.environ['MITHRIL_CLASSPATH'], str(script),
                            *[str(a) for a in args]], cwd=str(loop.MITHRIL), capture_output=True, text=True, timeout=180)
        return json.loads(p.stdout.strip().splitlines()[-1]), time.monotonic() - started

    def test_bpmn_and_task_state_parity(self):
        loop.CLASSPATH = loop.CLASSPATH or os.environ['MITHRIL_CLASSPATH']
        d = Path(tempfile.mkdtemp())
        state_cli, state_srv = d / 'cli.edn', d / 'srv.edn'
        cli_out, cli_time = [], 0.0
        for op, action, outcome in SEQUENCE:
            out, t = self.cli(loop.HELPER, [loop.PROFILE, state_cli, op, action, outcome])
            cli_out.append(out); cli_time += t
        task = FIX / 'railmini-task-state.json'
        docs = {}
        for phase in ('hypothesize', 'reflect'):
            state = json.loads(task.read_text()); state['phase'] = phase
            path = d / f'{phase}.json'; path.write_text(json.dumps(state))
            out, t = self.cli(loop.TASK_HELPER, [path, d / f'{phase}-cli.jsonld', FIX / 'railmini-domain.mith', loop.STATE_SCHEMA])
            cli_out.append(out); cli_time += t
            docs[phase] = path

        async def via_server():
            server = loop.MithrilServer()
            outs = []
            started = time.monotonic()
            try:
                for op, action, outcome in SEQUENCE:
                    outs.append(await server.request('bpmn', [loop.PROFILE, state_srv, op, action, outcome]))
                for phase in ('hypothesize', 'reflect'):
                    outs.append(await server.request('task-state', [docs[phase], d / f'{phase}-srv.jsonld',
                                                                    FIX / 'railmini-domain.mith', loop.STATE_SCHEMA]))
                with self.assertRaises(RuntimeError):
                    await server.request('bpmn', [loop.PROFILE, d / 'bad.edn', 'select', A + 'teleport', 'x'])
                outs.append(await server.request('bpmn', [loop.PROFILE, d / 'after-error.edn', 'enabled', '', 'true']))
            finally:
                await server.close()
            return outs, time.monotonic() - started

        srv_out, srv_time = asyncio.run(via_server())
        self.assertEqual(srv_out[:len(cli_out)], cli_out)
        self.assertEqual(state_srv.read_text(), state_cli.read_text())
        for phase in ('hypothesize', 'reflect'):
            self.assertEqual((d / f'{phase}-srv.jsonld').read_text(), (d / f'{phase}-cli.jsonld').read_text())
        self.assertEqual(srv_out[-1], cli_out[0])  # the server survives a refused request
        self.assertTrue(any(o.get('semantic', {}).get('entailed') for o in cli_out if isinstance(o, dict)))
        print(f'\nPARITY {len(cli_out)} responses; cli {cli_time:.1f}s ({cli_time / len(cli_out):.2f}s/call), '
              f'server {srv_time:.1f}s including start')


if __name__ == '__main__':
    unittest.main()
