"""Jev hypothesis routing between GPT-6 Luna calls in the Mithril v6 loop.

The decision input is only the task-derived plan and current agent observation.
Jev selects a bounded question; Luna still authors terminal commands. The
benchmark verifier, reference solution, and hidden fixtures are never input.
"""

import asyncio
import json
import os
import time
import urllib.request

from agent import MithrilDomainPrefillAgent


QUESTIONS = {
    'identity': 'Check how submissions identify the same physical operational point.',
    'recency': 'Check which submission wins when facts about a point conflict.',
    'coordinates': 'Check optional latitude and longitude formats and missing values.',
    'adjacency': 'Check direct line-section connections and distinct section counts.',
    'qualification': 'Check voltage units, authorized vehicles, and high-speed counts.',
    'independent_check': 'Compute expected rows independently from source RDF and compare both standalone SPARQL queries.',
}


def decide(state, api_key):
    request = {
        'model': 'typesafe/jev-1.13',
        'state': state,
        'questions': {'next_hypothesis': {
            'type': 'choice',
            'instructions': 'Select the most useful next falsifiable domain hypothesis for the railway task. A selection is a priority, never proof. Prefer an independent result check after files exist.',
            'criteria': QUESTIONS,
        }},
    }
    body = json.dumps(request, ensure_ascii=False).encode()
    http_request = urllib.request.Request(
        'https://openrouter.ai/api/alpha/decisions', data=body,
        headers={'Authorization': 'Bearer ' + api_key,
                 'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(http_request, timeout=35) as response:
        result = json.load(response)
    answer = result.get('answers', {}).get('next_hypothesis', {})
    choice = answer.get('choice')
    probabilities = answer.get('probabilities')
    confidence = answer.get('confidence')
    if (result.get('model', '').split('-2026')[0] != 'typesafe/jev-1.13'
            or choice not in QUESTIONS or not isinstance(probabilities, dict)
            or set(probabilities) != set(QUESTIONS)
            or not isinstance(confidence, (float, int))
            or not 0 <= confidence <= 1):
        raise RuntimeError('Jev response failed model, candidate, or probability checks')
    usage = result.get('usage') or {}
    if not all(isinstance(usage.get(key), (int, float)) for key in ('input_tokens', 'output_tokens', 'cost')):
        raise RuntimeError('Jev usage receipt is incomplete')
    return {'choice': choice, 'confidence': confidence,
            'probabilities': probabilities, 'usage': usage,
            'model': result['model'], 'request_id': result.get('id')}


class MithrilJevInterleavedAgent(MithrilDomainPrefillAgent):
    @staticmethod
    def name():
        return 'mithril-jev-interleaved-gpt6-luna-terminal-loop'

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
            'step': len(self.history),
            'last_action': latest.get('action'),
            'last_exit_code': latest.get('result', {}).get('exit_code'),
            'last_observation': latest.get('result', {}).get('stdout', '')[-1200:],
            'last_error': latest.get('result', {}).get('stderr', '')[-600:],
            'confirmed_artifacts': sorted(self.created_artifacts),
            'domain_evidence': receipt.get('domain-entailed', {}),
        }, ensure_ascii=False, sort_keys=True)
        started = time.monotonic()
        result = await asyncio.to_thread(decide, state, api_key)
        elapsed = time.monotonic() - started
        index = len(self.jev_decisions)
        usage_path = self.usage_dir / f'jev-{index:03}.json'
        usage_path.write_text(json.dumps({**result['usage'], 'estimated_cost_usd': result['usage']['cost']}))
        self.jev_usage_files.append(str(usage_path))
        self.jev_decisions.append({
            'step': len(self.history), 'choice': result['choice'],
            'confidence': result['confidence'], 'model': result['model'],
            'request_id': result['request_id'], 'wall_seconds': round(elapsed, 3),
        })
        self.jev_guidance = QUESTIONS[result['choice']] if result['confidence'] >= 0.6 else None
