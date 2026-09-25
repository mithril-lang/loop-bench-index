"""Chat transport builds append-only message arrays (the property that makes
the provider prompt cache hit). Scripted model, local bash.
Run: PYTHONPATH=harness/tests <harbor-venv>/bin/python -m unittest harness/tests/test_chat_transport.py"""

import json
import tempfile
import unittest
from pathlib import Path

import scripted  # noqa: F401
from scripted import Scripted, run_agent

from mithril_harness import lanes, loop


def chat_lane(cls):
    return type('Chat' + cls.__name__, (Scripted, cls), {'transport': 'chat'})


class AppendOnly(unittest.TestCase):
    def check(self, cls):
        agent, context = run_agent(chat_lane(cls), Path(tempfile.mkdtemp(prefix='chat-')))
        logs = agent.chat_messages_log
        self.assertGreater(len(logs), 10, 'scenario did not exercise the loop')
        for before, after in zip(logs, logs[1:]):
            self.assertEqual(after[:len(before)], before, 'the previous prompt is not a prefix of the next')
            self.assertGreater(len(after), len(before), 'history did not grow')
        self.assertEqual(logs[0][0], {'role': 'system', 'content': loop.CHAT_SYSTEM})
        self.assertNotIn({'role': 'system', 'content': loop.CHAT_SYSTEM}, logs[0][1:])
        roles = [m['role'] for m in logs[-1]]
        self.assertEqual(roles[:2], ['system', 'user'])
        self.assertEqual(agent.history[-1]['action'], 'finish')
        self.assertEqual(context.metadata['transport'], 'chat')
        return agent, logs

    def test_mithril_lane(self):
        agent, logs = self.check(lanes.MithrilLane)
        text = json.dumps(logs[-1])
        for literal in ('Finish held for independent acceptance review', 'Inspect budget exhausted'):
            self.assertIn(literal, text)
        self.assertIn('RESEARCH PHASE', logs[-1][-1]['content'])
        self.assertEqual(json.dumps(logs[-1]).count('PREFILLED TASK ONTOLOGY'), 1)  # static part sent once
        self.assertNotIn('PREFILLED TASK ONTOLOGY', logs[-1][-1]['content'])

    def test_react_lane(self):
        agent, _ = run_agent(chat_lane(lanes.ReactLane), Path(tempfile.mkdtemp(prefix='chat-')))
        logs = agent.chat_messages_log
        for before, after in zip(logs, logs[1:]):
            self.assertEqual(after[:len(before)], before)

    def test_hermes_default_unchanged(self):
        self.assertEqual(lanes.MithrilLane.transport, loop.TRANSPORT)


if __name__ == '__main__':
    unittest.main()


class SingleTurn(unittest.TestCase):
    def test_prefill_uses_the_format_system_prompt_not_the_action_one(self):
        import asyncio
        seen = []
        async def fake(messages, usage, **kw):
            seen.append(messages)
            return '{"goals": []}'
        original = loop.chat_complete
        loop.chat_complete = fake
        try:
            agent = type('C', (lanes.MithrilLane,), {'transport': 'chat'})(logs_dir=Path(tempfile.mkdtemp()))
            asyncio.run(agent.hermes_call('Return a plan.', agent.usage_dir / 'call-000.json', 'prefill'))
        finally:
            loop.chat_complete = original
        self.assertEqual(seen[0][0], {'role': 'system', 'content': loop.CHAT_SINGLE_SYSTEM})
        self.assertNotIn('"action"', seen[0][0]['content'])


