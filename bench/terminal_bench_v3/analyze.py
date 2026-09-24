"""Analyze public-safe Terminal-Bench rows without promoting sparse probes.

Input is JSON emitted by summarize.py. Trial-level rows are never silently
discarded; unmeasured rows count toward coverage but not success denominators.
"""

import argparse
import json
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path


def percentile(values, q):
    values = sorted(values)
    return values[round((len(values) - 1) * q)]


def clustered_interval(rows, lane, seed=260924, draws=4000):
    by_task = defaultdict(list)
    for row in rows:
        if row["lane"] == lane and row["status"] == "scored":
            by_task[row["task_id"]].append(row)
    # A one-task pilot cannot estimate between-task variation. Five clusters
    # are a minimum for displaying an exploratory interval, not qualification.
    if len(by_task) < 5:
        return None
    rng = random.Random(seed)
    tasks = sorted(by_task)
    rates = []
    for _ in range(draws):
        sample = [rng.choice(tasks) for _ in tasks]
        rates.append(statistics.mean(
            sum(r["reward"] == 1.0 for r in by_task[task]) / len(by_task[task])
            for task in sample
        ))
    return [percentile(rates, 0.025), percentile(rates, 0.975)]


def analyze(rows):
    if not rows:
        raise ValueError("empty row set cannot establish coverage")
    allowed = {"baseline", "mithril", "oracle-control"}
    if any(r.get("lane") not in allowed for r in rows):
        raise ValueError("unknown lane or missing agent receipt")
    totals = Counter(r["status"] for r in rows)
    controls = [r for r in rows if r["lane"] == "oracle-control"]
    scored = [r for r in rows if r["status"] == "scored"]
    if not scored:
        raise ValueError("no verifier-executed model trials")
    control_passes = {(r["task_id"], r["task_checksum"])
                      for r in controls if r["status"] == "control-pass"}
    if any((r["task_id"], r["task_checksum"]) not in control_passes for r in scored):
        raise ValueError("scored model trial lacks an oracle-positive verifier control")
    checksums = defaultdict(set)
    for row in scored:
        checksums[row["task_id"]].add(row["task_checksum"])
    if any(len(values) != 1 for values in checksums.values()):
        raise ValueError("task version changed within cohort")
    by_lane = {}
    for lane in ("baseline", "mithril"):
        subset = [r for r in scored if r["lane"] == lane]
        successes = sum(r["reward"] == 1.0 for r in subset)
        grouped = defaultdict(list)
        for row in subset:
            grouped[row["task_id"]].append(row)
        task_rates = [sum(r["reward"] == 1.0 for r in group) / len(group)
                      for group in grouped.values()]
        by_lane[lane] = {
            "tasks": len(grouped),
            "trials": len(subset), "successes": successes,
            "pass_at_1": statistics.mean(task_rates) if task_rates else None,
            "three_scored_repeats_per_task": bool(grouped) and all(len(group) == 3 for group in grouped.values()),
            "task_clustered_95pct_interval": clustered_interval(scored, lane),
            "mean_agent_wall_seconds": statistics.mean(r["agent_wall_seconds"] for r in subset) if subset else None,
            "mean_total_tokens": statistics.mean(r["input_tokens"] + r["output_tokens"] for r in subset) if subset else None,
            "mean_estimated_cost_usd": statistics.mean(r["estimated_cost_usd"] for r in subset) if subset else None,
        }
    pairs = defaultdict(dict)
    for row in scored:
        key = (row["task_id"], row["task_checksum"], row["repeat_id"])
        if row["lane"] in pairs[key]:
            raise ValueError(f"duplicate trial for {key} / {row['lane']}")
        pairs[key][row["lane"]] = row
    complete = [v for v in pairs.values() if set(v) == {"baseline", "mithril"}]
    both_pass = [v for v in complete if v["baseline"]["reward"] == v["mithril"]["reward"] == 1.0]
    # A ratio across a single successful task is descriptive only. Require
    # five task clusters and ten matched successes before reporting an index.
    qualified = len(both_pass) >= 10 and len({v["baseline"]["task_id"] for v in both_pass}) >= 5
    def ratio(field):
        return (sum(v["mithril"][field] for v in both_pass) /
                sum(v["baseline"][field] for v in both_pass)) if qualified else None
    return {
        "coverage": dict(totals),
        "oracle_controls": {"passed": sum(r["status"] == "control-pass" for r in controls),
                            "failed": sum(r["status"] == "control-fail" for r in controls)},
        "lanes": by_lane,
        "paired_trials": len(complete),
        "both_pass_pairs": len(both_pass),
        "success_qualified_index": {
            "eligible": qualified,
            "minimum": "10 paired successes across 5 distinct tasks",
            "tokens_mithril_over_baseline": None if not qualified else
                sum(v["mithril"]["input_tokens"] + v["mithril"]["output_tokens"] for v in both_pass) /
                sum(v["baseline"]["input_tokens"] + v["baseline"]["output_tokens"] for v in both_pass),
            "cost_mithril_over_baseline": ratio("estimated_cost_usd"),
            "wall_mithril_over_baseline": ratio("agent_wall_seconds"),
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("rows", type=Path)
    args = parser.parse_args()
    try:
        report = analyze(json.loads(args.rows.read_text()))
    except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError) as exc:
        raise SystemExit(f"REFUSE: {exc}") from exc
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
