"""Export public-safe action and prompt-replay metrics from a paired Harbor run."""

import argparse
import collections
import hashlib
import json
from pathlib import Path


def one(paths, label):
    files = list(paths)
    if len(files) != 1:
        raise ValueError(f"REFUSE: expected one {label}, found {len(files)}")
    return files[0]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def row(root, lane):
    lane_root = root / lane
    receipt_path = one(lane_root.glob("receipts/*.json"), f"{lane} action receipt")
    result_path = one(lane_root.glob("jobs/*/*/result.json"), f"{lane} Harbor result")
    receipt = json.loads(receipt_path.read_text())
    result = json.loads(result_path.read_text())
    actions = receipt.get("actions")
    meta = (result.get("agent_result") or {}).get("metadata") or {}
    if not actions or not meta or result.get("exception_info") or not result.get("verifier_result"):
        raise ValueError(f"REFUSE: {lane} has no scored action/usage/verifier evidence")
    kinds = [action["action"] for action in actions]
    streak = 0
    longest = 0
    for kind in kinds:
        streak = streak + 1 if kind == "inspect" else 0
        longest = max(longest, streak)
    usage_files = meta.get("usage_files") or []
    if len(usage_files) != meta.get("hermes_calls"):
        raise ValueError(f"REFUSE: {lane} completed usage receipt count mismatch")
    usages = [json.loads(Path(path).read_text()) for path in usage_files]
    if any(not usage.get("completed") for usage in usages):
        raise ValueError(f"REFUSE: {lane} completed usage list contains an incomplete call")
    return {
        "lane": lane,
        "task_checksum": result.get("task_checksum"),
        "trial_result_sha256": sha256(result_path),
        "action_receipt_sha256": sha256(receipt_path),
        "steps": len(actions),
        "action_counts": dict(collections.Counter(kinds)),
        "first_modify_step": next((i for i, kind in enumerate(kinds, 1) if kind == "modify"), None),
        "longest_inspect_streak": longest,
        "replayed_history_chars": sum(len(json.dumps(actions[:i], ensure_ascii=False))
                                      for i in range(len(actions))),
        "prompt_chars_total": meta.get("prompt_chars_total"),
        "completed_model_calls": len(usages),
        "failed_provider_attempts": len(meta.get("failed_usage_files") or []),
        "known_total_tokens": sum(usage.get("total_tokens") or 0 for usage in usages),
        "known_estimated_cost_usd": sum(usage.get("estimated_cost_usd") or 0 for usage in usages),
        "action_sequence": kinds,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    rows = [row(args.root, lane) for lane in ("control", "knowledge")]
    if not rows[0]["task_checksum"] or rows[0]["task_checksum"] != rows[1]["task_checksum"]:
        raise ValueError("REFUSE: paired task checksum missing or mismatched")
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
