"""reachmini verifier. Runs inside the task container after the agent stops:
  python3 verify.py <expected.json> <pristine-envs-dir>
Runs the agent's solve.py on fresh copies of the target and hidden
environments and compares both output files row for row. Prints
{"assertions": {...}, "passed": n, "total": n}; exit 2 only when it could not measure."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

APP = os.environ.get('REACHMINI_APP', '/app')


def norm(v):
    s = str(v).strip()
    try:
        return str(int(float(s))) if float(s).is_integer() else s
    except ValueError:
        return s


def main():
    if len(sys.argv) != 3:
        print('usage: verify.py <expected.json> <pristine-envs-dir>', file=sys.stderr)
        raise SystemExit(2)
    spec = json.loads(Path(sys.argv[1]).read_text())
    out = {'files_exist': all(Path(APP, f).is_file() for f in ('solve.py', 'requirements.txt'))}
    for env in ('env-t', 'env-h'):
        work = Path(tempfile.mkdtemp())
        shutil.copytree(Path(sys.argv[2]) / env, work / env)
        result_dir = work / 'out'
        run = subprocess.run([sys.executable, f'{APP}/solve.py', str(work / env), str(result_dir)],
                             capture_output=True, text=True, timeout=120)
        out[f'{env}_runs'] = run.returncode == 0
        for name, rows in spec['rows'][env].items():
            path = result_dir / name
            got = None
            if path.is_file():
                got = [[norm(c) for c in line.split('\t')] for line in path.read_text().splitlines() if line.strip()]
            out[f'{env}_{name}'] = got == [[norm(c) for c in row] for row in rows]
    passed = sum(bool(v) for v in out.values())
    print(json.dumps({'assertions': out, 'passed': passed, 'total': len(out)}))


if __name__ == '__main__':
    main()
