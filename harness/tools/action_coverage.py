"""Classify logged agent actions against the typed action library.

  python3 harness/tools/action_coverage.py <receipt.json>... [--details private.jsonl]

For each model-chosen action, the command is split into segments, and each
segment is mapped to a library operation and tier (pure < authored < llm).
The action's tier is the worst tier among its segments. Only `pure` actions
could be chosen and generated without an LLM call.

Two classifiers bound the answer:
- `strict` recognizes shell-level operations only. Every Python heredoc counts
  as an authored probe. This is a lower bound on pure coverage.
- `signature` also maps Python heredocs by what they do (run .rq files, check
  preservation, run the entrypoint). It is an upper bound: a script that
  matches `acceptance-check` may carry bespoke assertions a library call would
  not.

Harness-internal entries (gates, controller refusals) are counted separately
and are not model actions. The printed report is aggregate only. `--details`
writes per-action rows, which contain command text, to a private path.
"""

import argparse
import collections
import json
import re
import sys

TIER_RANK = {'pure': 0, 'authored': 1, 'llm': 2}
HARNESS_INTERNAL = {'critical review gate', 'required artifact check', 'finish gate', 'inspection budget'}
HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
NOISE = re.compile(r'^(set -[eux]+|cd \S+|echo\b.*|printf\b.*|true|:|done|fi|then|else|do|\{.*|\}.*|esac|continue|break|case .*|\*\).*|\[ .*)$')
ENV_CHECK = re.compile(r"""^python3? -c ['"]import [\w.]+[;\n]\s*print\([^)]*__version__[^)]*\)['"]""")
INLINE_SPARQL = re.compile(r"""(['"]{1,3})\s*(PREFIX|SELECT|ASK|CONSTRUCT)\b""", re.I)


def join_open_quotes(lines):
    """Join physical lines while a single quote is open (python -c '...', bash -c '...')."""
    out, buf = [], None
    for line in lines:
        buf = line if buf is None else buf + '\n' + line
        if buf.count("'") % 2 == 0 or HEREDOC.search(buf):
            out.append(buf); buf = None
    if buf is not None:
        out.append(buf)
    return out


def split_top(line):
    """Split on ; && || outside single/double quotes."""
    parts, buf, quote, i = [], [], None, 0
    while i < len(line):
        ch = line[i]
        if quote:
            buf.append(ch)
            if ch == quote: quote = None
        elif ch in "'\"":
            quote = ch; buf.append(ch)
        elif ch == ';' or line.startswith('&&', i) or line.startswith('||', i):
            parts.append(''.join(buf)); buf = []
            i += 1 if ch == ';' else 2
            continue
        else:
            buf.append(ch)
        i += 1
    parts.append(''.join(buf))
    return [p.strip() for p in parts if p.strip()]


def segments(command):
    """Yield (text, is_heredoc_block). Heredoc bodies and quoted -c bodies stay whole."""
    wrapper = re.match(r"^\s*bash -l?c '(.*)'\s*(2>&1)?\s*$", command, re.S)
    if wrapper:
        yield from segments(wrapper.group(1))
        return
    lines = command.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.count("'") % 2 and not HEREDOC.search(line):
            joined = join_open_quotes(lines[i:])[0]
            for part in split_top(joined):
                yield part, False
            i += joined.count('\n') + 1
            continue
        m = HEREDOC.search(line)
        if m:
            end = m.group(2)
            j = i + 1
            while j < len(lines) and lines[j].strip() != end:
                j += 1
            yield '\n'.join(lines[i:j + 1]), True
            i = j + 1
            continue
        for part in split_top(line):
            yield part, False
        i += 1


def classify_shell(seg):
    s = re.sub(r'^\s*(?:for .*?; do|do|then)\s+', '', seg).strip()
    if re.match(r'^(echo|printf)\b.*[^2&]>\s*[/\w$"]', s) and not re.search(r'>\s*/dev/(null|stderr)', s):
        return ('write-file', 'llm')
    if not s or NOISE.match(s):
        return None
    head = s.split()[0]
    if re.match(r'^(cat|tee)\b.*>', s) or re.match(r'^(sed|perl)\s+-i', s):
        return ('write-file' if head in ('cat', 'tee') else 'patch-file', 'llm')
    if re.match(r'^:\s*>', s):
        return ('write-file', 'llm')
    if re.match(r'^\w+=\$\?$', s):
        return None
    if head in ('chmod', 'mktemp', 'trap', 'cp', 'mkdir', 'rm') or re.match(r'^\w+=\$\(mktemp', s):
        return ('workspace-setup', 'pure')
    if head in ('find', 'ls', 'tree', 'test', 'stat', 'du'):
        return ('list-files', 'pure')
    if head in ('sed', 'cat', 'head', 'tail', 'wc', 'nl', 'sort', 'uniq', 'cut', 'diff', 'sha256sum', 'file'):
        return ('show-file', 'pure')
    if head in ('grep', 'rg'):
        return ('grep-terms', 'pure')
    if re.match(r'^python3?\s+\S+\.py(\s+\S+)*$', s):
        return ('run-entrypoint', 'pure')
    if re.match(r'^(pip3?|uv|python3? -m pip)\b.*install', s):
        return ('install-requirements', 'pure')
    if ENV_CHECK.match(s) or re.match(r'^python3? -m py_compile\b', s):
        return ('env-check', 'pure')
    m = re.match(r"^bash -l?c '(.*)'", s, re.S)
    if m:
        inner = [classify_shell(x) for x, blk in segments(m.group(1)) if not blk]
        inner = [x for x in inner if x]
        return max(inner, key=lambda o: TIER_RANK[o[1]]) if inner else None
    if head in ('for', 'while', 'if'):
        return None  # loop header; its body segments are classified
    return ('shell-other', 'authored')


