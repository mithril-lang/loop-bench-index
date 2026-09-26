"""Make local copies of Terminal-Bench tasks runnable under Harbor 0.1.43 + Podman.

Harbor 0.1.43 ignores `[verifier] environment_mode = "separate"`, so the
verifier runs in the agent's container, which lacks the verifier's Python
dependencies. For each task this copies the task directory and appends one
`pip install` line with the exact packages pinned in `tests/Dockerfile` to
`environment/Dockerfile`. Deviation from upstream: the agent can import
pytest and those packages. Only use tasks whose oracle then scores 1.0.

  python3 harness/tb/patch_tasks.py <terminal-bench-checkout> <out-dir> <task>...
"""

import re
import shutil
import sys
from pathlib import Path

PKG = re.compile(r'(?:uv pip install --system|pip install)\s+(.*)')


def verifier_packages(dockerfile_text):
    text = dockerfile_text.replace('\\\n', ' ')
    packages = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith('RUN'):
            continue
        for chunk in line.split('&&'):
            m = PKG.search(chunk)
            if m:
                packages += [p for p in m.group(1).split() if not p.startswith('-')]
    return packages


def patch(src_root, out_root, task):
    src, dst = Path(src_root) / 'tasks' / task, Path(out_root) / task
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    packages = verifier_packages((src / 'tests' / 'Dockerfile').read_text())
    if not packages:
        raise SystemExit(f'REFUSE: no verifier packages found for {task}')
    with open(dst / 'environment' / 'Dockerfile', 'a') as f:
        f.write('\n# local Podman adapter: Harbor 0.1.43 ignores environment_mode="separate"; '
                'verifier dependencies from tests/Dockerfile (versions unchanged):\n'
                f'RUN pip install --no-cache-dir {" ".join(packages)} && mkdir -p /logs/verifier\n')
    return packages


if __name__ == '__main__':
    if len(sys.argv) < 4:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    for name in sys.argv[3:]:
        print(name, patch(sys.argv[1], sys.argv[2], name))
