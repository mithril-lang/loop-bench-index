"""Mithril harness loop: the executor every lane shares.

Behaviour of the `react` and `mithril` lanes is byte-identical to
`bench/terminal_bench_v6/agent.py` (prompts and action history), which
`harness/tests/test_equivalence.py` checks against the frozen v6 source.
Components extend the loop only through these hooks:

- `task_text(instruction)`          text placed in the TASK section
- `before_query(instruction)`       per-step policy/retrieval (Jev, knowledge)
- `execute_action(env, action)`     run a non-finish action (default: bash)
- `finish_refusal(env, instruction)` reason string that holds a finish, or None
- `extra_metadata()`                fields merged into Harbor metadata
"""

import asyncio
import hashlib
import json
import os
import re
import shlex
import time
import uuid
from pathlib import Path

from harbor.agents.base import BaseAgent

ASSETS = Path(__file__).resolve().parents[1] / 'assets'
HERMES = os.environ.get('HERMES_BIN', '/Users/junkawasaki/.hermes/hermes-agent/venv/bin/hermes')
KBB = os.environ.get('KBB_BIN', '/opt/homebrew/bin/kbb')
MITHRIL = os.environ.get('MITHRIL_RUNTIME', '/Users/junkawasaki/.hermes/runtime/mithril')
CLASSPATH = os.environ.get('MITHRIL_CLASSPATH', '')
HELPER = ASSETS / 'mithril-bpmn-step.cljk'
PROFILE = ASSETS / 'terminal-agent-loop-v2.mith'
ONTOLOGY = ASSETS / 'terminal-actions-v2.mith'
TASK_HELPER = ASSETS / 'mithril-task-state.cljk'
PREFILL_HELPER = ASSETS / 'mithril-domain-prefill.cljk'
PROBE_SCRIPT = ASSETS / 'ontology_probe.py'
STATE_SCHEMA = Path(MITHRIL) / 'ontology/state-graph-v1.mith'
RUN_ROOT = Path(os.environ.get('BENCH_RUN_ROOT', '/tmp/mithril-harness'))
MAX_STEPS = int(os.environ.get('BENCH_MAX_STEPS', '500'))
REPEAT_ID = os.environ.get('BENCH_REPEAT_ID', 'development')
CRITICAL_REVIEW = os.environ.get('BENCH_CRITICAL_REVIEW', '1') == '1'
MAX_CONSECUTIVE_INSPECT = int(os.environ.get('BENCH_MAX_CONSECUTIVE_INSPECT', '6'))
ACTIONS = ('inspect', 'modify', 'verify', 'finish')


def strip_trailing_json_commas(source):
    """Remove commas immediately before } or ] outside JSON strings only."""
    source = re.sub(r',\s*""\s*}\s*$', '}', source)
    output = []; quoted = False; escaped = False
    for i, ch in enumerate(source):
        if quoted:
            output.append(ch)
            if escaped: escaped = False
            elif ch == '\\': escaped = True
            elif ch == '"': quoted = False
        elif ch == '"':
            quoted = True; output.append(ch)
        elif ch == ',':
            j = i + 1
            while j < len(source) and source[j].isspace(): j += 1
            if j < len(source) and source[j] in '}]': continue
            output.append(ch)
        else:
            output.append(ch)
    return ''.join(output)


def last_json_object(raw, accept):
    decoder = json.JSONDecoder(); found = None
    for i, ch in enumerate(raw):
        if ch != '{': continue
        try:
            candidate, _ = decoder.raw_decode(strip_trailing_json_commas(raw[i:]))
            if isinstance(candidate, dict) and accept(candidate): found = candidate
        except json.JSONDecodeError:
            pass
    return found