def classify_heredoc(block, action_kind, mode):
    first = block.splitlines()[0]
    body = block
    if re.match(r'^\s*(cat|tee)\b.*>', first):
        return ('write-file', 'llm')
    writes = re.search(r"write_text\(|open\([^)]*['\"][wa]['\"]", body)
    if writes and (action_kind == 'modify' or re.search(r'/app/[\w./-]+\.(py|rq|txt)', body) and 'replace(' in body):
        return ('patch-file', 'llm')
    if mode == 'strict':
        return ('python-probe', 'authored')
    runs_rq = bool(re.search(r'\.rq', body)) and '.query(' in body
    inline = bool(INLINE_SPARQL.search(body))
    preserve = bool(re.search(r'isomorphic|to_canonical_graph|to_isomorphic|graph_diff', body))
    entry = bool(re.search(r'pipeline\.py', body))
    if runs_rq and not inline and (preserve or entry):
        return ('acceptance-check', 'pure')
    if runs_rq and not inline:
        return ('run-queries', 'pure')
    if preserve and not inline and not runs_rq:
        return ('preservation-check', 'pure')
    if inline:
        return ('sparql-probe', 'authored')
    return ('python-probe', 'authored')


def classify_action(action, mode):
    command = action.get('command', '')
    if action.get('action') == 'controller' or command in HARNESS_INTERNAL or command.startswith('# mithril-differential'):
        return 'internal', []
    if command == 'differential':
        return 'authored', [('differential', 'authored')]
    ops = []
    for seg, is_block in segments(command):
        op = classify_heredoc(seg, action['action'], mode) if is_block else classify_shell(seg)
        if op:
            ops.append(op)
    if not ops:
        return 'pure', [('show-file', 'pure')]  # only headers/echo: harmless, generatable
    return max((t for _, t in ops), key=lambda t: TIER_RANK[t]), ops


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('receipts', nargs='+')
    parser.add_argument('--details')
    args = parser.parse_args()
    report = {'receipts': 0, 'actions_total': 0, 'internal_entries': 0}
    details = []
    for mode in ('strict', 'signature'):
        tiers = collections.Counter(); by_kind = collections.Counter(); ops = collections.Counter()
        model_actions = 0; internal = 0; receipts = 0
        for path in args.receipts:
            try:
                actions = json.load(open(path))['actions']
            except (OSError, ValueError, KeyError) as exc:
                print(f'UNREADABLE\t{path}\t{exc}', file=sys.stderr)
                raise SystemExit(2)
            receipts += 1
            for index, action in enumerate(actions):
                if action.get('action') == 'finish':
                    continue
                tier, found = classify_action(action, mode)
                if tier == 'internal':
                    internal += 1
                    continue
                model_actions += 1
                tiers[tier] += 1
                by_kind[(action['action'], tier)] += 1
                for op, _ in found:
                    ops[op] += 1
                if mode == 'signature' and args.details:
                    details.append({'receipt': path, 'index': index, 'kind': action['action'], 'tier': tier,
                                    'ops': [op for op, _ in found],
                                    'strict_tier': classify_action(action, 'strict')[0],
                                    'command': action.get('command', '')[:1500]})
        report.update({'receipts': receipts, 'actions_total': model_actions + internal, 'internal_entries': internal})
        report[mode] = {'model_actions': model_actions, 'tiers': dict(tiers),
                        'pure_fraction': round(tiers['pure'] / model_actions, 4) if model_actions else None,
                        'by_kind': {f'{k}/{t}': n for (k, t), n in sorted(by_kind.items())},
                        'ops': dict(sorted(ops.items()))}
    if report['signature']['model_actions'] == 0:
        print('SCANNED\t0 model actions: refusing an empty coverage report', file=sys.stderr)
        raise SystemExit(2)
    if args.details:
        with open(args.details, 'w') as out:
            for row in details:
                out.write(json.dumps(row, ensure_ascii=False) + '\n')
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
