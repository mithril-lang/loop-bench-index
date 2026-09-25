"""Harness components. Each one is a mixin over `HarnessLoop` hooks and is
named by the role it plays in the derived model (see harness/README.md):

- KnowledgeRetrieval  L0 prior knowledge: precompiled `.mith` rules (v7)
- JevPriority         System-1 policy over a fixed option set (v7 behaviour)
- DifferentialJudge   measured judge: harness-run row differential gates finish (v9a)
- AutoAcceptance      typed acceptance check run by the harness after every modify
"""

import asyncio
import hashlib
import json
import os
import re
import shlex
import time
import urllib.request

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