class FailedAttempts(unittest.TestCase):
    def test_timeouts_are_recorded_with_unknown_cost_then_success(self):
        import asyncio
        import os
        from mithril_harness import chat
        calls = {'n': 0}
        def fake_post(body, key, timeout):
            calls['n'] += 1
            if calls['n'] < 3:
                raise TimeoutError('read timed out')
            return {'model': 'm', 'provider': 'p', 'choices': [{'message': {'content': '{"action":"inspect"}'}}],
                    'usage': {'prompt_tokens': 100, 'completion_tokens': 5, 'cost': 0.001,
                              'prompt_tokens_details': {'cached_tokens': 90}}}
        original_post, original_sleep = chat._post, asyncio.sleep
        chat._post = fake_post
        async def no_sleep(_): return None
        chat.asyncio.sleep = no_sleep
        os.environ['OPENROUTER_API_KEY'] = 'test'
        d = Path(tempfile.mkdtemp())
        try:
            text = asyncio.run(chat.chat_complete([{'role': 'user', 'content': 'x'}], d / 'call-001.json'))
        finally:
            chat._post = original_post
            chat.asyncio.sleep = original_sleep
        self.assertEqual(text, '{"action":"inspect"}')
        failed = sorted(d.glob('call-001-failed-*.json'))
        self.assertEqual(len(failed), 2)
        record = json.loads(failed[0].read_text())
        self.assertEqual((record['status'], record['partial'], record['estimated_cost_usd']), ('TimeoutError', True, None))
        ok = json.loads((d / 'call-001.json').read_text())
        self.assertEqual((ok['input_tokens'], ok['cache_read_tokens'], ok['estimated_cost_usd']), (10, 90, 0.001))


class Deadline(unittest.TestCase):
    def test_deadline_bounds_a_request_that_never_returns(self):
        import asyncio
        import threading
        import time as _time
        from mithril_harness import chat
        release = threading.Event()
        def stuck(*_):
            release.wait(30)
            return 'late'
        started = _time.monotonic()
        with self.assertRaises(chat.DeadlineExceeded):
            asyncio.run(chat.call_with_deadline(stuck, deadline=1))
        self.assertLess(_time.monotonic() - started, 5)
        release.set()

    def test_thread_errors_pass_through_unchanged(self):
        import asyncio
        from mithril_harness import chat
        def boom(*_):
            raise TimeoutError('socket read timed out')
        with self.assertRaises(TimeoutError) as caught:
            asyncio.run(chat.call_with_deadline(boom, deadline=5))
        self.assertNotIsInstance(caught.exception, chat.DeadlineExceeded)


class MultiAction(unittest.TestCase):
    def test_chat_transport_executes_the_first_of_several_actions(self):
        import asyncio
        agent = type('C', (lanes.ReactLane,), {'transport': 'chat'})(logs_dir=Path(tempfile.mkdtemp()))
        raw = ('{"action":"modify","command":"cat > /app/a.py"} then {"action":"verify","command":"python3 /app/a.py"} '
               'and finally {"action":"finish","command":"true"}')
        action = asyncio.run(agent.parse_action(raw, 1))
        self.assertEqual(action['action'], 'modify')
        self.assertEqual(agent.multi_action_replies, 1)
        hermes = type('H', (lanes.ReactLane,), {'transport': 'hermes'})(logs_dir=Path(tempfile.mkdtemp()))
        self.assertEqual(asyncio.run(hermes.parse_action(raw, 1))['action'], 'finish')  # frozen v6 behaviour


class KnowledgeAndToolkit(unittest.TestCase):
    def test_knowledge_pack_goes_into_the_static_task_message(self):
        import asyncio
        receipt = {'packs': [{'path': 'x', 'digest': 'd', 'entries': 2}], 'axioms': 3, 'closure': 4,
                   'entries': [{'id': 'r1', 'kind': 'https://x/AlgorithmRule', 'text': 'Use BFS for minimum hops.'},
                               {'id': 'f1', 'kind': 'https://x/ObservedFailure', 'text': 'One action per reply.'}]}
        class Stub(Scripted, lanes.CombinedLane):
            transport = 'chat'
            async def kbb_json(self, args, label):
                self.pack_args = args
                return receipt
        agent, context = run_agent(Stub, Path(tempfile.mkdtemp(prefix='kp-')),
                                   replies=['{"action":"inspect","command":"true"}', '{"action":"finish","command":"true"}'])
        task_message = agent.chat_messages_log[0][1]['content']
        self.assertIn('[AlgorithmRule] Use BFS for minimum hops.', task_message)
        self.assertIn('[ObservedFailure] One action per reply.', task_message)
        self.assertIn('GRAPH TOOLKIT', task_message)
        self.assertEqual(agent.chat_messages_log[1][:2], agent.chat_messages_log[0][:2])  # static, cached prefix
        self.assertTrue(any(str(a).endswith('failure-cases-v1.mith') for a in agent.pack_args))
        self.assertEqual(context.metadata['knowledge_pack']['entries'], 2)
        self.assertIn('/opt/harness/graphkit.py', lanes.CombinedLane.container_files)
