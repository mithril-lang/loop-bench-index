"""Harbor development control: install the fixed candidate, then run verifier.

This is solution injection, not a Luna/Mithril agent benchmark run.
"""

import base64
import shlex
from pathlib import Path

from harbor.agents.base import BaseAgent

ARTIFACTS = Path(__file__).parent / 'candidate'


class CandidateControl(BaseAgent):
    @staticmethod
    def name():
        return 'railway-fixed-candidate-development-control'

    def version(self):
        return '1'

    async def setup(self, environment):
        pass

    async def run(self, instruction, environment, context):
        for name in ('pipeline.py', 'cross_border_operational_points.rq',
                     'qualified_cross_border_points.rq', 'requirements.txt'):
            data = base64.b64encode((ARTIFACTS / name).read_bytes()).decode()
            command = f'printf %s {shlex.quote(data)} | base64 -d > /app/{name}'
            result = await environment.exec(command=command, timeout_sec=120)
            if result.return_code != 0:
                raise RuntimeError(f'candidate install failed: {name}: {result.stderr}')
        result = await environment.exec(command='python3 /app/pipeline.py /app/2024-q2', timeout_sec=180)
        if result.return_code != 0:
            raise RuntimeError(f'candidate pipeline failed: {result.stderr}')
