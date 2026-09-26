"""Artificial Analysis-aligned Terminal-Bench agent: Harbor's mini-swe-agent
with the two settings AA states that the adapter does not expose.

AA (methodology page, read 2026-09-25): mini-swe-agent, interactive mini
config and prompts, native bash, no context compaction, at most 500 steps,
upstream task timeouts, pass@1 over three repeats, a task passes only when
every test passes. Harbor 0.1.43 installs the li-boxuan fork (v1.14.4 when
checked) and runs `mini ... -l 0` with the built-in mini.yaml, whose
step_limit is 0 (unlimited).

This agent copies the built-in mini.yaml inside the container, sets
agent.step_limit to AA_STEP_LIMIT (default 500) and adds the OpenRouter
reasoning effort AA_REASONING_EFFORT (default "high") to model_kwargs
(extra_body.reasoning.effort), then runs the same command with -c.
Everything else is Harbor's adapter unchanged.
"""

import os
import shlex

from harbor.agents.installed.mini_swe_agent import MiniSweAgent
from harbor.models.agent.name import AgentName  # noqa: F401  (kept for parity with the parent module)

CONFIG_PATH = '/tmp/aa-mini.yaml'
PATCH = r'''
import os, pathlib, yaml, minisweagent
src = pathlib.Path(minisweagent.__file__).parent / "config" / "mini.yaml"
cfg = yaml.safe_load(src.read_text())
cfg.setdefault("agent", {})["step_limit"] = int(os.environ["AA_STEP_LIMIT"])
kw = cfg.setdefault("model", {}).setdefault("model_kwargs", {}) or {}
kw.setdefault("extra_body", {})["reasoning"] = {"effort": os.environ["AA_REASONING_EFFORT"]}
cfg["model"]["model_kwargs"] = kw
pathlib.Path(os.environ["AA_CONFIG_PATH"]).write_text(yaml.safe_dump(cfg, sort_keys=False))
print("AA_CONFIG", cfg["agent"]["step_limit"], kw["extra_body"])
'''


class MiniSweAgentAA(MiniSweAgent):
    @staticmethod
    def name() -> str:
        return 'mini-swe-agent-aa'

    def create_run_agent_commands(self, instruction):
        commands = super().create_run_agent_commands(instruction)
        step_limit = os.environ.get('AA_STEP_LIMIT', '500')
        effort = os.environ.get('AA_REASONING_EFFORT', 'high')
        env = {'AA_STEP_LIMIT': step_limit, 'AA_REASONING_EFFORT': effort, 'AA_CONFIG_PATH': CONFIG_PATH}
        # run the patch with mini's own tool environment (it has pyyaml and minisweagent)
        prep_command = ('PY=$(ls $HOME/.local/share/uv/tools/mini-swe-agent/bin/python* | head -1); '
                        f'"$PY" -c {shlex.quote(PATCH)}')
        first = commands[0]
        run = first.command.replace('mini -m ', f'mini -c {CONFIG_PATH} -m ', 1)
        if run == first.command:
            raise RuntimeError('REFUSE: could not insert -c into the mini command')
        prep = type(first)(command=prep_command, env=env)
        patched = type(first)(**{**first.model_dump(), 'command': run})
        return [prep, patched] + list(commands[1:])
