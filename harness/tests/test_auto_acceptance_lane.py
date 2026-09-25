"""AutoAcceptance through the full loop (scripted model, local bash, uv rdflib).
Run: PYTHONPATH=harness/tests <harbor-venv>/bin/python -m unittest harness/tests/test_auto_acceptance_lane.py"""

import asyncio
import json
import os
import types
import unittest

import test_acceptance as fixture  # builds the synthetic task and sets the copy root
import scripted  # noqa: F401
from scripted import FakeEnv, Scripted

from mithril_harness import lanes

os.environ['PATH'] = f'{fixture.ROOT}/bin:' + os.environ['PATH']


def act(action, command):
    return json.dumps({'action': action, 'command': command, 'reason': 'r'})


def run_lane(cls, replies):
    agent = type('T', (Scripted, cls), {})(logs_dir=fixture.ROOT / 'logs')
    agent.replies = list(replies)
    context = types.SimpleNamespace(metadata=None)
    instruction = fixture.INSTRUCTION + '\nTarget data lives under /app/2024-q2 for the probe.'
    asyncio.run(agent.run(instruction, FakeEnv(), context))
    return agent, context


class Lane(unittest.TestCase):
    def test_acceptance_report_follows_each_modify(self):
        replies = [json.dumps(fixture.SPEC),
                   act('modify', f'touch {fixture.ROOT}/build.py'),
                   act('inspect', 'true'),
                   act('finish', 'true'), act('verify', 'true'), act('finish', 'true')]
        agent, context = run_lane(lanes.AutoAcceptanceLane, replies)
        modify = [h for h in agent.history if h['action'] == 'modify'][0]
        self.assertIn('[HARNESS ACCEPTANCE CHECK after modify: exit 0]', modify['result']['stdout'])
        inspect = [h for h in agent.history if h['action'] == 'inspect'][0]
        self.assertNotIn('HARNESS ACCEPTANCE CHECK after modify', inspect['result']['stdout'])
        self.assertEqual((context.metadata['acceptance_runs'], context.metadata['acceptance_pass']), (1, 1))
        self.assertTrue(context.metadata['acceptance_spec_digest'].startswith('sha256:'))
        self.assertEqual([k for k, _ in agent.prompts[:2]], ['prefill', 'acceptance-prefill'])
        self.assertIn('HARNESS ACCEPTANCE CHECK (applies to this run)', agent.prompts[2][1])

    def test_unverifiable_spec_fails_closed(self):
        bad = dict(fixture.SPEC, entrypoint='/app/invented.py')
        with self.assertRaises(RuntimeError) as caught:
            run_lane(lanes.AutoAcceptanceLane, [json.dumps(bad)])
        self.assertIn('REFUSE acceptance spec: not-in-instruction:entrypoint:/app/invented.py', str(caught.exception))

    def test_mithril_lane_runs_no_acceptance(self):
        replies = [act('modify', f'touch {fixture.ROOT}/build.py'), act('finish', 'true'),
                   act('verify', 'true'), act('finish', 'true')]
        agent, context = run_lane(lanes.MithrilLane, replies)
        self.assertNotIn('HARNESS ACCEPTANCE', json.dumps(agent.history))
        self.assertNotIn('acceptance_runs', context.metadata)


if __name__ == '__main__':
    unittest.main()
