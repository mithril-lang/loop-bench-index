"""Harness components. Each one is a mixin over `HarnessLoop` hooks and is
named by the role it plays in the derived model (see harness/README.md):

- KnowledgeRetrieval  L0 prior knowledge: precompiled `.mith` rules (v7)
- JevPriority         System-1 policy over a fixed option set (v7 behaviour)
- DifferentialJudge   measured judge: harness-run row differential gates finish (v9a)
- AutoAcceptance      typed acceptance check run by the harness after every modify
- KnowledgePack       compiled .mith knowledge packs (domain rules, failure cases) in the static task text
- GraphToolkit        a task-agnostic graph helper placed in the container
- SchemaCard          a deterministic profile of the target environment's own ontology and data
- InvariantCheck      after each modify, necessary conditions derived from the data (failure case FC-03)
- RequirementGate     finish only when every extracted requirement has a passing agent-written test
- IndependentReview   at finish, acceptance tests written from the specification alone by a fresh model call
"""

import asyncio
import base64
import hashlib
import json
import os
import re
import shlex
import time
import urllib.request
from pathlib import Path

from .differential import (command_paths, compare, coverage_gaps,
                           independence_violations, validate_submission)
from .acceptance import acceptance_command, spec_digest, spec_prompt, validate_spec
from .loop import ASSETS, last_json_object

KNOWLEDGE_LOOKUP = ASSETS / 'knowledge_lookup.cljk'
KNOWLEDGE_GENERAL = ASSETS / 'knowledge' / 'general-reasoning-v1.mith'
KNOWLEDGE_TASK = ASSETS / 'knowledge' / 'railway-query-v1.mith'


