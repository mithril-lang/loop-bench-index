"""Independent acceptance review (co-scientist reflection step).

At the first finish attempt a separate, single-turn model call reads only the
task text, the documents the task names, and a listing of file names. It does
not see the agent's code or transcript. It writes pytest acceptance tests for
the behaviour the specification describes. The harness runs them against the
agent's deliverable; failures are returned to the agent before finish is
admitted. The agent may record a test it believes contradicts the
specification in /tmp/review_tests/DISPUTED.txt as `test_name: reason`.
"""

import re

TEST_DIR = '/tmp/review_tests'

PROMPT = ('You are reviewing a task specification. Write pytest acceptance tests that check the behaviour a correct '
          'solution must have, using only the task text and documents below. You cannot see the implementation. '
          'Exercise the deliverable through the interfaces the task names (commands, files, modules, functions). '
          'Prefer edge cases the text states explicitly. Keep it to at most 12 small tests that run in under a minute '
          'in total. Reply with one fenced ```python block containing the whole test file and nothing else.\n')

RUN_SCRIPT = r'''
import json, re, subprocess, sys, pathlib
root = pathlib.Path(sys.argv[1])
disputed = {}
path = root / "DISPUTED.txt"
if path.exists():
    for line in path.read_text(errors="replace").splitlines():
        m = re.match(r"\s*(test_\w+)\s*:\s*(.{10,})", line)
        if m:
            disputed[m.group(1)] = m.group(2)[:200]
r = subprocess.run([sys.executable, "-m", "pytest", str(root), "-q", "-rA", "-p", "no:cacheprovider"],
                   capture_output=True, text=True, timeout=110)
failed = sorted({m.group(1) for m in re.finditer(r"^(?:FAILED|ERROR)\s+\S*::(test_\w+)", r.stdout, re.M)})
passed = sorted({m.group(1) for m in re.finditer(r"^PASSED\s+\S*::(test_\w+)", r.stdout, re.M)})
open_failures = [t for t in failed if t not in disputed]
print(json.dumps({"passed": len(passed), "failed": failed, "disputed": sorted(disputed),
                  "open": open_failures, "collected": "no tests ran" not in r.stdout,
                  "tail": (r.stdout[-2500:] + r.stderr[-500:])}))
'''


def extract_code(reply):
    m = re.search(r'```(?:python)?\s*\n(.*?)```', reply, re.S)
    return m.group(1) if m else None
