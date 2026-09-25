"""DifferentialJudge through the full harness loop (scripted model, local bash).
Run: <harbor-venv>/bin/python -m unittest harness/tests/test_judge_lane.py"""

import json
import tempfile
import unittest
from pathlib import Path

import scripted  # noqa: F401
from scripted import Scripted, make_task, run_agent

from mithril_harness import lanes


def act(action, command, **extra):
    return json.dumps(dict({'action': action, 'command': command, 'reason': 'r'}, **extra))


class JudgeLane(unittest.TestCase):
    def run_scenario(self, cls, tail=()):
        root = Path(tempfile.mkdtemp(prefix='judge-'))
        _, a, b = make_task(root)
        src = root / 'src.tsv'; src.write_text('a\t1\nb\t2\n')
        derive = root / 'derive.sh'; derive.write_text(f'cut -f1,2 {src}\n')
        cheat = root / 'cheat.sh'; cheat.write_text(f'cat {a}\n')
        pair = {'name': 'q1', 'answer_command': f'cat {a}', 'answer_paradigm': 'stored rows',
                'derivation_command': f'bash {derive}', 'derivation_paradigm': 'cut over source'}
        spec = {'pairs': [pair], 'uncovered': [{'path': str(b), 'reason': 'second output checked elsewhere'}]}
        replies = [
            act('modify', f'printf "a\\t1\\n" > {a}; printf "x\\n" > {b}'),
            act('finish', 'true'),                                                    # no passing differential
            act('verify', 'differential', differential=spec),                         # mismatch: b 2 missing
            act('verify', 'differential', differential={'pairs': [dict(pair, derivation_command=f'bash {cheat}')],
                                                        'uncovered': spec['uncovered']}),  # independence refused
            act('modify', f'printf "b\\t2.0\\na\\t1\\n" > {a}'),
            act('verify', 'differential', differential=spec),                         # match
            act('modify', f'printf "a\\t1\\n" > {a}'),
            act('finish', 'true'),                                                    # stale
            act('modify', f'printf "a\\t1\\nb\\t2\\n" > {a}'),
            act('verify', 'differential', differential=spec),                         # match again
            act('finish', 'true'),                                                    # critical review hold
            act('verify', 'differential', differential=spec),                         # passing verify: review done
            act('finish', 'true')] + list(tail)                                       # admitted
        agent, context = run_agent(type('T', (Scripted, cls), {}), root, replies=replies)
        return agent, context, root

    def test_judge_gates_finish(self):
        agent, context, root = self.run_scenario(lanes.JudgeLane)
        stderr = [h['result']['stderr'] for h in agent.history]
        self.assertIn('Finish refused by differential gate: no-passing-differential', stderr)
        self.assertIn('Finish refused by differential gate: differential-stale-after-artifact-change', stderr)
        exits = [r['exit'] for r in agent.differential_receipts]
        self.assertEqual(exits, [1, 2, 0, 0, 0])
        self.assertEqual(agent.differential_receipts[0]['pairs'][0]['missing'], [['b', '2']])
        self.assertEqual(agent.differential_receipts[1]['pairs'][0]['violations'],
                         [f'derivation-file-mentions:{root}/cheat.sh:q1.rq'])
        self.assertEqual(agent.history[-1]['action'], 'finish')
        self.assertEqual(context.metadata['differential_exit_counts'], {'0': 3, '1': 1, '2': 1})
        self.assertEqual(context.metadata['differential_gate_refusals'], 2)
        self.assertIn('HARNESS FINISH GATE', agent.prompts[1][1])

    def test_mithril_lane_without_judge_finishes_earlier(self):
        # Control: the same replies without the judge admit the first finish that passes
        # the v6 gates, so the judge is what holds finish in the test above.
        agent, context, _ = self.run_scenario(lanes.MithrilLane,
                                              tail=[act('verify', 'true'), act('finish', 'true')])
        self.assertNotIn('differential_gate', context.metadata)
        self.assertFalse(any('differential gate' in h['result']['stderr'] for h in agent.history))
        self.assertEqual(agent.history[-1]['action'], 'finish')
        self.assertNotIn('HARNESS FINISH GATE', agent.prompts[1][1])


if __name__ == '__main__':
    unittest.main()
