import asyncio, json, os, re, subprocess, time
from pathlib import Path

from harbor.agents.base import BaseAgent

ROOT = Path(__file__).resolve().parent
HERMES = os.environ.get('HERMES_BIN', '/Users/junkawasaki/.hermes/hermes-agent/venv/bin/hermes')
KBB = os.environ.get('KBB_BIN', '/opt/homebrew/bin/kbb')
MITHRIL = os.environ.get('MITHRIL_RUNTIME', '/Users/junkawasaki/.hermes/runtime/mithril')
CLASSPATH = os.environ.get('MITHRIL_CLASSPATH', '')
HELPER = ROOT / 'mithril-bpmn-step.cljk'
PROFILE = ROOT / 'terminal-agent-loop-v1.mith'
ONTOLOGY = ROOT / 'terminal-actions-v1.mith'
RUN_ROOT = Path(os.environ.get('BENCH_RUN_ROOT', '/tmp/terminal-bench-v2'))
MAX_STEPS = int(os.environ.get('BENCH_MAX_STEPS', '64'))

class LoopAgent(BaseAgent):
    lane = 'baseline'
    @staticmethod
    def name(): return 'hermes-gpt6-luna-terminal-loop'
    def version(self): return '0.1.0'
    async def setup(self, environment): pass
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls=[]
        self.history=[]
        self.state=RUN_ROOT / 'state' / f'{self.lane}-{os.getpid()}-state.edn'
        self.state.parent.mkdir(parents=True, exist_ok=True)
        self.usage_dir=RUN_ROOT / 'usage' / f'{self.lane}-{os.getpid()}'
        self.usage_dir.mkdir(parents=True, exist_ok=True)

    async def shell(self, environment, command):
        try:
            res=await environment.exec(command=command, timeout_sec=120)
            return {'exit_code':res.return_code,'stdout':(res.stdout or '')[-12000:],'stderr':(res.stderr or '')[-4000:]}
        except RuntimeError as exc:
            if 'timed out' not in str(exc).lower(): raise
            return {'exit_code':124,'stdout':'','stderr':'Command exceeded 120 second execution limit; choose a bounded approach.'}

    async def mith(self, op, action='', outcome='true'):
        args=[KBB,'--classpath',CLASSPATH,str(HELPER),str(PROFILE),str(self.state),op,action,outcome]
        p=await asyncio.create_subprocess_exec(*args,cwd=str(MITHRIL),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        out,err=await p.communicate()
        if p.returncode: raise RuntimeError(err.decode()[-2000:] or out.decode()[-2000:])
        data=json.loads(out.decode().strip().splitlines()[-1])
        if 'error' in data: raise RuntimeError(data)
        return data

    async def query(self, instruction, enabled):
        n=len(self.calls)
        transcript=json.dumps(self.history,ensure_ascii=False)
        prompt=("You are a terminal task-solving agent. Return exactly one JSON object and no markdown: "
          '{"action":"inspect|modify|verify|finish","command":"bash command","reason":"brief"}. '
          'Commands execute in the isolated benchmark container. Multi-line bash commands and file edits are allowed. '
          'Choose finish only after checking the required artifact or behavior. Do not repeat an unchanged failed command. '
          'The full prior transcript is provided below, as in an interactive terminal agent.\n'
          f'TASK:\n{instruction}\n\nALLOWED ACTIONS: {enabled}\n'
          f'FULL TRANSCRIPT: {transcript}\n'
          'Execute the next action. For finish use command="true".')
        usage=self.usage_dir/f'call-{n:03}.json'
        p=await asyncio.create_subprocess_exec(HERMES,'--provider','openrouter','--model','openai/gpt-6-luna','--reasoning','medium','--ignore-user-config','--ignore-rules','--toolsets','todo','--usage-file',str(usage),'-z',prompt,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        out,err=await p.communicate()
        if p.returncode: raise RuntimeError(f'Hermes exit {p.returncode}: {err.decode()[-1000:]}')
        raw=out.decode(errors='replace').strip()
        self.calls.append({'usage_file':str(usage),'exit_code':p.returncode})
        decoder=json.JSONDecoder(); action=None
        for i,ch in enumerate(raw):
            if ch!='{': continue
            try:
                candidate,_=decoder.raw_decode(raw[i:])
                if isinstance(candidate,dict) and candidate.get('action') in ('inspect','modify','verify','finish'):
                    action=candidate
            except json.JSONDecodeError: pass
        if action is None: raise RuntimeError('No valid JSON action returned: '+raw[-1000:])
        if action.get('action') not in ('inspect','modify','verify','finish') or not isinstance(action.get('command'),str):
            raise RuntimeError('Invalid action object: '+str(action))
        return action

    async def run(self, instruction, environment, context):
        started=time.time(); max_steps=MAX_STEPS
        try:
            for step in range(max_steps):
                if self.lane=='mithril':
                    enabled_state=await self.mith('enabled')
                    enabled=enabled_state.get('actions',[])
                    if enabled_state.get('completed'): break
                else: enabled=['inspect','modify','verify','finish']
                action=await self.query(instruction,enabled)
                kind=action['action']; cmd=action['command']
                if kind=='finish':
                    if self.lane=='mithril':
                        action_id='https://mithril.fund/id/action/terminal/finish'
                        await self.mith('select',action_id); await self.mith('complete',action_id)
                    self.history.append({'action':kind,'command':cmd,'result':{'exit_code':0,'stdout':'Agent finished','stderr':''}})
                    break
                if self.lane=='mithril':
                    action_id=f'https://mithril.fund/id/action/terminal/{kind}'
                    await self.mith('select',action_id)
                result=await self.shell(environment,cmd)
                self.history.append({'action':kind,'command':cmd,'result':result})
                if self.lane=='mithril': await self.mith('complete',action_id)
            usage=[]
            for p in sorted(self.usage_dir.glob('call-*.json')):
                try: usage.append(json.loads(p.read_text()))
                except Exception: pass
            def sm(k): return sum((u.get(k) or u.get('usage',{}).get(k) or 0) for u in usage)
            context.n_input_tokens=sm('total_tokens')-sm('output_tokens') or sm('input_tokens')
            context.n_output_tokens=sm('output_tokens')
            context.n_cache_tokens=sm('cache_read_tokens')+sm('cache_write_tokens')
            costs=[u.get('estimated_cost_usd',u.get('cost_usd')) for u in usage]
            context.cost_usd=sum(c for c in costs if isinstance(c,(int,float))) if any(isinstance(c,(int,float)) for c in costs) else None
            context.metadata={'lane':self.lane,'step_count':len(self.history),'hermes_calls':len(self.calls),'usage_files':[x['usage_file'] for x in self.calls],'wall_agent_seconds':round(time.time()-started,3),'mithril_ontology_sha256':__import__('hashlib').sha256(ONTOLOGY.read_bytes()).hexdigest() if self.lane=='mithril' else None}
        finally:
            (RUN_ROOT/'receipts').mkdir(parents=True,exist_ok=True)
            (RUN_ROOT/'receipts'/f'{self.lane}-{os.getpid()}.json').write_text(json.dumps({'instruction_sha256':__import__('hashlib').sha256(instruction.encode()).hexdigest(),'actions':self.history,'calls':self.calls},indent=2))

class HermesBaselineAgent(LoopAgent):
    lane='baseline'

class MithrilBpmnAgent(LoopAgent):
    lane='mithril'
    @staticmethod
    def name(): return 'mithril-ontology-bpmn-gpt6-luna-terminal-loop'
