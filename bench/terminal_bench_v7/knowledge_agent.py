"""Luna/Mithril loop with precompiled reusable and railway task knowledge.

The two versioned .mith files are compiled before the first Luna call. The
model sees bounded retrieval results, not an unverified claim of OWL proof.
"""

import asyncio
import json
import re
import sys
from pathlib import Path

V6 = Path(__file__).resolve().parents[1] / 'terminal_bench_v6'
if str(V6) not in sys.path:
    sys.path.insert(0, str(V6))

from agent import CLASSPATH, KBB, MITHRIL, MithrilDomainPrefillAgent
from jev_interleave import MithrilJevInterleavedAgent

ROOT = Path(__file__).resolve().parent
GENERAL = ROOT / 'knowledge' / 'general-reasoning-v1.mith'
TASK = ROOT / 'knowledge' / 'railway-query-v1.mith'
LOOKUP = ROOT / 'knowledge_lookup.cljk'


class KnowledgeMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.knowledge_receipt = None
        self.knowledge_guidance = None
        self.knowledge_rules = []

    async def compile_knowledge(self):
        process = await asyncio.create_subprocess_exec(
            KBB, '--classpath', CLASSPATH, str(LOOKUP), str(GENERAL), str(TASK),
            cwd=str(MITHRIL), stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await process.communicate()
        if process.returncode:
            raise RuntimeError('Mith knowledge compile failed: ' +
                               (stderr.decode(errors='replace')[-1200:] or stdout.decode(errors='replace')[-1200:]))
        receipt = json.loads(stdout.decode().strip().splitlines()[-1])
        if receipt.get('error') or not receipt.get('owl-entailed-section') or \
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
            score = sum(word in haystack for word in words)
            ranked.append((score, entry))
        ranked.sort(key=lambda pair: (-pair[0], pair[1]['id']))
        selected = [entry for score, entry in ranked if score > 0][:limit]
        if not selected:
            selected = [entry for _, entry in ranked[:limit]]
        for marker in ('/bench/rule/', '/bench/railway/task/'):
            if not any(marker in entry['id'] for entry in selected):
                category = next((entry for _, entry in ranked if marker in entry['id']), None)
                if category:
                    selected = selected[:max(0, limit - 1)] + [category]
        return json.dumps([{'id': entry['id'], 'text': entry['text']}
                           for entry in selected], ensure_ascii=False)

    async def prefill_task(self, instruction, probe):
        await self.compile_knowledge()
        self.knowledge_guidance = self.retrieve_knowledge(instruction, limit=5)
        return await super().prefill_task(instruction, probe)

    async def before_query(self, instruction):
        latest = self.history[-1] if self.history else {}
        observation = latest.get('result', {})
        focus = (observation.get('stderr') or '')[-800:] + ' ' + \
                (observation.get('stdout') or '')[-800:]
        self.knowledge_guidance = self.retrieve_knowledge(focus or instruction)
        parent_hook = getattr(super(), 'before_query', None)
        if parent_hook:
            await parent_hook(instruction)


class MithrilKnowledgeAgent(KnowledgeMixin, MithrilDomainPrefillAgent):
    @staticmethod
    def name():
        return 'mithril-precompiled-knowledge-gpt6-luna-terminal-loop'


class MithrilKnowledgeJevAgent(KnowledgeMixin, MithrilJevInterleavedAgent):
    @staticmethod
    def name():
        return 'mithril-precompiled-knowledge-jev-gpt6-luna-terminal-loop'