class KnowledgeRetrieval:
    """Bounded keyword retrieval over compiled general + task `.mith` rules.
    The task graph is railway-specific: lanes using it are task-assisted."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.knowledge_receipt = None
        self.knowledge_guidance = None
        self.knowledge_rules = []

    async def compile_knowledge(self):
        receipt = await self.kbb_json([str(KNOWLEDGE_LOOKUP), str(KNOWLEDGE_GENERAL), str(KNOWLEDGE_TASK)],
                                      'Mith knowledge compile failed: ')
        if not receipt.get('owl-entailed-section') or \
                receipt.get('general-rule-count', 0) < 5 or receipt.get('task-rule-count', 0) < 4:
            raise RuntimeError('Mith knowledge retrieval failed: ' + str(receipt))
        self.knowledge_receipt = receipt
        self.knowledge_rules = receipt['matches']
        self.state.with_suffix('.knowledge.json').write_text(json.dumps(receipt, indent=2))

    def retrieve_knowledge(self, text, limit=4):
        words = {word.lower() for word in re.findall(r'[A-Za-z]{4,}', text)}
        ranked = []
        for entry in self.knowledge_rules:
            haystack = (entry['id'] + ' ' + entry['text']).lower()
            ranked.append((sum(word in haystack for word in words), entry))
        ranked.sort(key=lambda pair: (-pair[0], pair[1]['id']))
        selected = [entry for score, entry in ranked if score > 0][:limit]
        if not selected:
            selected = [entry for _, entry in ranked[:limit]]
        for marker in ('/bench/rule/', '/bench/railway/task/'):
            if not any(marker in entry['id'] for entry in selected):
                category = next((entry for _, entry in ranked if marker in entry['id']), None)
                if category:
                    selected = selected[:max(0, limit - 1)] + [category]
        return json.dumps([{'id': entry['id'], 'text': entry['text']} for entry in selected], ensure_ascii=False)

    async def prefill_task(self, instruction, probe):
        await self.compile_knowledge()
        self.knowledge_guidance = self.retrieve_knowledge(instruction, limit=5)
        return await super().prefill_task(instruction, probe)

    async def before_query(self, instruction):
        latest = self.history[-1] if self.history else {}
        observation = latest.get('result', {})
        focus = (observation.get('stderr') or '')[-800:] + ' ' + (observation.get('stdout') or '')[-800:]
        self.knowledge_guidance = self.retrieve_knowledge(focus or instruction)
        parent_hook = getattr(super(), 'before_query', None)
        if parent_hook:
            await parent_hook(instruction)


JEV_QUESTIONS = {
    'identity': 'Check how submissions identify the same physical operational point.',
    'recency': 'Check which submission wins when facts about a point conflict.',
    'coordinates': 'Check optional latitude and longitude formats and missing values.',
    'adjacency': 'Check direct line-section connections and distinct section counts.',
    'qualification': 'Check voltage units, authorized vehicles, and high-speed counts.',
    'independent_check': 'Compute expected rows independently from source RDF and compare both standalone SPARQL queries.',
}
# v7 instruction, kept verbatim for reproduction. Its last sentence biased all
# 39 v7 decisions to `independent_check`; JEV_NEUTRAL removes it.
JEV_V7_INSTRUCTION = ('Select the most useful next falsifiable domain hypothesis for the railway task. '
                      'A selection is a priority, never proof. Prefer an independent result check after files exist.')
JEV_NEUTRAL_INSTRUCTION = ('Select the most useful next falsifiable domain hypothesis for the railway task. '
                           'A selection is a priority, never proof.')


def jev_decide(state, api_key, instruction):
    model = os.environ.get('BENCH_JEV_MODEL')
    if not model:
        raise RuntimeError('BENCH_JEV_MODEL is required for the Jev lane')
    request = {'model': model, 'state': state,
               'questions': {'next_hypothesis': {'type': 'choice', 'instructions': instruction,
                                                 'criteria': JEV_QUESTIONS}}}
    http_request = urllib.request.Request(
        'https://openrouter.ai/api/alpha/decisions', data=json.dumps(request, ensure_ascii=False).encode(),
        headers={'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(http_request, timeout=35) as response:
        result = json.load(response)
    answer = result.get('answers', {}).get('next_hypothesis', {})
    choice = answer.get('choice'); probabilities = answer.get('probabilities')
    confidence = answer.get('confidence'); resolved_model = result.get('model', '')
    if (not (resolved_model == model or resolved_model.startswith(model + '-'))
            or choice not in JEV_QUESTIONS or not isinstance(probabilities, dict)
            or set(probabilities) != set(JEV_QUESTIONS)
            or not isinstance(confidence, (float, int)) or not 0 <= confidence <= 1):
        raise RuntimeError('Jev response failed model, candidate, or probability checks')
    usage = result.get('usage') or {}
    if not all(isinstance(usage.get(key), (int, float)) for key in ('input_tokens', 'output_tokens', 'cost')):
        raise RuntimeError('Jev usage receipt is incomplete')
    return {'choice': choice, 'confidence': confidence, 'probabilities': probabilities, 'usage': usage,
            'model': resolved_model, 'request_id': result.get('id')}


class JevPriority:
    """Jev picks one of a fixed set of investigation priorities before each
    Luna call; below `jev_threshold` the choice is recorded but not shown.
    Jev never authors a command. Calls, tokens and cost are metered."""
    jev_instruction = JEV_V7_INSTRUCTION
    jev_threshold = 0.6
    decide = staticmethod(jev_decide)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.jev_usage_files = []
        self.jev_decisions = []
        self.jev_guidance = None

    async def before_query(self, instruction):
        api_key = os.environ.get('OPENROUTER_API_KEY')
        if not api_key:
            raise RuntimeError('OPENROUTER_API_KEY is required for the Jev lane')
        latest = self.history[-1] if self.history else {}
        receipt = self.latest_state_receipt or {}
        state = json.dumps({
            'task_goals': (self.plan or {}).get('goals', []),
            'task_constraints': (self.plan or {}).get('constraints', []),
            'focus_classes': (self.plan or {}).get('focus_classes', []),
            'focus_properties': (self.plan or {}).get('focus_properties', []),
            'step': len(self.history), 'last_action': latest.get('action'),
            'last_exit_code': latest.get('result', {}).get('exit_code'),
            'last_observation': latest.get('result', {}).get('stdout', '')[-1200:],
            'last_error': latest.get('result', {}).get('stderr', '')[-600:],
            'confirmed_artifacts': sorted(self.created_artifacts),
            'domain_evidence': receipt.get('domain-entailed', {}),
        }, ensure_ascii=False, sort_keys=True)
        started = time.monotonic()
        result = await asyncio.to_thread(self.decide, state, api_key, self.jev_instruction)
        elapsed = time.monotonic() - started
        usage_path = self.usage_dir / f'jev-{len(self.jev_decisions):03}.json'
        usage_path.write_text(json.dumps({**result['usage'], 'estimated_cost_usd': result['usage']['cost']}))
        self.jev_usage_files.append(str(usage_path))
        self.jev_decisions.append({'step': len(self.history), 'choice': result['choice'],
                                   'confidence': result['confidence'], 'model': result['model'],
                                   'request_id': result['request_id'], 'wall_seconds': round(elapsed, 3)})
        self.jev_guidance = JEV_QUESTIONS[result['choice']] if result['confidence'] >= self.jev_threshold else None
        parent_hook = getattr(super(), 'before_query', None)
        if parent_hook:
            await parent_hook(instruction)


DIFFERENTIAL_GATE_TEXT = (
    '\n\nHARNESS FINISH GATE (applies to this run): finish is refused until the harness has run a '
    'differential for your answers. Submit it as action="verify" with command="differential" and a field '
    '"differential": {"pairs":[{"name":"...","answer_command":"...","answer_paradigm":"...",'
    '"derivation_command":"...","derivation_paradigm":"..."}],"uncovered":[{"path":"...","reason":"..."}]}. '
    'answer_command prints the rows your submitted artifact produces; derivation_command prints the rows '
    'you compute independently from the task source data with a different method. Both print one row per '
    'line, tab-separated fields, no header, absolute paths only. The derivation, and any file its command '
    'names, must not mention the required artifacts or the files the answer command reads. Every required '
    'file must be used by an answer command or listed in uncovered with a reason. The harness compares the '
    'rows as multisets and reports missing and extra rows; a passing differential goes stale if any '
    'required file changes. Agreement is evidence, not proof: build the derivation from the task text, '
    'not from your answer.')
OUTPUT_LIMIT = 2_000_000
REFERENCED_FILE_LIMIT = 262_144


class DifferentialJudge:
    """Finish is admissible only after the harness ran every submitted
    answer/derivation pair, all compared equal (exit 0), and the required
    artifacts are unchanged since. The harness supplies no expected rows."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.differential_receipts = []
        self.passing_digest = None
        self.gate_refusals = []

    def task_text(self, instruction):
        return super().task_text(instruction) + DIFFERENTIAL_GATE_TEXT

    async def execute_action(self, environment, action):
        if action['action'] != 'verify' or 'differential' not in action:
            return await super().execute_action(environment, action)
        receipt = await self.run_differential(environment, action['differential'])
        self.differential_receipts.append(receipt)
        action['command'] = 'differential'
        return {'exit_code': 0 if receipt['exit'] == 0 else 1,
                'stdout': json.dumps(receipt, ensure_ascii=False)[-12000:], 'stderr': ''}

    async def finish_refusal(self, environment, instruction):
        reason = None
        if self.passing_digest is None:
            reason = 'no-passing-differential'
        elif await self.artifact_digest(environment, self.required_artifacts(instruction)) != self.passing_digest:
            self.passing_digest = None
            reason = 'differential-stale-after-artifact-change'
        if reason:
            self.gate_refusals.append(reason)
            return 'Finish refused by differential gate: ' + reason
        return await super().finish_refusal(environment, instruction)

    def extra_metadata(self):
        exits = [r['exit'] for r in self.differential_receipts]
        data = dict(super().extra_metadata())
        data.update({'differential_gate': True,
                     'differential_submissions': len(self.differential_receipts),
                     'differential_exit_counts': {str(k): exits.count(k) for k in (0, 1, 2)},
                     'differential_gate_refusals': len(self.gate_refusals),
                     'differential_refusal_reasons': sorted(set(self.gate_refusals)),
                     'differential_passing_at_end': self.passing_digest is not None})
        return data

    async def run(self, instruction, environment, context):
        self.instruction_text = instruction
        try:
            await super().run(instruction, environment, context)
        finally:
            self.state.with_suffix('.differential.json').write_text(json.dumps(
                {'receipts': self.differential_receipts, 'gate_refusals': self.gate_refusals}, indent=2))

    async def exec_full(self, environment, command, timeout=180):
        try:
            result = await environment.exec(command=command, timeout_sec=timeout)
        except RuntimeError as exc:
            if 'timed out' not in str(exc).lower():
                raise
            return {'exit_code': 124, 'stdout': '', 'stderr': 'timed out'}
        return {'exit_code': result.return_code, 'stdout': (result.stdout or '')[:OUTPUT_LIMIT],
                'stderr': (result.stderr or '')[-2000:]}

    async def artifact_digest(self, environment, required):
        if not required:
            return 'no-required-artifacts'
        listing = ' '.join(shlex.quote(p) for p in sorted(required))
        result = await self.exec_full(environment, f'sha256sum {listing} 2>&1', timeout=60)
        return hashlib.sha256(result['stdout'].encode()).hexdigest()

    async def referenced_contents(self, environment, command):
        contents = {}
        for path in command_paths(command)[:12]:
            quoted = shlex.quote(path)
            result = await self.exec_full(
                environment, f'test -f {quoted} && head -c {REFERENCED_FILE_LIMIT} {quoted}', timeout=30)
            if result['exit_code'] == 0:
                contents[path] = result['stdout']
        return contents

    async def run_differential(self, environment, spec):
        required = self.required_artifacts(self.instruction_text)
        pairs, uncovered, invalid = validate_submission(spec)
        if invalid:
            return {'exit': 2, 'reason': invalid, 'pairs': [], 'step': len(self.history)}
        gaps = coverage_gaps(pairs, uncovered, required)
        results, overall = [], 0
        for pair in pairs:
            violations = independence_violations(
                pair, required, await self.referenced_contents(environment, pair['derivation_command']))
            if violations:
                row = {'name': pair['name'], 'exit': 2, 'reason': 'independence-refused', 'violations': violations}
            else:
                answer = await self.exec_full(environment, pair['answer_command'])
                derivation = await self.exec_full(environment, pair['derivation_command'])
                row = dict(compare(answer, derivation), name=pair['name'],
                           answer_stderr=answer['stderr'][-600:], derivation_stderr=derivation['stderr'][-600:])
            row.update({'answer_paradigm': str(pair.get('answer_paradigm', ''))[:200],
                        'derivation_paradigm': str(pair.get('derivation_paradigm', ''))[:200]})
            results.append(row)
            overall = max(overall, row['exit'])
        if gaps:
            overall = 2
        reason = ('pairs-match' if overall == 0 else
                  'coverage-gap' if gaps and all(r['exit'] < 2 for r in results) else 'see-pairs')
        self.passing_digest = await self.artifact_digest(environment, required) if overall == 0 else None
        return {'exit': overall, 'reason': reason, 'coverage_gaps': gaps, 'pairs': results,
                'step': len(self.history), 'artifact_digest': self.passing_digest}


