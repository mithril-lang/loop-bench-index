"""Run the no-knowledge and precompiled-knowledge Harbor lanes sequentially.

Refuses a busy Podman VM or missing verifier evidence. Raw Harbor jobs stay
under the caller's private output directory.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HARBOR = Path(os.environ.get("HARBOR_BIN", "/Users/junkawasaki/.local/bin/harbor"))
RUNTIME = Path(os.environ.get("MITHRIL_RUNTIME", "/Users/junkawasaki/.hermes/runtime/mithril"))


def require_idle_podman():
    process = subprocess.run(["podman", "ps", "--format", "{{.Names}}"],
                             capture_output=True, text=True, check=True)
    if process.stdout.strip():
        raise RuntimeError("REFUSE: Podman has an active container: " + process.stdout.strip())


def verify_trial(jobs_dir):
    results = list(jobs_dir.glob("*/*/result.json"))
    if len(results) != 1:
        raise RuntimeError(f"REFUSE: expected one Harbor trial result in {jobs_dir}, got {len(results)}")
    result = json.loads(results[0].read_text())
    ctrf_path = results[0].parent / "verifier" / "ctrf.json"
    if result.get("exception_info") or not ctrf_path.exists():
        raise RuntimeError("REFUSE: agent error or missing verifier receipt: " + str(results[0]))
    summary = json.loads(ctrf_path.read_text()).get("results", {}).get("summary", {})
    if int(summary.get("tests", 0)) <= 0:
        raise RuntimeError("REFUSE: verifier executed no tests: " + str(ctrf_path))
    return summary, result.get("task_checksum")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeat-id", required=True)
    parser.add_argument("--max-steps", type=int, default=48)
    args = parser.parse_args()
    if not args.task.is_dir() or args.max_steps < 1:
        raise SystemExit("REFUSE: task directory or step cap invalid")
    require_idle_podman()
    classpath = os.environ.get("MITHRIL_CLASSPATH")
    if not classpath:
        classpath = subprocess.run([os.environ.get("KBB_BIN", "kbb"), "-Spath"],
                                   cwd=RUNTIME, capture_output=True, text=True,
                                   check=True).stdout.strip()
    if not classpath:
        raise SystemExit("REFUSE: Mithril classpath unavailable")
    lanes = (("control", "knowledge_agent:MithrilDomainPrefillAgent"),
             ("knowledge", "knowledge_agent:MithrilKnowledgeAgent"))
    task_checksum = None
    for lane, agent in lanes:
        require_idle_podman()
        run_root = args.output.resolve() / lane
        jobs_dir = run_root / "jobs"
        if run_root.exists():
            raise RuntimeError("REFUSE: output already exists: " + str(run_root))
        env = os.environ.copy()
        env.update({"PYTHONPATH": str(HERE), "MITHRIL_CLASSPATH": classpath,
                    "BENCH_RUN_ROOT": str(run_root), "BENCH_MAX_STEPS": str(args.max_steps),
                    "BENCH_REPEAT_ID": args.repeat_id,
                    "BENCH_MODEL": os.environ.get("BENCH_MODEL", "openai/gpt-6-luna")})
        command = [str(HARBOR), "run", "--path", str(args.task),
                   "--agent-import-path", agent, "--model", env["BENCH_MODEL"],
                   "--job-name", f"railway-{lane}-{args.repeat_id}",
                   "--jobs-dir", str(jobs_dir), "--n-concurrent", "1", "--quiet"]
        process = subprocess.run(command, env=env)
        if process.returncode:
            raise RuntimeError(f"REFUSE: Harbor {lane} exited {process.returncode}")
        summary, observed_checksum = verify_trial(jobs_dir)
        if not observed_checksum or (task_checksum and observed_checksum != task_checksum):
            raise RuntimeError("REFUSE: missing or changed task checksum")
        task_checksum = observed_checksum
        print(json.dumps({"lane": lane, "verifier": summary}), flush=True)
    require_idle_podman()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
