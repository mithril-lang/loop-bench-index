"""Export public-safe metrics from local Harbor trial results.

Never copy raw Harbor results, task instructions, verifier output, or agent
receipts to a public benchmark repository.
"""

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path


def seconds(span):
    if not span or not span.get("started_at") or not span.get("finished_at"):
        return None
    start = datetime.fromisoformat(span["started_at"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(span["finished_at"].replace("Z", "+00:00"))
    return round((end - start).total_seconds(), 3)


def trial_row(path):
    trial = json.loads(path.read_text())
    verifier = trial.get("verifier_result") or {}
    rewards = verifier.get("rewards") or {}
    agent = trial.get("agent_result") or {}
    meta = agent.get("metadata") or {}
    error = trial.get("exception_info")
    oracle = (trial.get("agent_info") or {}).get("name") == "oracle"
    usages = []
    for usage_file in meta.get("usage_files", []):
        try:
            usages.append(json.loads(Path(usage_file).read_text()))
        except (ValueError, OSError):
            pass
    jev_usages = []
    for usage_file in meta.get("jev_usage_files", []):
        try:
            jev_usages.append(json.loads(Path(usage_file).read_text()))
        except (ValueError, OSError):
            pass
    usage_complete = len(usages) == meta.get("hermes_calls", -1) and len(usages) > 0
    jev_usage_complete = len(jev_usages) == meta.get("jev_calls", 0)
    verifier_stdout = path.parent / "verifier" / "test-stdout.txt"
    output = verifier_stdout.read_text(errors="replace") if verifier_stdout.exists() else ""
    infrastructure_failure = any(marker in output for marker in (
        "No module named pytest", "pytest: command not found",
        "ModuleNotFoundError: No module named 'pytest'",
    ))
    ctrf_path = path.parent / "verifier" / "ctrf.json"
    executed_tests = 0
    if ctrf_path.exists():
        try:
            ctrf = json.loads(ctrf_path.read_text())
            executed_tests = int(ctrf.get("results", {}).get("summary", {}).get("tests", 0))
        except (ValueError, OSError, TypeError):
            pass
    # Other verifier formats need an explicit per-task audit before inclusion.
    measured = not error and rewards and usage_complete and jev_usage_complete and not infrastructure_failure and executed_tests > 0
    control_valid = oracle and not error and rewards and not infrastructure_failure and executed_tests > 0
    return {
        "task_id": trial.get("task_name"),
        "task_checksum": trial.get("task_checksum"),
        "trial_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "lane": "oracle-control" if oracle else meta.get("lane"),
        "repeat_id": meta.get("repeat_id", "development"),
        "status": ("control-pass" if rewards.get("reward") == 1.0 else "control-fail") if control_valid else ("scored" if measured else "unmeasured"),
        "reward": rewards.get("reward") if measured or control_valid else None,
        "model_calls": meta.get("hermes_calls"),
        "jev_calls": meta.get("jev_calls", 0),
        "jev_input_tokens": sum(u.get("input_tokens", 0) for u in jev_usages) if jev_usage_complete else None,
        "jev_output_tokens": sum(u.get("output_tokens", 0) for u in jev_usages) if jev_usage_complete else None,
        "jev_cost_usd": sum(u.get("cost", 0) for u in jev_usages) if jev_usage_complete else None,
        "provider_api_calls": sum(u.get("api_calls", 0) for u in usages) if usage_complete else None,
        "steps": meta.get("step_count"),
        "semantic_receipts": meta.get("semantic_receipts"),
        "verifier_tests_executed": executed_tests,
        "input_tokens": agent.get("n_input_tokens") if measured else None,
        "output_tokens": agent.get("n_output_tokens") if measured else None,
        "reasoning_tokens": sum(u.get("reasoning_tokens", 0) or 0 for u in usages) if measured else None,
        "cache_tokens": agent.get("n_cache_tokens") if measured else None,
        "estimated_cost_usd": agent.get("cost_usd") if measured else None,
        "agent_wall_seconds": seconds(trial.get("agent_execution")) if measured else None,
        "failure_class": "verifier-dependency-missing" if infrastructure_failure else ((error or {}).get("exception_type") if error else (None if measured or control_valid else ("usage-receipt-missing" if not usage_complete and not oracle else "verifier-evidence-missing"))),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("jobs_dir", type=Path)
    args = parser.parse_args()
    paths = sorted(args.jobs_dir.glob("*/*/result.json"))
    if not paths:
        raise SystemExit("No Harbor trial results; refusing an empty report")
    print(json.dumps([trial_row(path) for path in paths], indent=2))


if __name__ == "__main__":
    main()
