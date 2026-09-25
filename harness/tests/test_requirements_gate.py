"""Requirements gate: coverage parsing (uv + pytest) and finish gating through the loop.
Run: PYTHONPATH=harness/tests <harbor-venv>/bin/python harness/tests/test_requirements_gate.py"""
import asyncio, json, os, sys, tempfile, types, subprocess
from pathlib import Path
sys.path.insert(0, 'harness/tests'); import scripted  # noqa
from scripted import Scripted, FakeEnv
from mithril_harness import lanes, requirements
# 1) check script: covers parsing, pass/fail, waivers (pytest via uv python)
d = Path('/tmp/harness_tests'); import shutil; shutil.rmtree(d, ignore_errors=True); d.mkdir()
(d/'test_a.py').write_text("# covers: R1, R2\ndef test_ok():\n    assert 1 == 1\n\n# covers: R3\ndef test_bad():\n    assert 1 == 2\n")
(d/'WAIVED.txt').write_text("R4: needs network access that the sandbox does not have\n")
r = subprocess.run(['uv','run','--quiet','--no-project','--with','pytest','python','-c',requirements.CHECK_SCRIPT,'R1,R2,R3,R4,R5'],capture_output=True,text=True)
rep = json.loads(r.stdout.strip().splitlines()[-1]); print('check', {k: rep[k] for k in ('tests','passing','covered','waived','missing')})
assert rep['covered']==['R1','R2'] and rep['waived']==['R4'] and rep['missing']==['R3','R5'], rep
shutil.rmtree(d)
# 2) lane: requirements from a model reply go into the static task text; gate refuses finish and records
class T(Scripted, lanes.RequirementGateLane):
    transport = 'chat'
agent = T(logs_dir=Path(tempfile.mkdtemp()))
agent.replies = ['{"requirements": ["Output file must be sorted", "Empty input returns empty output"]}',
                 '{"action":"finish","command":"true"}', '{"action":"finish","command":"true"}',
                 '{"action":"finish","command":"true"}', '{"action":"finish","command":"true"}',
                 '{"action":"finish","command":"true"}', '{"action":"finish","command":"true"}']
async def hc(prompt, usage, kind):
    agent.prompts.append((kind, prompt)); agent.calls.append({'usage_file': str(usage), 'exit_code': 0, 'kind': kind}); return agent.replies.pop(0)
agent.hermes_call = hc
ctx = types.SimpleNamespace(metadata=None)
asyncio.run(agent.run('Do the task described in `/nonexistent/DESIGN.md`.', FakeEnv(), ctx))
msg = agent.chat_messages_log[0][1]['content']
print('R1 in task text', 'R1: Output file must be sorted' in msg, '| refusals', ctx.metadata['gate_refusals'], 'overridden', ctx.metadata['gate_overridden'], '| last action', agent.history[-1]['action'])
stderrs = [h['result']['stderr'] for h in agent.history if h['command'] == 'finish gate']
print('refusal literal', stderrs[0][:80] if stderrs else None)
