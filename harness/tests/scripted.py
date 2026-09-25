"""Scripted doubles for offline harness tests: a local-bash environment, a
model that replays fixed replies, and fixed Mithril/Jev receipts. The same
mixin is put first in the MRO of a frozen legacy agent and of a harness lane,
so both see identical inputs."""

import json
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
RUN_ROOT = Path(tempfile.mkdtemp(prefix='harness-test-'))
os.environ['BENCH_RUN_ROOT'] = str(RUN_ROOT)
os.environ['BENCH_MAX_STEPS'] = '40'
os.environ.setdefault('BENCH_CRITICAL_REVIEW', '1')
os.environ['OPENROUTER_API_KEY'] = 'test-key-not-used'
os.environ['BENCH_JEV_MODEL'] = 'typesafe/jev-test'
for path in (REPO / 'harness', REPO / 'bench' / 'terminal_bench_v6', REPO / 'bench' / 'terminal_bench_v7'):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

PROBE = {'classes': ['era:OperationalPoint', 'era:SectionOfLine'], 'properties': ['era:opName'],
         'prefixes': {'era': 'http://data.europa.eu/949/'}, 'ontology_files': ['ontology_era.owl']}
PLAN = {'goals': ['produce both query files'], 'constraints': ['keep source triples'],
        'hypotheses': ['points share identity by name'], 'focus_classes': ['era:OperationalPoint', 'era:Unknown'],
        'focus_properties': ['era:opName']}
DOMAIN_RECEIPT = {'ontology-digest': 'sha256:domain', 'source-class-count': 2,
                  'entailed-descendants': {'era:SectionOfLine': ['era:QualifyingSection']}}
STATE_RECEIPT = {'state-graph-digest': 'sha256:state', 'domain-entailed': {'era:OperationalPoint': True}}
KNOWLEDGE_RECEIPT = {'general-digest': 'sha256:g', 'task-digest': 'sha256:t', 'general-rule-count': 5,
                     'task-rule-count': 5, 'owl-entailed-section': True,
                     'matches': [{'id': 'https://mithril.fund/id/bench/rule/identity', 'text': 'Group records by identity evidence'},
                                 {'id': 'https://mithril.fund/id/bench/rule/differential', 'text': 'Calculate expected rows independently'},
                                 {'id': 'https://mithril.fund/id/bench/railway/task/q1', 'text': 'Operational points crossing borders'}]}


class FakeEnv:
    async def exec(self, command, timeout_sec):
        p = subprocess.run(['bash', '-c', command], capture_output=True, text=True, timeout=timeout_sec)
        return types.SimpleNamespace(return_code=p.returncode, stdout=p.stdout, stderr=p.stderr)


def make_task(root):
    root.mkdir(parents=True, exist_ok=True)
    a, b = root / 'q1.rq', root / 'q2.rq'
    instruction = (f'Answer questions over /app/2024-q2 railway data.\n'
                   f'Create the following files:\n- `{a}`\n- `{b}`\n\nUse the ontology.')
    return instruction, a, b


def scripted_replies(a, b):
    act = lambda action, command, **extra: json.dumps(dict({'action': action, 'command': command, 'reason': 'r'}, **extra))
    replies = [act('inspect', 'ls /', hypothesis='names identify points', prediction='a list')]
    replies += [act('inspect', f'echo inspect-{k}') for k in range(6)]
    replies += [act('inspect', 'echo over-budget'),
                act('modify', f'printf "a\\t1\\n" > {a}'),
                '{"action":"verify","command":"false",}  trailing',
                'not json at all',
                act('verify', 'false'),
                act('finish', 'true'), act('finish', 'true'),
                act('verify', 'true'),
                act('finish', 'true'),
                act('modify', f'printf "b\\t2\\n" > {b}'),
                act('finish', 'true')]
    return replies


class Scripted:
    """Put first in the MRO. Replies to model calls from `self.replies`."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.prompts = []
        self.jev_states = []
        self.jev_instructions = []
        self.jev_count = 0

    async def hermes_call(self, prompt, usage, kind):
        self.prompts.append((kind, prompt))
        self.calls.append({'usage_file': str(usage), 'exit_code': 0, 'kind': kind})
        if kind == 'prefill':
            return 'plan: ' + json.dumps(PLAN)
        return self.replies.pop(0)

    async def mith(self, op, action='', outcome='true'):
        if op == 'enabled':
            return {'actions': [f'https://mithril.fund/id/action/terminal/{k}'
                                for k in ('finish', 'inspect', 'modify', 'verify')], 'completed': False}
        return {'semantic': {'entailed': True}}

    async def encode_task_state(self, instruction, phase):
        self.task_state_receipts.append(dict(STATE_RECEIPT, phase=phase))
        self.latest_state_receipt = STATE_RECEIPT
        return STATE_RECEIPT

    async def ontology_probe(self, instruction, environment):
        self.probe_data = PROBE
        return PROBE

    async def compile_domain_ontology(self):
        self.domain_receipt = DOMAIN_RECEIPT
        return DOMAIN_RECEIPT

    async def compile_knowledge(self):
        self.knowledge_receipt = KNOWLEDGE_RECEIPT
        self.knowledge_rules = KNOWLEDGE_RECEIPT['matches']

    def fake_jev(self, state, api_key, instruction=None):
        self.jev_states.append(state)
        self.jev_instructions.append(instruction)
        self.jev_count += 1
        choice = ['identity', 'independent_check', 'recency'][self.jev_count % 3]
        return {'choice': choice, 'confidence': [0.9, 0.4, 0.7][self.jev_count % 3],
                'probabilities': {}, 'usage': {'input_tokens': 10, 'output_tokens': 2, 'cost': 0.0},
                'model': 'typesafe/jev-test-1', 'request_id': f'r{self.jev_count}'}


def run_agent(cls, root, replies=None, prepare=None):
    import asyncio
    instruction, a, b = make_task(root)
    agent = cls(logs_dir=root / 'logs')
    agent.replies = replies if replies is not None else scripted_replies(a, b)
    if prepare:
        prepare(agent)
    context = types.SimpleNamespace(metadata=None)
    asyncio.run(agent.run(instruction, FakeEnv(), context))
    return agent, context
