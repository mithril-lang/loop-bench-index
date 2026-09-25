"""Harness lanes reproduce the frozen v6/v7 agents byte for byte.

Run with the Harbor interpreter from the repository root:
  <harbor-venv>/bin/python -m unittest harness/tests/test_equivalence.py
Each pair runs the same scripted scenario (inspect budget, malformed JSON
repair, critical review, missing-artifact refusal, finish) and compares every
model prompt, the action history, hypotheses, task-state phases and Jev inputs.
"""

import filecmp
import tempfile
import unittest
from pathlib import Path

import scripted  # noqa: F401  (sets env and sys.path before agent imports)
from scripted import REPO, Scripted, run_agent

import agent as v6
import jev_interleave as v6_jev
import knowledge_agent as v7
from mithril_harness import components, lanes

CURRENT = {}


def legacy_decide(state, api_key):
    return CURRENT['agent'].fake_jev(state, api_key)


v6_jev.decide = legacy_decide


def pair(legacy_cls, harness_cls):
    results = []
    for cls in (legacy_cls, harness_cls):
        test_cls = type('T' + cls.__name__, (Scripted, cls), {})
        root = Path(tempfile.mkdtemp(prefix='eq-'))
        def prepare(agent):
            CURRENT['agent'] = agent
            agent.decide = agent.fake_jev
        agent, context = run_agent(test_cls, root, prepare=prepare)
        results.append((agent, context, root))
    return results


def normalize(text, root):
    return text.replace(str(root), '<ROOT>')


class Equivalence(unittest.TestCase):
    def assert_same(self, legacy_cls, harness_cls, expect_jev):
        (old, old_ctx, old_root), (new, new_ctx, new_root) = pair(legacy_cls, harness_cls)
        old_prompts = [(k, normalize(p, old_root)) for k, p in old.prompts]
        new_prompts = [(k, normalize(p, new_root)) for k, p in new.prompts]
        self.assertGreater(len(old_prompts), 15, 'scenario did not exercise the loop')
        self.assertEqual(len(old_prompts), len(new_prompts))
        for i, (o, n) in enumerate(zip(old_prompts, new_prompts)):
            self.assertEqual(o, n, f'prompt {i} differs')
        norm_hist = lambda a, r: [normalize(repr(h), r) for h in a.history]
        self.assertEqual(norm_hist(old, old_root), norm_hist(new, new_root))
        self.assertEqual(old.hypotheses, new.hypotheses)
        self.assertEqual([r['phase'] for r in old.task_state_receipts],
                         [r['phase'] for r in new.task_state_receipts])
        self.assertEqual([normalize(s, old_root) for s in old.jev_states],
                         [normalize(s, new_root) for s in new.jev_states])
        self.assertEqual(bool(old.jev_states), expect_jev)
        self.assertEqual(old.history[-1]['action'], 'finish')
        for key in ('step_count', 'hermes_calls', 'semantic_receipts', 'task_state_receipts',
                    'jev_calls', 'critical_review_enabled', 'artifact_count_confirmed'):
            self.assertEqual(old_ctx.metadata[key], new_ctx.metadata[key], key)
        return old, new

    def test_mithril_lane(self):
        old, _ = self.assert_same(v6.MithrilDomainPrefillAgent, lanes.MithrilLane, False)
        refusals = [h['result']['stderr'] for h in old.history if h['action'] in ('verify', 'controller')]
        for literal in ('Inspect budget exhausted; create or verify an artifact',
                        'Finish held for independent acceptance review',
                        'Run an acceptance verification command before finish',
                        'Finish refused: required artifacts missing'):
            self.assertIn(literal, refusals)

    def test_react_lane(self):
        # The plain loop finishes at the first finish action: no gates.
        (old, _, old_root), (new, _, new_root) = pair(v6.HermesBaselineAgent, lanes.ReactLane)
        self.assertEqual([(k, normalize(p, old_root)) for k, p in old.prompts],
                         [(k, normalize(p, new_root)) for k, p in new.prompts])
        self.assertEqual([normalize(repr(h), old_root) for h in old.history],
                         [normalize(repr(h), new_root) for h in new.history])
        self.assertEqual(old.history[-1]['action'], 'finish')

    def test_knowledge_lane(self):
        self.assert_same(v7.MithrilKnowledgeAgent, lanes.KnowledgeLane, False)

    def test_jev_v7_lane(self):
        _, new = self.assert_same(v6_jev.MithrilJevInterleavedAgent, lanes.JevV7Lane, True)
        self.assertEqual(set(new.jev_instructions), {components.JEV_V7_INSTRUCTION})

    def test_knowledge_jev_lane(self):
        self.assert_same(v7.MithrilKnowledgeJevAgent, lanes.KnowledgeJevLane, True)

    def test_jev_v7_instruction_is_the_frozen_literal(self):
        source = (REPO / 'bench/terminal_bench_v6/jev_interleave.py').read_text()
        self.assertIn("'instructions': '" + components.JEV_V7_INSTRUCTION + "'", source)
        self.assertEqual(components.JEV_QUESTIONS, v6_jev.QUESTIONS)

    def test_assets_are_the_frozen_copies(self):
        v6_dir, v7_dir, assets = REPO / 'bench/terminal_bench_v6', REPO / 'bench/terminal_bench_v7', REPO / 'harness/assets'
        for name in ('mithril-bpmn-step.cljk', 'mithril-task-state.cljk', 'mithril-domain-prefill.cljk',
                     'ontology_probe.py', 'terminal-actions-v2.mith', 'terminal-agent-loop-v2.mith'):
            self.assertTrue(filecmp.cmp(v6_dir / name, assets / name, shallow=False), name)
        self.assertTrue(filecmp.cmp(v7_dir / 'knowledge_lookup.cljk', assets / 'knowledge_lookup.cljk', shallow=False))
        for name in ('general-reasoning-v1.mith', 'railway-query-v1.mith'):
            self.assertTrue(filecmp.cmp(v7_dir / 'knowledge' / name, assets / 'knowledge' / name, shallow=False), name)


if __name__ == '__main__':
    unittest.main()
