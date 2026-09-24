import asyncio, json, os, re, subprocess, time, uuid
from pathlib import Path
from context import history_view, recall_step

from harbor.agents.base import BaseAgent

ROOT = Path(__file__).resolve().parent
HERMES = os.environ.get('HERMES_BIN', '/Users/junkawasaki/.hermes/hermes-agent/venv/bin/hermes')
KBB = os.environ.get('KBB_BIN', '/opt/homebrew/bin/kbb')
MITHRIL = os.environ.get('MITHRIL_RUNTIME', '/Users/junkawasaki/.hermes/runtime/mithril')
CLASSPATH = os.environ.get('MITHRIL_CLASSPATH', '')
HELPER = ROOT / 'mithril-bpmn-step.cljk'
PROFILE = ROOT / 'terminal-agent-loop-v2.mith'
ONTOLOGY = ROOT / 'terminal-actions-v2.mith'
RUN_ROOT = Path(os.environ.get('BENCH_RUN_ROOT', '/tmp/terminal-bench-v4'))
MAX_STEPS = int(os.environ.get('BENCH_MAX_STEPS', '500'))
REPEAT_ID = os.environ.get('BENCH_REPEAT_ID', 'development')

class LoopAgent(BaseAgent):
    lane = 'baseline'
    @staticmethod
    def name(): return 'hermes-gpt6-luna-terminal-loop'
    def version(self): return '0.4.0'
    async def setup(self, environment): pass
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls=[]
        self.history=[]
        self.semantic_receipts=0
        self.mith_wall_seconds=0.0
        self.prompt_chars=[]
        self.recalled=None
        self.run_id=f'{self.lane}-{uuid.uuid4().hex[:16]}'
        self.state=RUN_ROOT / 'state' / f'{self.run_id}-state.edn'
        self.state.parent.mkdir(parents=True, exist_ok=True)
        self.usage_dir=RUN_ROOT / 'usage' / self.run_id
        self.usage_dir.mkdir(parents=True, exist_ok=True)

    async def shell(self, environment, command):
        try:
            res=await environment.exec(command=command, timeout_sec=120)
            return {'exit_code':res.return_code,'stdout':(res.stdout or '')[-12000:],'stderr':(res.stderr or '')[-4000:]}
        except RuntimeError as exc:
            if 'timed out' not in str(exc).lower(): raise
            return {'exit_code':124,'stdout':'','stderr':'Command exceeded 120 second execution limit; choose a bounded approach.'}

    async def mith(self, op, action='', outcome='true'):
        started=time.monotonic()
        args=[KBB,'--classpath',CLASSPATH,str(HELPER),str(PROFILE),str(self.state),op,action,outcome]
        p=await asyncio.create_subprocess_exec(*args,cwd=str(MITHRIL),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        out,err=await p.communicate()
        self.mith_wall_seconds+=time.monotonic()-started
        if p.returncode: raise RuntimeError(err.decode()[-2000:] or out.decode()[-2000:])
        data=json.loads(out.decode().strip().splitlines()[-1])
        if 'error' in data: raise RuntimeError(data)
        return data

    async def query(self, instruction, enabled):
        n=len(self.calls)
        transcript=history_view(self.history,self.recalled)
        prompt=("You are a terminal task-solving agent. Return exactly one JSON object and no markdown: "
          '{"action":"inspect|modify|verify|finish|recall","command":"bash command","step":0,"reason":"brief"}. '
          'Commands execute in the isolated benchmark container. Multi-line bash commands and file edits are allowed. '
          'Choose finish only after checking the required artifact or behavior. Do not repeat an unchanged failed command. '
          'History is bounded; use action="recall" with an earlier zero-based step to see its full command and output. '
          'Recall does not execute a bash command.\n'
          f'TASK:\n{instruction}\n\nALLOWED ACTIONS: {enabled}\n'
          f'HISTORY: {transcript}\n'
          'Execute the next action. For finish use command="true".')
        self.prompt_chars.append(len(prompt))
        self.recalled=None
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
                if isinstance(candidate,dict) and candidate.get('action') in ('inspect','modify','verify','finish','recall'):
                    action=candidate
            except json.JSONDecodeError: pass
        if action is None: raise RuntimeError('No valid JSON action returned: '+raw[-1000:])
        if action.get('action') not in ('inspect','modify','verify','finish','recall') or (action.get('action')!='recall' and not isinstance(action.get('command'),str)):
            raise RuntimeError('Invalid action object: '+str(action))
        return action

    async def run(self, instruction, environment, context):
        started=time.time(); max_steps=MAX_STEPS
        enabled_state=None
        try:
            for step in range(max_steps):
                if self.lane=='mithril':
                    if enabled_state is None: enabled_state=await self.mith('enabled')
                    enabled=enabled_state.get('actions',[])
                    if enabled_state.get('completed'): break
                else: enabled=[f'https://mithril.fund/id/action/terminal/{kind}'
                               for kind in ['finish','inspect','modify','verify']]
                action=await self.query(instruction,enabled)
                kind=action['action']; cmd=action.get('command','')
                if kind=='recall':
                    try: self.recalled=recall_step(self.history,action.get('step'))
                    except ValueError as exc: self.recalled={'error':str(exc),'total_steps':len(self.history)}
                    continue
                if kind=='finish':
                    if self.lane=='mithril':
                        action_id='https://mithril.fund/id/action/terminal/finish'
                        semantic=await self.mith('select',action_id,cmd)
                        if semantic.get('semantic',{}).get('entailed'): self.semantic_receipts+=1
                        enabled_state=await self.mith('complete',action_id)
                    self.history.append({'action':kind,'command':cmd,'result':{'exit_code':0,'stdout':'Agent finished','stderr':''}})
                    break
                if self.lane=='mithril':
                    action_id=f'https://mithril.fund/id/action/terminal/{kind}'
                    semantic=await self.mith('select',action_id,cmd)
                    if semantic.get('semantic',{}).get('entailed'): self.semantic_receipts+=1
                result=await self.shell(environment,cmd)
                self.history.append({'action':kind,'command':cmd,'result':result})
                if self.lane=='mithril': enabled_state=await self.mith('complete',action_id,str(result['exit_code']==0).lower())
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
            context.metadata={'lane':self.lane,'run_id':self.run_id,'repeat_id':REPEAT_ID,'step_count':len(self.history),'hermes_calls':len(self.calls),'usage_files':[x['usage_file'] for x in self.calls],'wall_agent_seconds':round(time.time()-started,3),'mithril_wall_seconds':round(self.mith_wall_seconds,3),'prompt_chars_total':sum(self.prompt_chars),'prompt_chars_max':max(self.prompt_chars,default=0),'mithril_ontology_sha256':__import__('hashlib').sha256(ONTOLOGY.read_bytes()).hexdigest() if self.lane=='mithril' else None,'semantic_receipts':self.semantic_receipts}
        finally:
            (RUN_ROOT/'receipts').mkdir(parents=True,exist_ok=True)
            (RUN_ROOT/'receipts'/f'{self.run_id}.json').write_text(json.dumps({'instruction_sha256':__import__('hashlib').sha256(instruction.encode()).hexdigest(),'actions':self.history,'calls':self.calls,'semantic_receipts':self.semantic_receipts},indent=2))

class HermesBaselineAgent(LoopAgent):
    lane='baseline'

class MithrilBpmnAgent(LoopAgent):
    lane='mithril'
    @staticmethod
    def name(): return 'mithril-ontology-bpmn-gpt6-luna-terminal-loop'
