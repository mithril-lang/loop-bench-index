"""Requirement extraction and the coverage check for the requirements gate.

extract(instruction) is deterministic: it splits the instruction into
sentences and list items and keeps those that carry a constraint cue (must,
should, exactly, only, never, at least, ...). CHECK_SCRIPT runs inside the
task container: it maps each test function under /tmp/harness_tests to the
requirement ids named in a `covers:` comment or docstring, runs pytest, and
reports which requirements have at least one passing test.
"""

import re

CUES = re.compile(r"\b(must|should|shall|needs? to|required|requires?|ensure|exactly|only|never|always|at least|"
                  r"at most|no more than|do not|don't|cannot|must not|within|every|each)\b", re.I)
MAX_REQUIREMENTS = 30
BOILERPLATE = re.compile(r'\b(cheat|online solutions|hints specific to this task)\b', re.I)
DOC_PATH = re.compile(r'`(/[^`\s]+\.(?:md|txt|rst|ya?ml))`')


def referenced_docs(instruction):
    return sorted(set(DOC_PATH.findall(instruction)))


def extract_all(instruction, docs):
    """Requirements from the instruction first, then from each referenced document (source-labelled)."""
    out = [('task', r) for r in extract(instruction)]
    for path, text in docs.items():
        out += [(path, r) for r in extract(text)]
    seen, unique = set(), []
    for src, r in out:
        if r.lower() not in seen:
            seen.add(r.lower()); unique.append((src, r))
    return unique[:MAX_REQUIREMENTS]


def extract(instruction):
    text = re.sub(r'<!--.*?-->', ' ', instruction, flags=re.S)
    text = re.sub(r'```.*?```', ' ', text, flags=re.S)
    pieces = []
    for block in re.split(r'\n\s*\n|\n\s*[-*]\s+|\n\s*\d+\.\s+', text):
        block = ' '.join(block.split())
        pieces += [s.strip() for s in re.split(r'(?<=[.!?])\s+(?=[A-Z`(])', block) if s.strip()]
    seen, out = set(), []
    for sentence in pieces:
        if len(sentence) < 12 or not CUES.search(sentence) or BOILERPLATE.search(sentence):
            continue
        key = sentence.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(sentence[:400])
    return out[:MAX_REQUIREMENTS]


CHECK_SCRIPT = r'''
import json, re, subprocess, sys, pathlib
root = pathlib.Path("/tmp/harness_tests")
ids = sys.argv[1].split(",") if sys.argv[1] else []
covers = {}
for f in sorted(root.glob("test_*.py")):
    lines = f.read_text(errors="replace").splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"\s*def (test_\w+)\s*\(", line)
        if not m:
            continue
        # only the comment/decorator lines directly above and the docstring directly below this function
        above, j = [], i - 1
        while j >= 0 and lines[j].strip().startswith(("#", "@")):
            above.append(lines[j]); j -= 1
        below, k = [], i + 1
        if k < len(lines) and lines[k].strip().startswith(('"""', chr(39) * 3)):
            quote = lines[k].strip()[:3]
            below.append(lines[k])
            if lines[k].strip().count(quote) < 2:
                k += 1
                while k < len(lines):
                    below.append(lines[k])
                    if quote in lines[k]:
                        break
                    k += 1
        window = "\n".join(above + below)
        tags = set(re.findall(r"R\d+", " ".join(re.findall(r"covers:([^\n\"']*)", window))))
        covers[f"{f.name}::{m.group(1)}"] = sorted(tags)
waived = {}
w = root / "WAIVED.txt"
if w.exists():
    for line in w.read_text(errors="replace").splitlines():
        m = re.match(r"\s*(R\d+)\s*:\s*(.{10,})", line)
        if m:
            waived[m.group(1)] = m.group(2)[:200]
passed = set()
out = ""
if covers:
    r = subprocess.run([sys.executable, "-m", "pytest", str(root), "-q", "-rA", "-p", "no:cacheprovider"],
                       capture_output=True, text=True, timeout=100)
    out = r.stdout[-3000:] + r.stderr[-800:]
    for m in re.finditer(r"^PASSED\s+(\S+)", r.stdout, re.M):
        name = m.group(1)
        passed.add(name.split("/")[-1])
covered = {rid for test, tags in covers.items() if test in passed for rid in tags}
missing = [rid for rid in ids if rid not in covered and rid not in waived]
print(json.dumps({"tests": len(covers), "passing": len([t for t in covers if t in passed]),
                  "covered": sorted(covered), "waived": sorted(waived), "missing": missing,
                  "pytest_tail": out[-1500:]}))
'''
