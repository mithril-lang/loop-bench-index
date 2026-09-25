"""Independent review lane through the loop (scripted model; pytest via a uv shim).
Run: PYTHONPATH=harness/tests <harbor-venv>/bin/python harness/tests/test_review_lane.py"""
import asyncio, os, shutil, stat, tempfile, types
from pathlib import Path
import scripted  # noqa: F401
from scripted import Scripted, FakeEnv
from mithril_harness import lanes

root = Path(tempfile.mkdtemp())
(root / 'bin').mkdir()
shim = root / 'bin' / 'python3'
shim.write_text("#!/bin/sh\nexec uv run --quiet --no-project --with pytest python \"$@\"\n")
shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
os.environ['PATH'] = f'{root}/bin:' + os.environ['PATH']
shutil.rmtree('/tmp/review_tests', ignore_errors=True)

review_file = "```python\ndef test_ok():\n    assert True\n\ndef test_edge():\n    assert 1 == 2\n```"
act = lambda a, c: '{"action":"%s","command":"%s"}' % (a, c)
replies = [act('finish', 'true'),                      # held: test_edge fails
           act('modify', "printf 'test_edge: the spec allows either value here' > /tmp/review_tests/DISPUTED.txt"),
           act('finish', 'true')]                      # admitted: failure disputed

class T(Scripted, lanes.ReviewLane):
    transport = 'chat'
agent = T(logs_dir=root / 'logs'); agent.replies = replies
async def hc(prompt, usage, kind):
    agent.prompts.append((kind, prompt)); agent.calls.append({'usage_file': str(usage), 'exit_code': 0, 'kind': kind})
    return review_file if kind == 'review' else agent.replies.pop(0)
agent.hermes_call = hc
ctx = types.SimpleNamespace(metadata=None)
asyncio.run(agent.run('Build the thing described here.', FakeEnv(), ctx))
held = [h for h in agent.history if h['command'] == 'finish gate']
assert held and 'test_edge' in held[0]['result']['stderr'], held
assert agent.history[-1]['action'] == 'finish'
review_prompt = [p for k, p in agent.prompts if k == 'review'][0]
assert 'FILE NAMES UNDER /app' in review_prompt and 'printf' not in review_prompt  # reviewer never sees the transcript
reports = ctx.metadata['review_reports']
assert reports[0]['open'] == ['test_edge'] and reports[-1]['disputed'] == ['test_edge'] and reports[-1]['open'] == [], reports
print('REVIEW LANE OK', reports)
shutil.rmtree('/tmp/review_tests', ignore_errors=True)
