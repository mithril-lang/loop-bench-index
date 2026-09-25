"""Lane registry: each lane is one composition of harness components.

`LANES` maps a lane id to its Harbor import path, the components it adds, and
the frozen source it reproduces (checked by tests/test_equivalence.py).
`PLANNED` lists derived-model lanes that are declared but not implemented;
they stay out of the runner until their prerequisites are measured.
"""

from .components import AutoAcceptance, DifferentialJudge, JevPriority, JEV_NEUTRAL_INSTRUCTION, KnowledgeRetrieval
from .loop import HarnessLoop


class ReactLane(HarnessLoop):
    lane_id = 'react'
    lane = 'baseline'
    semantic = False
    @staticmethod
    def name(): return 'hermes-gpt6-luna-terminal-loop'


class MithrilLane(HarnessLoop):
    lane_id = 'mithril'
    lane = 'mithril'
    semantic = True
    @staticmethod
    def name(): return 'mithril-domain-prefill-gpt6-luna-terminal-loop'


class KnowledgeLane(KnowledgeRetrieval, MithrilLane):
    lane_id = 'knowledge'
    @staticmethod
    def name(): return 'mithril-precompiled-knowledge-gpt6-luna-terminal-loop'


class JevV7Lane(JevPriority, MithrilLane):
    lane_id = 'jev-v7'
    @staticmethod
    def name(): return 'mithril-jev-interleaved-gpt6-luna-terminal-loop'


class JevNeutralLane(JevPriority, MithrilLane):
    lane_id = 'jev-neutral'
    jev_instruction = JEV_NEUTRAL_INSTRUCTION
    @staticmethod
    def name(): return 'mithril-jev-neutral-gpt6-luna-terminal-loop'


class KnowledgeJevLane(KnowledgeRetrieval, JevPriority, MithrilLane):
    lane_id = 'knowledge-jev'
    @staticmethod
    def name(): return 'mithril-precompiled-knowledge-jev-gpt6-luna-terminal-loop'


class JudgeLane(DifferentialJudge, MithrilLane):
    lane_id = 'judge'
    @staticmethod
    def name(): return 'mithril-differential-gate-gpt6-luna-terminal-loop'


class AutoAcceptanceLane(AutoAcceptance, MithrilLane):
    lane_id = 'auto-acceptance'
    @staticmethod
    def name(): return 'mithril-auto-acceptance-gpt6-luna-terminal-loop'


LANES = {
    'react':          {'import': 'mithril_harness.lanes:ReactLane', 'adds': [],
                       'reproduces': 'bench/terminal_bench_v6/agent.py:HermesBaselineAgent'},
    'mithril':        {'import': 'mithril_harness.lanes:MithrilLane', 'adds': ['semantic-layer'],
                       'reproduces': 'bench/terminal_bench_v6/agent.py:MithrilDomainPrefillAgent'},
    'knowledge':      {'import': 'mithril_harness.lanes:KnowledgeLane', 'adds': ['semantic-layer', 'knowledge'],
                       'reproduces': 'bench/terminal_bench_v7/knowledge_agent.py:MithrilKnowledgeAgent',
                       'task_assisted': True},
    'jev-v7':         {'import': 'mithril_harness.lanes:JevV7Lane', 'adds': ['semantic-layer', 'jev-priority'],
                       'reproduces': 'bench/terminal_bench_v6/jev_interleave.py:MithrilJevInterleavedAgent'},
    'jev-neutral':    {'import': 'mithril_harness.lanes:JevNeutralLane', 'adds': ['semantic-layer', 'jev-priority'],
                       'reproduces': None},
    'knowledge-jev':  {'import': 'mithril_harness.lanes:KnowledgeJevLane',
                       'adds': ['semantic-layer', 'knowledge', 'jev-priority'],
                       'reproduces': 'bench/terminal_bench_v7/knowledge_agent.py:MithrilKnowledgeJevAgent',
                       'task_assisted': True},
    'judge':          {'import': 'mithril_harness.lanes:JudgeLane', 'adds': ['semantic-layer', 'differential-judge'],
                       'reproduces': None},
    'auto-acceptance': {'import': 'mithril_harness.lanes:AutoAcceptanceLane',
                        'adds': ['semantic-layer', 'typed-acceptance-prefill', 'acceptance-after-modify'],
                        'reproduces': None},
}

# Derived-model lanes (harness/README.md). Each names what must be measured
# before it may be implemented and admitted to the runner.
PLANNED = {
    'typed-actions': {'adds': ['typed-action-ir'],
                      'requires': 'a policy that chooses pure operations; coverage measured (20.6-58.3% pure)'},
    'belief-context': {'adds': ['belief-graph-context'],
                       'requires': 'judge lane result; context built from L1-L3 graph instead of transcript'},
    'jev-policy': {'adds': ['typed-action-ir', 'jev-policy'],
                   'requires': 'typed-actions coverage and Jev calibration on logged decisions'},
    'population': {'adds': ['differential-judge', 'or-node-population', 'elo'],
                   'requires': 'judge-verifier agreement measured on the judge lane'},
    'budget-controller': {'adds': ['stop-controller'],
                          'requires': 'at least one solved matched pair (success-qualified cost)'},
}