class HarnessLoop(BaseAgent):
    """`semantic=False` is the plain ReAct lane; True adds the Mithril layer:
    source probe + prefill, OWL/SHACL task state, BPMN admission, inspect
    budget, critical review and the required-artifact finish check."""
    lane = 'baseline'
    lane_id = None
    semantic = False

    @staticmethod
    def name(): return 'hermes-gpt6-luna-terminal-loop'
    def version(self): return 'mithril-harness-1'
    async def setup(self, environment): pass

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls = []; self.failed_usage_files = []; self.history = []
        self.semantic_receipts = 0; self.task_state_receipts = []; self.hypotheses = []
        self.mith_wall_seconds = 0.0; self.prompt_chars = []
        self.critical_review_requested = False; self.critical_review_done = False
        self.probe_data = None; self.plan = None; self.domain_receipt = None
        self.latest_state_receipt = None; self.created_artifacts = set()
        self.run_id = f'{self.lane}-{uuid.uuid4().hex[:16]}'
        self.state = RUN_ROOT / 'state' / f'{self.run_id}-state.edn'
        self.state.parent.mkdir(parents=True, exist_ok=True)
        self.usage_dir = RUN_ROOT / 'usage' / self.run_id
        self.usage_dir.mkdir(parents=True, exist_ok=True)

    # ---- hooks -----------------------------------------------------------
    def task_text(self, instruction): return instruction
    async def execute_action(self, environment, action): return await self.shell(environment, action['command'])
    async def finish_refusal(self, environment, instruction): return None
    def extra_metadata(self): return {}

    # ---- model and tool boundaries --------------------------------------
    async def hermes_call(self, prompt, usage, kind):
        """Retry a failed provider turn without rerunning a terminal action."""
        model = os.environ.get('BENCH_MODEL', 'openai/gpt-6-luna')
        failures = []
        for attempt in range(3):
            attempt_usage = usage if attempt == 0 else usage.with_name(f'{usage.stem}-retry-{attempt}{usage.suffix}')
            p = await asyncio.create_subprocess_exec(
                HERMES, '--provider', 'openrouter', '--model', model,
                '--reasoning', 'medium', '--ignore-user-config', '--ignore-rules', '--toolsets', 'todo',
                '--usage-file', str(attempt_usage), '-z', prompt,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, err = await p.communicate()
            if p.returncode == 0:
                self.calls.append({'usage_file': str(attempt_usage), 'exit_code': 0, 'kind': kind})
                return out.decode(errors='replace')
            receipt = {}
            if attempt_usage.exists():
                try: receipt = json.loads(attempt_usage.read_text())
                except (ValueError, OSError): pass
                self.failed_usage_files.append(str(attempt_usage))
            detail = (err.decode(errors='replace')[-800:] or out.decode(errors='replace')[-800:]).strip()
            failures.append({'exit': p.returncode, 'partial': receipt.get('partial'),
                             'api_calls': receipt.get('api_calls'), 'detail': detail})
            # The terminal has not been touched; only a partial provider turn is retryable.
            if not receipt.get('partial') or attempt == 2:
                break
            await asyncio.sleep(2 * (attempt + 1))
        raise RuntimeError(f'Hermes {kind} failed after {len(failures)} attempt(s): {json.dumps(failures)}')

    async def shell(self, environment, command):
        try:
            res = await environment.exec(command=command, timeout_sec=120)
            return {'exit_code': res.return_code, 'stdout': (res.stdout or '')[-12000:], 'stderr': (res.stderr or '')[-4000:]}
        except RuntimeError as exc:
            if 'timed out' not in str(exc).lower(): raise
            return {'exit_code': 124, 'stdout': '', 'stderr': 'Command exceeded 120 second execution limit; choose a bounded approach.'}

    async def kbb_json(self, args, label):
        started = time.monotonic()
        p = await asyncio.create_subprocess_exec(KBB, '--classpath', CLASSPATH, *args, cwd=str(MITHRIL),
                                                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await p.communicate()
        self.mith_wall_seconds += time.monotonic() - started
        if p.returncode: raise RuntimeError(label + (err.decode()[-1200:] or out.decode()[-1200:]))
        data = json.loads(out.decode().strip().splitlines()[-1])
        if 'error' in data: raise RuntimeError(data)
        return data

    # ---- Mithril semantic layer -----------------------------------------
    async def mith(self, op, action='', outcome='true'):
        return await self.kbb_json([str(HELPER), str(PROFILE), str(self.state), op, action, outcome], '')

    async def encode_task_state(self, instruction, phase):
        observed_text = json.dumps(self.history[-1].get('result', {}), ensure_ascii=False) if self.history else ''
        known = self.probe_data.get('classes', []) if self.probe_data else []
        observed = [name for name in known if name in observed_text][:24]
        prefixes = self.probe_data.get('prefixes', {}) if self.probe_data else {}
        def expand(name):
            prefix, sep, local = name.partition(':')
            return prefixes.get(prefix, '') + local if sep and prefix in prefixes else name
        focus = [name for name in (self.plan or {}).get('focus_classes', []) if name in known]
        state = {'task_text': instruction, 'phase': phase, 'hypotheses': self.hypotheses[-3:],
                 'latest_observation': self.history[-1] if self.history else {},
                 'action_count': len(self.history), 'prefill_plan': self.plan or {},
                 'domain_focus_classes': [expand(name) for name in focus],
                 'domain_observed_classes': [expand(name) for name in observed]}
        state_path = self.state.with_suffix('.task.json')
        document_path = self.state.with_suffix('.task.jsonld')
        state_path.write_text(json.dumps(state, ensure_ascii=False))
        receipt = await self.kbb_json([str(TASK_HELPER), str(state_path), str(document_path),
                                       str(self.domain_ontology), str(STATE_SCHEMA)], 'Mithril task state: ')
        self.task_state_receipts.append(receipt)
        self.latest_state_receipt = receipt
        return receipt

    async def ontology_probe(self, instruction, environment):
        matches = re.findall(r'/app/\d{4}-q\d+', instruction)
        if not matches: raise RuntimeError('No target bundle directory in task instruction')
        command = "python3 - " + shlex.quote(matches[0]) + " <<'PY'\n" + PROBE_SCRIPT.read_text() + "\nPY"
        result = await environment.exec(command=command, timeout_sec=120)
        if result.return_code: raise RuntimeError('Ontology probe failed: ' + (result.stderr or '')[-1000:])
        probe = json.loads(result.stdout.strip().splitlines()[-1])
        if not probe.get('classes') or not probe.get('ontology_files'):
            raise RuntimeError('Ontology probe returned no schema evidence')
        self.probe_data = probe
        self.state.with_suffix('.probe.json').write_text(json.dumps(probe, ensure_ascii=False))
        return probe

    async def prefill_task(self, instruction, probe):
        prompt = ('Before solving the task, map its requirements to the observed source ontology. '
                  'Return exactly one JSON object with arrays: goals (observable acceptance goals), '
                  'constraints (hard prohibitions and edge cases), hypotheses (2-4 falsifiable domain hypotheses), '
                  'focus_classes (2-6 class names copied exactly from the inventory), '
                  'focus_properties (property names copied exactly from the inventory). '
                  'Use only task instruction and source inventory; do not invent a solution or rely on verifier fixtures.\n'
                  f'TASK:\n{instruction}\nSOURCE INVENTORY:\n{json.dumps(probe, ensure_ascii=False)}')
        if getattr(self, 'knowledge_guidance', None):
            prompt += '\nPRECOMPILED MITH KNOWLEDGE (hypotheses, verify against source):\n' + self.knowledge_guidance
        started = time.monotonic()
        raw = await self.hermes_call(prompt, self.usage_dir / 'call-000.json', 'prefill')
        candidate = last_json_object(raw, lambda c: isinstance(c.get('goals'), list))
        if candidate is None: raise RuntimeError('Prefill returned no structured task ontology plan')
        def strings(key, limit): return [str(v)[:1000] for v in candidate.get(key, []) if isinstance(v, str)][:limit]
        known_classes = set(probe['classes']); known_properties = set(probe['properties'])
        self.plan = {'goals': strings('goals', 8), 'constraints': strings('constraints', 8),
                     'hypotheses': strings('hypotheses', 4),
                     'focus_classes': [v for v in strings('focus_classes', 8) if v in known_classes],
                     'focus_properties': [v for v in strings('focus_properties', 12) if v in known_properties]}
        if not self.plan['goals'] or not self.plan['focus_classes']:
            raise RuntimeError('Prefill lacked source-grounded goals or focus classes')
        self.prompt_chars.append(len(prompt))
        self.state.with_suffix('.plan.json').write_text(json.dumps(self.plan, ensure_ascii=False))
        self.prefill_wall_seconds = time.monotonic() - started
        return self.plan

    async def compile_domain_ontology(self):
        self.domain_ontology = self.state.with_suffix('.domain.mith')
        self.domain_receipt = await self.kbb_json(
            [str(PREFILL_HELPER), str(self.state.with_suffix('.probe.json')),
             str(self.state.with_suffix('.plan.json')), str(self.domain_ontology)],
            'Mithril domain prefill failed: ')
        return self.domain_receipt

    @staticmethod
    def required_artifacts(instruction):
        match = re.search(r'Create the following files:\s*(.*?)(?:\n\n|$)', instruction, re.S)
        return re.findall(r'`(/[^`\n]+)`', match.group(1)) if match else []

    async def artifact_check(self, environment, paths):
        if not paths: return {'exit_code': 0, 'stdout': 'No explicit file list in task', 'stderr': ''}
        command = 'for p in ' + ' '.join(shlex.quote(p) for p in paths) + '; do if test -f "$p"; then echo "PRESENT $p"; else echo "MISSING $p"; fi; done'
        return await self.shell(environment, command)

    def inspect_streak(self):
        streak = 0
        for earlier in reversed(self.history):
            if earlier['action'] == 'controller': continue
            if earlier['action'] != 'inspect': break
            streak += 1
        return streak

    def phase(self):
        return ('hypothesize' if not self.history else
                'reflect' if self.history[-1]['result']['exit_code'] != 0 else 'experiment')

    # ---- policy call ------------------------------------------------------
    def semantic_prompt(self, instruction):
        missing = [p for p in self.required_artifacts(instruction) if p not in self.created_artifacts]
        text = (f'\nRESEARCH PHASE: {self.phase()}. Required artifacts still unconfirmed: {missing}. '
                'Use a Co-Scientist cycle: propose a concrete hypothesis, run the cheapest command that can refute it, '
                'record what the output changed, then revise. Return fields hypothesis and prediction alongside action. '
                'After two inspections, favor producing and checking the required files. '
                'A finish action is refused while required files are missing.\n'
                f'ACTIVE HYPOTHESES: {json.dumps(self.hypotheses[-3:], ensure_ascii=False)}')
        streak = self.inspect_streak()
        if streak >= MAX_CONSECUTIVE_INSPECT:
            text += ('\nEXPERIMENT BUDGET: The last ' + str(streak) + ' actions only inspected data. '
                     'Use the ontology evidence already gathered to create the required artifacts now. '
                     'Inspect is unavailable until after a modify or verify action.')
        text += ('\nPREFILLED TASK ONTOLOGY: ' + json.dumps(self.plan, ensure_ascii=False)
                 + '\nOWL-ENTAILED SOURCE CLASS FAMILIES: '
                 + json.dumps(self.domain_receipt.get('entailed-descendants', {}), ensure_ascii=False)
                 + '\nLATEST DOMAIN EVIDENCE: '
                 + json.dumps((self.latest_state_receipt or {}).get('domain-entailed', {}), ensure_ascii=False)
                 + '\nUse only source vocabulary when adding RDF triples. Resolve one uncertain ontology relation or data-normalization hypothesis per experiment; test both standalone SPARQL queries on unified.ttl before finish.')
        if getattr(self, 'jev_guidance', None):
            text += '\nTYPED JEV PRIORITY (a hypothesis to test, not an accepted fact): ' + self.jev_guidance
        if getattr(self, 'knowledge_guidance', None):
            text += '\nPRECOMPILED MITH KNOWLEDGE (source verification required): ' + self.knowledge_guidance
        if CRITICAL_REVIEW and self.critical_review_requested and not self.critical_review_done:
            text += ('\nCRITICAL REVIEW REQUIRED: Challenge the solution as a skeptical reviewer. '
                     'Run a concrete verification command that checks generated triples use only source ontology/data terms, '
                     'both SPARQL files execute directly over unified.ttl, and the stated edge cases. '
                     'Return action="verify"; revise the files if it fails. Do not finish in this turn.')
        return text

    async def query(self, instruction, enabled):
        n = len(self.calls)
        transcript = json.dumps(self.history, ensure_ascii=False)
        prompt = ("You are a terminal task-solving agent. Return exactly one JSON object and no markdown: "
                  '{"action":"inspect|modify|verify|finish","command":"bash command","reason":"brief"}. '
                  'Commands execute in the isolated benchmark container. Multi-line bash commands and file edits are allowed. '
                  'Choose finish only after checking the required artifact or behavior. Do not repeat an unchanged failed command. '
                  'The full prior transcript is provided below, as in an interactive terminal agent.\n'
                  'The JSON must parse strictly: no trailing commas or empty keys.\n'
                  f'TASK:\n{self.task_text(instruction)}\n\nALLOWED ACTIONS: {enabled}\n'
                  f'FULL TRANSCRIPT: {transcript}\n'
                  'Execute the next action. For finish use command="true".')
        if self.semantic:
            prompt += self.semantic_prompt(instruction)
        self.prompt_chars.append(len(prompt))
        raw = (await self.hermes_call(prompt, self.usage_dir / f'call-{n:03}.json', 'action')).strip()
        valid = lambda c: c.get('action') in ACTIONS
        action = last_json_object(raw, valid)
        if action is None:
            repair_prompt = ('Repair this malformed JSON action without changing its intended command or meaning. '
                             'Return exactly one valid JSON object with action and command fields, no markdown.\n'
                             + raw[-12000:])
            self.prompt_chars.append(len(repair_prompt))
            repaired = await self.hermes_call(repair_prompt, self.usage_dir / f'call-{n:03}-repair.json', 'json-repair')
            action = last_json_object(repaired, valid)
        if action is None: raise RuntimeError('No valid JSON action returned after repair: ' + raw[-1000:])
        if action.get('action') not in ACTIONS or not isinstance(action.get('command'), str):
            raise RuntimeError('Invalid action object: ' + str(action))
        return action

    # ---- the loop ----------------------------------------------------------
    def refuse(self, command, stderr, stdout=''):
        self.history.append({'action': 'verify', 'command': command,
                             'result': {'exit_code': 1, 'stdout': stdout, 'stderr': stderr}})

    async def finish_gates(self, environment, instruction, required):
        """Returns True when finish is admitted; otherwise records the refusal."""
        if not self.semantic: return True
        if CRITICAL_REVIEW and not self.critical_review_requested:
            self.critical_review_requested = True
            self.refuse('critical review gate', 'Finish held for independent acceptance review'); return False
        if CRITICAL_REVIEW and not self.critical_review_done:
            self.refuse('critical review gate', 'Run an acceptance verification command before finish'); return False
        if required:
            check = await self.artifact_check(environment, required)
            present = set(re.findall(r'^PRESENT (.+)$', check['stdout'], re.M))
            self.created_artifacts = present
            if len(present) != len(required):
                self.refuse('required artifact check', 'Finish refused: required artifacts missing', check['stdout']); return False
        return True

    async def run(self, instruction, environment, context):
        started = time.time()
        self.created_artifacts = set()
        required = self.required_artifacts(instruction)
        try:
            if self.semantic:
                probe = await self.ontology_probe(instruction, environment)
                await self.prefill_task(instruction, probe)
                await self.compile_domain_ontology()
            for step in range(MAX_STEPS):
                streak = 0
                if self.semantic:
                    enabled_state = await self.mith('enabled')
                    enabled = enabled_state.get('actions', [])
                    if enabled_state.get('completed'): break
                    streak = self.inspect_streak()
                    if streak >= MAX_CONSECUTIVE_INSPECT:
                        enabled = [item for item in enabled if not item.endswith('/inspect')]
                    await self.encode_task_state(instruction, self.phase())
                    if hasattr(self, 'before_query'):
                        await self.before_query(instruction)
                else:
                    enabled = [f'https://mithril.fund/id/action/terminal/{kind}'
                               for kind in ['finish', 'inspect', 'modify', 'verify']]
                action = await self.query(instruction, enabled)
                kind = action['action']; cmd = action['command']
                if self.semantic and kind == 'inspect' and streak >= MAX_CONSECUTIVE_INSPECT:
                    self.history.append({'action': 'controller', 'command': 'inspection budget',
                                         'result': {'exit_code': 1, 'stdout': '',
                                                    'stderr': 'Inspect budget exhausted; create or verify an artifact'}})
                    continue
                if self.semantic and isinstance(action.get('hypothesis'), str):
                    self.hypotheses.append({'text': action['hypothesis'][:600],
                                            'prediction': str(action.get('prediction', ''))[:400], 'step': step})
                if kind == 'finish':
                    refusal = await self.finish_refusal(environment, instruction)
                    if refusal:
                        self.refuse('finish gate', refusal); continue
                    if not await self.finish_gates(environment, instruction, required): continue
                    if self.semantic:
                        action_id = 'https://mithril.fund/id/action/terminal/finish'
                        semantic = await self.mith('select', action_id, cmd)
                        if semantic.get('semantic', {}).get('entailed'): self.semantic_receipts += 1
                        await self.mith('complete', action_id)
                    self.history.append({'action': kind, 'command': cmd, 'result': {'exit_code': 0, 'stdout': 'Agent finished', 'stderr': ''}})
                    break
                if self.semantic:
                    action_id = f'https://mithril.fund/id/action/terminal/{kind}'
                    semantic = await self.mith('select', action_id, cmd)
                    if semantic.get('semantic', {}).get('entailed'): self.semantic_receipts += 1
                result = await self.execute_action(environment, action)
                self.history.append({'action': kind, 'command': action['command'], 'result': result})
                if self.semantic and self.critical_review_requested and kind == 'verify' and result['exit_code'] == 0:
                    self.critical_review_done = True
                if self.semantic: await self.mith('complete', action_id, str(result['exit_code'] == 0).lower())
            self.record_usage(context, started, required)
        finally:
            (RUN_ROOT / 'receipts').mkdir(parents=True, exist_ok=True)
            (RUN_ROOT / 'receipts' / f'{self.run_id}.json').write_text(json.dumps({
                'instruction_sha256': hashlib.sha256(instruction.encode()).hexdigest(),
                'actions': self.history, 'calls': self.calls, 'semantic_receipts': self.semantic_receipts,
                'task_state_receipts': self.task_state_receipts, 'domain_receipt': self.domain_receipt}, indent=2))

    def record_usage(self, context, started, required):
        usage = []
        for p in sorted(self.usage_dir.glob('call-*.json')):
            try: usage.append(json.loads(p.read_text()))
            except Exception: pass
        jev_usage_files = getattr(self, 'jev_usage_files', [])
        for p in jev_usage_files:
            try: usage.append(json.loads(Path(p).read_text()))
            except Exception: pass
        def field(u, k): return u.get(k) or u.get('usage', {}).get(k)
        def sm(k): return sum(field(u, k) or 0 for u in usage)
        context.n_input_tokens = sum(((field(u, 'total_tokens') or 0) - (field(u, 'output_tokens') or 0))
                                     if field(u, 'total_tokens') else (field(u, 'input_tokens') or 0)
                                     for u in usage)
        context.n_output_tokens = sm('output_tokens')
        context.n_cache_tokens = sm('cache_read_tokens') + sm('cache_write_tokens')
        costs = [u.get('estimated_cost_usd', u.get('cost_usd')) for u in usage]
        context.cost_usd = sum(c for c in costs if isinstance(c, (int, float))) if any(isinstance(c, (int, float)) for c in costs) else None
        knowledge = getattr(self, 'knowledge_receipt', None) or {}
        context.metadata = {
            'lane': self.lane, 'run_id': self.run_id, 'repeat_id': REPEAT_ID, 'step_count': len(self.history),
            'hermes_calls': len(self.calls), 'usage_files': [x['usage_file'] for x in self.calls],
            'wall_agent_seconds': round(time.time() - started, 3),
            'mithril_ontology_sha256': hashlib.sha256(ONTOLOGY.read_bytes()).hexdigest() if self.semantic else None,
            'semantic_receipts': self.semantic_receipts,
            'task_state_receipts': len(self.task_state_receipts), 'failed_usage_files': self.failed_usage_files,
            'jev_calls': len(jev_usage_files), 'jev_usage_files': [str(p) for p in jev_usage_files],
            'jev_decisions': getattr(self, 'jev_decisions', []),
            'domain_ontology_digest': (self.domain_receipt or {}).get('ontology-digest'),
            'domain_source_class_count': (self.domain_receipt or {}).get('source-class-count'),
            'knowledge_general_digest': knowledge.get('general-digest'),
            'knowledge_task_digest': knowledge.get('task-digest'),
            'knowledge_general_rules': knowledge.get('general-rule-count'),
            'knowledge_task_rules': knowledge.get('task-rule-count'),
            'prefill_wall_seconds': round(getattr(self, 'prefill_wall_seconds', 0), 3),
            'critical_review_enabled': CRITICAL_REVIEW if self.semantic else False,
            'mithril_wall_seconds': round(self.mith_wall_seconds, 3),
            'prompt_chars_total': sum(self.prompt_chars), 'required_artifacts': required,
            'artifact_count_confirmed': len(self.created_artifacts),
            'harness_version': self.version(), 'harness_lane': self.lane_id}
        context.metadata.update(self.extra_metadata())
