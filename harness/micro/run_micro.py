"""Fast verification loop: harness lanes on railmini micro tasks, all trials in
parallel, one small container per trial, a hard wall-clock deadline.

  <harbor-venv>/bin/python harness/micro/run_micro.py --lanes mithril,auto-acceptance \
      --seeds 101,102,103 --output <private-dir> [--max-steps 10] [--trial-timeout 420] [--deadline 600]

A trial's status is one of the following. Only `scored` rows enter success
statistics; the others are reported with their counts.
- `scored`: the agent finished and the verifier measured.
- `timeout`: the per-trial cap was hit. The verifier still measured what exists.
- `deadline`: the loop deadline was hit and the trial was cancelled. Not verified.
- `error`: an agent or harness exception. The verifier still measured if it could.
- `unmeasured`: the verifier could not run.

Token accounting is read from the usage files, so interrupted trials are still
counted. With `--transport chat` (default) cache reads are reported
separately from uncached input.
Refuses (exit 2): unknown lanes, a missing image, a missing Mithril
classpath, or non-micro containers running on the Podman VM.
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import types
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
HARNESS = HERE.parent
IMAGE = 'localhost/harness-micro:rdflib-7.1.4'
PREFIX = 'harness-micro-'


def podman(*args, check=True, timeout=120):
    return subprocess.run(['podman', *args], capture_output=True, text=True, check=check, timeout=timeout)


async def apodman(*args, check=True, timeout=120):
    """Never block the event loop: every trial shares it."""
    return await asyncio.to_thread(podman, *args, check=check, timeout=timeout)


class PodmanEnv:
    """The only surface HarnessLoop needs: `exec(command, timeout_sec)`."""

    def __init__(self, name):
        self.name = name

    async def exec(self, command, timeout_sec):
        proc = await asyncio.create_subprocess_exec(
            'podman', 'exec', '-w', '/app', self.name, 'bash', '-c', command,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout_sec)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError(f'Command timed out after {timeout_sec} seconds')
        return types.SimpleNamespace(return_code=proc.returncode, stdout=out.decode(errors='replace'),
                                     stderr=err.decode(errors='replace'))


def usage_totals(usage_dir):
    totals = {'calls': 0, 'failed_attempts': 0, 'uncached_input_tokens': 0, 'cache_read_tokens': 0,
              'output_tokens': 0, 'reasoning_tokens': 0, 'cost_usd': 0.0, 'cost_missing': 0}
    for path in sorted(Path(usage_dir).glob('*.json')):
        try:
            u = json.loads(path.read_text())
        except ValueError:
            totals['cost_missing'] += 1
            continue
        if u.get('partial'):
            totals['failed_attempts'] += 1
        else:
            totals['calls'] += 1
        totals['model_wall_seconds'] = totals.get('model_wall_seconds', 0) + (u.get('wall_seconds') or 0)
        if u.get('partial'):
            totals['failed_attempt_seconds'] = totals.get('failed_attempt_seconds', 0) + (u.get('wall_seconds') or 0)
        totals['uncached_input_tokens'] += (u.get('input_tokens') or 0) + (u.get('cache_write_tokens') or 0)
        totals['cache_read_tokens'] += u.get('cache_read_tokens') or 0
        totals['output_tokens'] += u.get('output_tokens') or 0
        totals['reasoning_tokens'] += u.get('reasoning_tokens') or 0
        cost = u.get('estimated_cost_usd', u.get('cost'))
        if isinstance(cost, (int, float)):
            totals['cost_usd'] += cost
        else:
            totals['cost_missing'] += 1
    prompt = totals['uncached_input_tokens'] + totals['cache_read_tokens']
    totals['cache_hit_ratio'] = round(totals['cache_read_tokens'] / prompt, 4) if prompt else None
    totals['cost_usd'] = round(totals['cost_usd'], 6)
    return totals


async def verify(name, task_dir):
    await apodman('exec', name, 'mkdir', '-p', '/verify/bundles')
    for bundle in (task_dir / 'app' / '2031-q2', task_dir / 'hidden' / '2031-q3'):
        await apodman('cp', str(bundle), f'{name}:/verify/bundles/')  # pristine copies, never the agent's
    await apodman('cp', str(task_dir / 'expected.json'), f'{name}:/verify/expected.json')
    await apodman('cp', str(HERE / 'verify.py'), f'{name}:/verify/verify.py')
    proc = await asyncio.create_subprocess_exec(
        'podman', 'exec', name, 'python3', '/verify/verify.py', '/verify/expected.json', '/verify/bundles',
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await asyncio.wait_for(proc.communicate(), 240)
    if proc.returncode != 0:
        return None, err.decode(errors='replace')[-500:]
    return json.loads(out.decode().strip().splitlines()[-1]), None


async def trial(lane_id, lane_cls, seed, task_dir, args, run_root):
    name = f'{PREFIX}{lane_id}-{seed}-{uuid.uuid4().hex[:6]}'
    row = {'lane': lane_id, 'seed': seed, 'container': name}
    started = time.monotonic()
    await apodman('run', '-d', '--name', name, '--memory', '384m', IMAGE, 'sleep', 'infinity')
    try:
        for bundle in ('2031-q2', '2031-q1'):
            await apodman('cp', str(task_dir / 'app' / bundle), f'{name}:/app/')
        instruction = (task_dir / 'instruction.md').read_text()
        agent = lane_cls(logs_dir=Path(run_root) / 'logs' / name)
        context = types.SimpleNamespace(metadata=None)
        status = 'scored'
        try:
            await asyncio.wait_for(agent.run(instruction, PodmanEnv(name), context), args.trial_timeout)
        except asyncio.TimeoutError:
            status = 'timeout'
        except Exception as exc:  # recorded, never silently scored
            status = 'error'
            row['error'] = f'{type(exc).__name__}: {str(exc)[-400:]}'
        row['agent_wall_seconds'] = round(time.monotonic() - started, 3)
        spans = {'model': agent.model_wall_seconds, 'exec': agent.exec_wall_seconds, 'mithril': agent.mith_wall_seconds}
        row.update({'steps': len(agent.history), 'finished': bool(agent.history) and agent.history[-1]['action'] == 'finish',
                    'mithril_wall_seconds': round(agent.mith_wall_seconds, 3),
                    'spans_seconds': {k: round(v, 3) for k, v in spans.items()},
                    'unaccounted_seconds': round(row['agent_wall_seconds'] - sum(spans.values()), 3)})
        row.update(usage_totals(agent.usage_dir))
        meta = context.metadata or {}
        for key in ('acceptance_runs', 'acceptance_pass', 'differential_submissions'):
            if key in meta:
                row[key] = meta[key]
        result, verify_error = await verify(name, task_dir)
        if result is None:
            row.update({'status': 'unmeasured', 'verify_error': verify_error})
        else:
            row.update({'status': status, 'passed': result['passed'], 'total': result['total'],
                        'success': result['passed'] == result['total'],
                        'failed_assertions': sorted(k for k, v in result['assertions'].items() if not v)})
    finally:
        await apodman('rm', '-f', name, check=False)
        row['trial_wall_seconds'] = round(time.monotonic() - started, 3)
    return row


def summarize(rows, lanes):
    summary = {}
    for lane in lanes:
        mine = [r for r in rows if r['lane'] == lane]
        scored = [r for r in mine if r.get('status') in ('scored', 'timeout') and 'passed' in r]
        cost = sum(r.get('cost_usd', 0) for r in mine)
        prompt = sum(r.get('uncached_input_tokens', 0) + r.get('cache_read_tokens', 0) for r in mine)
        summary[lane] = {
            'trials': len(mine), 'status_counts': {s: sum(r.get('status') == s for r in mine)
                                                   for s in ('scored', 'timeout', 'deadline', 'error', 'unmeasured')},
            'successes': sum(bool(r.get('success')) for r in scored), 'measured': len(scored),
            'mean_assertion_fraction': round(sum(r['passed'] / r['total'] for r in scored) / len(scored), 4) if scored else None,
            'cost_usd': round(cost, 6),
            'cost_per_success_usd': round(cost / max(1, sum(bool(r.get('success')) for r in scored)), 6)
            if any(r.get('success') for r in scored) else None,
            'uncached_input_tokens': sum(r.get('uncached_input_tokens', 0) for r in mine),
            'cache_read_tokens': sum(r.get('cache_read_tokens', 0) for r in mine),
            'output_tokens': sum(r.get('output_tokens', 0) for r in mine),
            'cache_hit_ratio': round(sum(r.get('cache_read_tokens', 0) for r in mine) / prompt, 4) if prompt else None,
            'max_trial_wall_seconds': max((r.get('trial_wall_seconds', 0) for r in mine), default=None)}
    return summary


async def main_async(args, lanes_map, lanes):
    run_root = Path(os.environ['BENCH_RUN_ROOT'])
    tasks_root = Path(args.output) / 'tasks'
    sys.path.insert(0, str(HERE))
    import railmini
    for seed in args.seeds:
        railmini.generate(seed, tasks_root / f's{seed}', args.difficulty)
    loop_started = time.monotonic()
    jobs = {asyncio.ensure_future(trial(lane, lanes_map[lane], seed, tasks_root / f's{seed}', args, run_root)): (lane, seed)
            for lane in lanes for seed in args.seeds}
    done, pending = await asyncio.wait(jobs, timeout=args.deadline)
    rows = []
    for job in done:
        try:
            rows.append(job.result())
        except Exception as exc:
            lane, seed = jobs[job]
            rows.append({'lane': lane, 'seed': seed, 'status': 'error', 'error': f'{type(exc).__name__}: {str(exc)[-400:]}'})
    for job in pending:
        job.cancel()
        lane, seed = jobs[job]
        rows.append({'lane': lane, 'seed': seed, 'status': 'deadline'})
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
        for line in podman('ps', '-a', '--format', '{{.Names}}', check=False).stdout.split():
            if line.startswith(PREFIX):
                podman('rm', '-f', line, check=False)
    loop_wall = round(time.monotonic() - loop_started, 3)
    rows.sort(key=lambda r: (r['lane'], r['seed']))
    report = {'loop_wall_seconds': loop_wall, 'deadline_seconds': args.deadline, 'transport': os.environ['BENCH_TRANSPORT'],
              'model': os.environ.get('BENCH_MODEL', 'openai/gpt-6-luna'), 'reasoning': os.environ.get('BENCH_REASONING', 'medium'),
              'max_steps': args.max_steps, 'difficulty': args.difficulty, 'mithril_resident': not args.mithril_cli, 'trial_timeout_seconds': args.trial_timeout, 'seeds': args.seeds,
              'summary': summarize(rows, lanes), 'rows': rows}
    Path(args.output, 'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({'loop_wall_seconds': loop_wall, 'summary': report['summary']}, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--lanes', required=True)
    parser.add_argument('--seeds', required=True, type=lambda s: [int(x) for x in s.split(',') if x])
    parser.add_argument('--output', required=True)
    parser.add_argument('--max-steps', type=int, default=10)
    parser.add_argument('--trial-timeout', type=int, default=420)
    parser.add_argument('--deadline', type=int, default=600)
    parser.add_argument('--transport', default='chat', choices=('chat', 'hermes'))
    parser.add_argument('--difficulty', type=int, default=3, choices=(1, 2, 3))
    parser.add_argument('--mithril-cli', action='store_true', help='spawn kbb per Mithril call instead of the resident server')
    args = parser.parse_args()
    if Path(args.output).exists():
        raise RuntimeError(f'REFUSE: output exists: {args.output}')
    if podman('image', 'exists', IMAGE, check=False).returncode != 0:
        raise RuntimeError(f'REFUSE: image {IMAGE} missing; build it with: podman build -t {IMAGE} {HERE}')
    busy = [n for n in podman('ps', '--format', '{{.Names}}').stdout.split() if not n.startswith(PREFIX)]
    if busy:
        raise RuntimeError('REFUSE: other containers are running on the Podman VM: ' + ' '.join(busy))
    classpath = os.environ.get('MITHRIL_CLASSPATH') or subprocess.run(
        [os.environ.get('KBB_BIN', 'kbb'), '-Spath'], capture_output=True, text=True, check=True,
        cwd=os.environ.get('MITHRIL_RUNTIME', '/Users/junkawasaki/.hermes/runtime/mithril')).stdout.strip()
    if not classpath:
        raise RuntimeError('REFUSE: Mithril classpath unavailable')
    Path(args.output).mkdir(parents=True)
    os.environ.update({'MITHRIL_CLASSPATH': classpath, 'BENCH_MAX_STEPS': str(args.max_steps),
                       'BENCH_RUN_ROOT': str(Path(args.output).resolve() / 'run'), 'BENCH_TRANSPORT': args.transport,
                       'BENCH_REPEAT_ID': 'micro-' + Path(args.output).name,
                       'BENCH_MITHRIL_RESIDENT': '0' if args.mithril_cli else '1'})
    sys.path.insert(0, str(HARNESS))
    from mithril_harness import lanes as lane_module  # env must be set before this import
    registry = {lane_id: getattr(lane_module, spec['import'].split(':')[1]) for lane_id, spec in lane_module.LANES.items()}
    lanes = [lane for lane in args.lanes.split(',') if lane]
    unknown = [lane for lane in lanes if lane not in registry]
    if unknown:
        raise RuntimeError('REFUSE: unknown lanes: ' + ','.join(unknown))
    asyncio.run(main_async(args, registry, lanes))


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