ACCEPTANCE_TEXT = (
    '\n\nHARNESS ACCEPTANCE CHECK (applies to this run): after every modify action the harness itself runs the '
    'entrypoint on the target bundle and on a copy of each other bundle, checks that every source triple is '
    'preserved and that added triples use only existing vocabulary, runs each query file on the output graph '
    'and checks its column names. The report is appended to that modify action\'s observation. These checks '
    'are not the task verifier and say nothing about whether the rows are correct.')
ACCEPTANCE_REPORT_LIMIT = 6000


class AutoAcceptance:
    """One metered typed prefill extracts the acceptance spec; it is admitted only
    if every value appears verbatim in the instruction (fail closed otherwise).
    After each modify, the harness-generated acceptance command runs and its
    report is appended to the modify observation. No model chooses it."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.acceptance_spec = None
        self.acceptance_runs = []

    def task_text(self, instruction):
        return super().task_text(instruction) + ACCEPTANCE_TEXT

    async def prefill_task(self, instruction, probe):
        plan = await super().prefill_task(instruction, probe)
        raw = await self.hermes_call(spec_prompt(instruction),
                                     self.usage_dir / f'call-{len(self.calls):03}-acceptance.json', 'acceptance-prefill')
        spec = last_json_object(raw, lambda c: 'entrypoint' in c)
        normalized, reasons = validate_spec(spec, instruction, self.required_artifacts(instruction))
        self.state.with_suffix('.acceptance-spec.json').write_text(
            json.dumps({'proposed': spec, 'admitted': normalized, 'refusals': reasons}, indent=2))
        if reasons:
            raise RuntimeError('REFUSE acceptance spec: ' + ', '.join(reasons))
        self.acceptance_spec = normalized
        return plan

    async def execute_action(self, environment, action):
        result = await super().execute_action(environment, action)
        if action['action'] != 'modify' or not self.acceptance_spec:
            return result
        started = time.monotonic()
        try:
            check = await environment.exec(command=acceptance_command(self.acceptance_spec), timeout_sec=300)
            self.acceptance_wall_seconds = getattr(self, 'acceptance_wall_seconds', 0.0) + time.monotonic() - started
            exit_code, out, err = check.return_code, check.stdout or '', check.stderr or ''
        except RuntimeError as exc:
            if 'timed out' not in str(exc).lower():
                raise
            exit_code, out, err = 124, '', 'acceptance check exceeded 300 seconds'
        elapsed = round(time.monotonic() - started, 3)
        self.acceptance_runs.append({'step': len(self.history), 'exit': exit_code, 'seconds': elapsed})
        report = (out + ('\n' + err[-1500:] if err else ''))[-ACCEPTANCE_REPORT_LIMIT:]
        result = dict(result)
        result['stdout'] = (result.get('stdout') or '') + \
            f'\n[HARNESS ACCEPTANCE CHECK after modify: exit {exit_code}]\n' + report
        return result

    def extra_metadata(self):
        data = dict(super().extra_metadata())
        exits = [r['exit'] for r in self.acceptance_runs]
        data.update({'auto_acceptance': True,
                     'acceptance_spec_digest': spec_digest(self.acceptance_spec) if self.acceptance_spec else None,
                     'acceptance_runs': len(self.acceptance_runs),
                     'acceptance_pass': exits.count(0),
                     'acceptance_seconds': round(sum(r['seconds'] for r in self.acceptance_runs), 3)})
        return data


KNOWLEDGE_PACK_HELPER = ASSETS / 'knowledge_pack.cljk'


class KnowledgePack:
    """Compiles `knowledge_packs` (files under assets/knowledge) with Mithril once
    per trial and puts every entry into the static task text. With the chat
    transport that text sits in the cached prefix, so more knowledge costs
    little per step. Entries are general to a task family: rules, checks and
    failure cases, never answers."""
    knowledge_packs = ()

    async def run(self, instruction, environment, context):
        receipt = await self.kbb_json([str(KNOWLEDGE_PACK_HELPER)] + [str(ASSETS / 'knowledge' / p) for p in self.knowledge_packs],
                                      'Knowledge pack compile failed: ')
        if not receipt.get('entries'):
            raise RuntimeError('REFUSE: knowledge packs compiled to no entries')
        self.knowledge_pack_receipt = {'packs': receipt['packs'], 'axioms': receipt['axioms'],
                                       'closure': receipt['closure'], 'entries': len(receipt['entries'])}
        lines = []
        for entry in receipt['entries']:
            kind = entry['kind'].rsplit('/', 1)[-1]
            lines.append(f'- [{kind}] {entry["text"]}')
        self.knowledge_pack_text = '\n'.join(lines)
        return await super().run(instruction, environment, context)

    def task_text(self, instruction):
        text = super().task_text(instruction)
        if getattr(self, 'knowledge_pack_text', None):
            text += ('\n\nKNOWLEDGE (compiled from Mithril ontology packs: domain rules, checks and failure cases '
                     'seen in earlier runs; apply them where the task text agrees):\n' + self.knowledge_pack_text)
        return text

    def extra_metadata(self):
        data = dict(super().extra_metadata())
        data['knowledge_pack'] = getattr(self, 'knowledge_pack_receipt', None)
        return data


GRAPHKIT = Path(__file__).resolve().parents[1] / 'attack' / 'container' / 'graphkit.py'
GRAPHKIT_TEXT = ('\n\nGRAPH TOOLKIT: `/opt/harness/graphkit.py` is available (use it from solve.py with '
                 '`import sys; sys.path.insert(0, "/opt/harness"); import graphkit as gk`). It offers load_turtle(paths), '
                 'files(dir, pattern), instances(g, class_iri) including subclasses, pairs(g, property_iri), '
                 'literal(g, node, property_iri), bfs(adjacency, start) returning hop counts, and within(dist, k). '
                 'It applies no task rules: name normalization, policies and edge choice are yours.')


class GraphToolkit:
    container_files = {'/opt/harness/graphkit.py': GRAPHKIT}

    def task_text(self, instruction):
        return super().task_text(instruction) + GRAPHKIT_TEXT


SCHEMA_PROBE = Path(__file__).resolve().parents[1] / 'attack' / 'container' / 'schema_probe.py'
TARGET_DIR = re.compile(r"`(/app/[\w.-]+)/`")


class SchemaCard:
    """Profiles the target environment inside the container before the first
    model call and puts the card in the static task text. It describes the
    data (sources, classes, rule comments, where names resolve, parameters)
    and computes no answer."""
    container_files = {'/opt/harness/schema_probe.py': SCHEMA_PROBE}

    async def run(self, instruction, environment, context):
        match = TARGET_DIR.search(instruction)
        if not match:
            raise RuntimeError('REFUSE: no target directory in the instruction for the schema card')
        result = await environment.exec(command=f'python3 /opt/harness/schema_probe.py card {shlex.quote(match.group(1))}',
                                        timeout_sec=120)
        if result.return_code != 0:
            raise RuntimeError('REFUSE: schema card failed: ' + (result.stderr or '')[-600:])
        card = json.loads(result.stdout)
        self.schema_card_text = json.dumps(card, sort_keys=True)
        self.schema_card_receipt = {'target': match.group(1), 'chars': len(self.schema_card_text),
                                    'identity_classes': sorted(card.get('identity', {})),
                                    'comments': len(card.get('comments', {})), 'parameters': len(card.get('parameters', []))}
        return await super().run(instruction, environment, context)

    def task_text(self, instruction):
        text = super().task_text(instruction)
        if getattr(self, 'schema_card_text', None):
            text += ('\n\nSCHEMA CARD (computed by the harness from the target environment; describes the data, '
                     'not the answer):\n' + self.schema_card_text)
        return text

    def extra_metadata(self):
        data = dict(super().extra_metadata())
        data['schema_card'] = getattr(self, 'schema_card_receipt', None)
        return data


INVARIANT_TEXT = ('\n\nHARNESS INVARIANT CHECK (applies to this run): after every modify action the harness runs '
                  '/app/solve.py on the target environment and checks necessary conditions derived from the data: '
                  'output host names are names from the authoritative host source, every entry host is listed, and '
                  'an entry host that runs as a role reaches at least one role. Passing does not mean the answer is right.')


class InvariantCheck:
    """reachmini-specific: after each modify, run the solver and schema_probe
    check-reach, and append the report to the observation."""
    container_files = {'/opt/harness/schema_probe.py': SCHEMA_PROBE}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.invariant_runs = []

    def task_text(self, instruction):
        return super().task_text(instruction) + INVARIANT_TEXT

    async def run(self, instruction, environment, context):
        match = TARGET_DIR.search(instruction)
        self.invariant_target = match.group(1) if match else None
        return await super().run(instruction, environment, context)

    async def execute_action(self, environment, action):
        result = await super().execute_action(environment, action)
        if action['action'] != 'modify' or not self.invariant_target:
            return result
        target = shlex.quote(self.invariant_target)
        command = (f'rm -rf /tmp/invariant-out && timeout 120 python3 /app/solve.py {target} /tmp/invariant-out '
                   f'&& python3 /opt/harness/schema_probe.py check-reach {target} /tmp/invariant-out')
        started = time.monotonic()
        try:
            check = await environment.exec(command=command, timeout_sec=200)
            code, out = check.return_code, (check.stdout or '') + (check.stderr or '')[-800:]
        except RuntimeError as exc:
            if 'timed out' not in str(exc).lower():
                raise
            code, out = 124, 'invariant check timed out'
        self.acceptance_wall_seconds = getattr(self, 'acceptance_wall_seconds', 0.0) + time.monotonic() - started
        self.invariant_runs.append({'step': len(self.history), 'exit': code})
        result = dict(result)
        result['stdout'] = (result.get('stdout') or '') + f'\n[HARNESS INVARIANT CHECK after modify: exit {code}]\n' + out[-3000:]
        return result

    def extra_metadata(self):
        data = dict(super().extra_metadata())
        exits = [r['exit'] for r in self.invariant_runs]
        data.update({'invariant_runs': len(exits), 'invariant_pass': exits.count(0)})
        return data


from .requirements import CHECK_SCRIPT as REQUIREMENT_CHECK, extract_all as extract_requirements, referenced_docs


class RequirementGate:
    """Task-agnostic. The harness extracts requirement sentences from the
    instruction (deterministic), asks the agent to cover each with a test in
    /tmp/harness_tests tagged `covers: Rk`, and holds finish until every
    requirement has a passing test or a written waiver. After
    `max_gate_refusals` refusals finish is admitted and the override is
    recorded, so the gate cannot hold a run until the step cap."""
    max_gate_refusals = 4

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.requirements = []
        self.gate_reports = []
        self.gate_refusal_count = 0
        self.gate_overridden = False

    async def run(self, instruction, environment, context):
        docs = {}
        for path in referenced_docs(instruction)[:6]:
            result = await environment.exec(command=f'head -c 20000 {shlex.quote(path)} 2>/dev/null', timeout_sec=30)
            if result.return_code == 0 and (result.stdout or '').strip():
                docs[path] = result.stdout
        self.requirement_sources = sorted(docs)
        self.requirements = await self.model_requirements(instruction, docs)
        self.requirement_origin = 'model'
        if not self.requirements:
            self.requirements = extract_requirements(instruction, docs)
            self.requirement_origin = 'deterministic-fallback'
        return await super().run(instruction, environment, context)

    async def model_requirements(self, instruction, docs):
        """One metered call: testable behavioural requirements from the task and the documents it names."""
        prompt = ('List the testable requirements a correct solution must satisfy. Use only the task text and the '
                  'documents below. Each requirement is one short, concrete, checkable statement of behaviour or output '
                  '(inputs, outputs, edge cases, invariants, files that must or must not change). Return exactly one JSON '
                  'object: {"requirements": ["...", "..."]} with at most 20 items, most important first. Do not solve the task.\n'
                  'TASK:\n' + instruction + ''.join(f'\n\nDOCUMENT {path}:\n{text}' for path, text in docs.items()))
        try:
            raw = await self.hermes_call(prompt, self.usage_dir / f'call-{len(self.calls):03}-requirements.json', 'requirements')
        except RuntimeError:
            return []
        found = last_json_object(raw, lambda c: isinstance(c.get('requirements'), list))
        if not found:
            return []
        return [('model', str(r)[:300]) for r in found['requirements'] if isinstance(r, str) and r.strip()][:20]

    def task_text(self, instruction):
        text = super().task_text(instruction)
        if not self.requirements:
            return text
        listing = '\n'.join(f'R{i + 1}: {r}' for i, (src, r) in enumerate(self.requirements))
        return text + ('\n\nREQUIREMENTS GATE (applies to this run). The harness extracted these requirement sentences '
                       'from the task:\n' + listing + '\nBefore finishing, write pytest tests in /tmp/harness_tests/test_*.py '
                       'that exercise your deliverable the way the task describes (run it, check its outputs or files; do not '
                       'just restate constants). Put a comment `# covers: R1, R4` on the line above each test function. The '
                       'harness runs `python3 -m pytest /tmp/harness_tests` and admits finish only when every requirement is '
                       'covered by at least one passing test, or is listed in /tmp/harness_tests/WAIVED.txt as `Rk: reason` '
                       'because it cannot be tested. Keep these tests outside the deliverable directories.')

    async def finish_refusal(self, environment, instruction):
        if not self.requirements or self.gate_overridden:
            return await super().finish_refusal(environment, instruction)
        ids = ','.join(f'R{i + 1}' for i in range(len(self.requirements)))
        command = f"mkdir -p /tmp/harness_tests && python3 - {shlex.quote(ids)} <<'PY'\n{REQUIREMENT_CHECK}\nPY"
        try:
            result = await environment.exec(command=command, timeout_sec=150)
            report = json.loads((result.stdout or '').strip().splitlines()[-1])
        except (RuntimeError, ValueError, IndexError) as exc:
            report = {'error': str(exc)[-300:], 'missing': ['unmeasured']}
        self.gate_reports.append({k: report.get(k) for k in ('tests', 'passing', 'covered', 'waived', 'missing', 'error')})
        if not report.get('missing'):
            return await super().finish_refusal(environment, instruction)
        self.gate_refusal_count += 1
        if self.gate_refusal_count > self.max_gate_refusals:
            self.gate_overridden = True
            return await super().finish_refusal(environment, instruction)
        return ('Finish refused by the requirements gate: requirements without a passing test: '
                + ', '.join(report['missing']) + f". Tests found: {report.get('tests')}, passing: {report.get('passing')}. "
                + 'pytest output tail:\n' + (report.get('pytest_tail') or report.get('error') or '')[-1200:])

    def extra_metadata(self):
        data = dict(super().extra_metadata())
        data.update({'requirements': len(self.requirements), 'requirement_sources': getattr(self, 'requirement_sources', []),
                     'requirement_origin': getattr(self, 'requirement_origin', None),
                     'gate_refusals': self.gate_refusal_count,
                     'gate_overridden': self.gate_overridden, 'gate_reports': self.gate_reports[-3:]})
        return data


from . import review as acceptance_review


class IndependentReview:
    """At the first finish attempt, a fresh single-turn model call writes
    acceptance tests from the specification alone (no code, no transcript).
    The harness runs them against the deliverable and holds finish while
    undisputed tests fail, for at most `max_review_rounds` rounds."""
    max_review_rounds = 2

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.review_rounds = 0
        self.review_reports = []
        self.review_ready = False

    async def run(self, instruction, environment, context):
        self.review_instruction = instruction
        return await super().run(instruction, environment, context)

    async def prepare_review(self, environment):
        docs = {}
        for path in referenced_docs(self.review_instruction)[:6]:
            r = await environment.exec(command=f'head -c 20000 {shlex.quote(path)} 2>/dev/null', timeout_sec=30)
            if r.return_code == 0 and (r.stdout or '').strip():
                docs[path] = r.stdout
        listing = await environment.exec(command="find /app -maxdepth 3 -not -path '*/.*' 2>/dev/null | head -150",
                                         timeout_sec=30)
        prompt = (acceptance_review.PROMPT + 'TASK:\n' + self.review_instruction
                  + ''.join(f'\n\nDOCUMENT {p}:\n{t}' for p, t in docs.items())
                  + '\n\nFILE NAMES UNDER /app:\n' + (listing.stdout or ''))
        reply = await self.hermes_call(prompt, self.usage_dir / f'call-{len(self.calls):03}-review.json', 'review')
        code = acceptance_review.extract_code(reply)
        if not code:
            return False
        encoded = base64.b64encode(code.encode()).decode()
        d = acceptance_review.TEST_DIR
        r = await environment.exec(command=f'mkdir -p {d} && echo {encoded} | base64 -d > {d}/test_review.py', timeout_sec=30)
        return r.return_code == 0

    async def finish_refusal(self, environment, instruction):
        if self.review_rounds >= self.max_review_rounds:
            return await super().finish_refusal(environment, instruction)
        if not self.review_ready:
            self.review_ready = await self.prepare_review(environment)
            if not self.review_ready:
                self.review_rounds = self.max_review_rounds  # no usable review: do not block
                self.review_reports.append({'error': 'no test file from reviewer'})
                return await super().finish_refusal(environment, instruction)
        command = f"python3 - {acceptance_review.TEST_DIR} <<'PY'\n{acceptance_review.RUN_SCRIPT}\nPY"
        try:
            r = await environment.exec(command=command, timeout_sec=150)
            report = json.loads((r.stdout or '').strip().splitlines()[-1])
        except (RuntimeError, ValueError, IndexError) as exc:
            report = {'error': str(exc)[-300:], 'open': []}
        self.review_reports.append({k: report.get(k) for k in ('passed', 'failed', 'disputed', 'open', 'collected', 'error')})
        if not report.get('open'):
            return await super().finish_refusal(environment, instruction)
        self.review_rounds += 1
        return ('Finish held by an independent acceptance review: tests written from the specification alone (without '
                'your code) fail: ' + ', '.join(report['open']) + '. Fix the deliverable, or if a test contradicts the '
                'specification, add `test_name: reason` to /tmp/review_tests/DISPUTED.txt. The tests are in '
                '/tmp/review_tests/test_review.py. pytest output tail:\n' + (report.get('tail') or '')[-1800:])

    def extra_metadata(self):
        data = dict(super().extra_metadata())
        data.update({'review_rounds': self.review_rounds, 'review_reports': self.review_reports[-3:]})
        return data
