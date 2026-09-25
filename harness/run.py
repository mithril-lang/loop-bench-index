"""Run harness lanes sequentially on one Harbor task.

  python3 harness/run.py --task <task-dir> --output <private-dir> --repeat-id r01 \
      --lanes mithril,judge [--max-steps 48]

Refuses (exit 2): an unknown or planned lane, a busy Podman VM, an existing
output directory, an agent exception or missing verifier receipt, zero
executed verifier tests, or a task checksum that changed between lanes.
Lanes run in the order given, never concurrently (the 2 GiB Podman VM lost a
container when two Harbor jobs overlapped; see results/knowledge-ablation-2026-09-25).
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
HARBOR = Path(os.environ.get('HARBOR_BIN', '/Users/junkawasaki/.local/bin/harbor'))
RUNTIME = Path(os.environ.get('MITHRIL_RUNTIME', '/Users/junkawasaki/.hermes/runtime/mithril'))


def lane_registry():
    # Parsed from source so the runner does not need Harbor importable.
    namespace = {}
    source = (HERE / 'mithril_harness' / 'lanes.py').read_text()
    registry = source[source.index('LANES = {'):]
    exec(compile(registry, 'lanes.py', 'exec'), {}, namespace)
    return namespace['LANES'], namespace['PLANNED']


def require_tools():
    """Harbor needs a resolvable `docker` (the Podman shim) and podman-compose."""
    docker = shutil.which('docker')
    if not docker or not os.path.exists(os.path.realpath(docker)):
        raise RuntimeError(f'REFUSE: docker shim missing or dangling: {docker}')
    compose = os.environ.get('PODMAN_COMPOSE_BIN')
    if docker and 'docker-podman-compat' in os.path.realpath(docker) and not (compose and os.path.exists(compose)):
        raise RuntimeError(f'REFUSE: PODMAN_COMPOSE_BIN missing: {compose}')


def require_idle_podman():
    process = subprocess.run(['podman', 'ps', '--format', '{{.Names}}'], capture_output=True, text=True, check=True)
    if process.stdout.strip():
        raise RuntimeError('REFUSE: Podman has an active container: ' + process.stdout.strip())


def verify_trial(jobs_dir):
    results = list(jobs_dir.glob('*/*/result.json'))
    if len(results) != 1:
        raise RuntimeError(f'REFUSE: expected one Harbor trial result in {jobs_dir}, got {len(results)}')
    result = json.loads(results[0].read_text())
    ctrf_path = results[0].parent / 'verifier' / 'ctrf.json'
    if result.get('exception_info') or not ctrf_path.exists():
        detail = (result.get('exception_info') or {}).get('exception_message', '')[-600:]
        raise RuntimeError('REFUSE: agent error or missing verifier receipt: ' + str(results[0]) + ' ' + detail)
    summary = json.loads(ctrf_path.read_text()).get('results', {}).get('summary', {})
    if int(summary.get('tests', 0)) <= 0:
        raise RuntimeError('REFUSE: verifier executed no tests: ' + str(ctrf_path))
    return summary, result.get('task_checksum')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--task', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeat-id', required=True)
    parser.add_argument('--lanes', required=True)
    parser.add_argument('--max-steps', type=int, default=48)
    args = parser.parse_args()
    lanes, planned = lane_registry()
    chosen = [lane for lane in args.lanes.split(',') if lane]
    for lane in chosen:
        if lane in planned:
            raise RuntimeError(f'REFUSE: lane {lane} is planned, not implemented: requires {planned[lane]["requires"]}')
        if lane not in lanes:
            raise RuntimeError(f'REFUSE: unknown lane {lane}')
    if not args.task.is_dir() or args.max_steps < 1 or not chosen:
        raise RuntimeError('REFUSE: task directory, step cap, or lane list invalid')
    require_tools()
    require_idle_podman()
    classpath = os.environ.get('MITHRIL_CLASSPATH') or subprocess.run(
        [os.environ.get('KBB_BIN', 'kbb'), '-Spath'], cwd=RUNTIME, capture_output=True, text=True,
        check=True).stdout.strip()
    if not classpath:
        raise RuntimeError('REFUSE: Mithril classpath unavailable')
    task_checksum = None
    for lane in chosen:
        require_idle_podman()
        run_root = args.output.resolve() / lane
        if run_root.exists():
            raise RuntimeError('REFUSE: output already exists: ' + str(run_root))
        env = os.environ.copy()
        env.update({'PYTHONPATH': str(HERE), 'MITHRIL_CLASSPATH': classpath, 'BENCH_RUN_ROOT': str(run_root),
                    'BENCH_MAX_STEPS': str(args.max_steps), 'BENCH_REPEAT_ID': args.repeat_id,
                    'BENCH_MODEL': os.environ.get('BENCH_MODEL', 'openai/gpt-6-luna')})
        command = [str(HARBOR), 'run', '--path', str(args.task), '--agent-import-path', lanes[lane]['import'],
                   '--model', env['BENCH_MODEL'], '--job-name', f'harness-{lane}-{args.repeat_id}',
                   '--jobs-dir', str(run_root / 'jobs'), '--n-concurrent', '1', '--quiet']
        if subprocess.run(command, env=env).returncode:
            raise RuntimeError(f'REFUSE: Harbor {lane} exited nonzero')
        summary, observed = verify_trial(run_root / 'jobs')
        if not observed or (task_checksum and observed != task_checksum):
            raise RuntimeError('REFUSE: missing or changed task checksum')
        task_checksum = observed
        print(json.dumps({'lane': lane, 'verifier': summary}), flush=True)
    require_idle_podman()


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
