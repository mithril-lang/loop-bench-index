"""Bounded, recoverable terminal history shared by both benchmark lanes."""

import hashlib
import json


RECENT_STEPS = 4
INDEX_STEPS = 12


def _clip(value, limit):
    value = str(value or "")
    if len(value) <= limit:
        return value
    return value[: limit // 2] + f"\n...[{len(value) - limit} characters omitted]...\n" + value[-limit // 2 :]


def history_view(history, recalled=None):
    older = history[:-RECENT_STEPS]
    index = []
    for step, item in list(enumerate(older))[-INDEX_STEPS:]:
        result = item.get("result", {})
        output = (result.get("stdout") or "") + (result.get("stderr") or "")
        index.append({"step": step, "action": item.get("action"),
                      "command": _clip(item.get("command"), 160),
                      "exit_code": result.get("exit_code"),
                      "output_sha256": hashlib.sha256(output.encode()).hexdigest()[:16]})
    recent = []
    for step, item in list(enumerate(history))[-RECENT_STEPS:]:
        result = item.get("result", {})
        recent.append({"step": step, "action": item.get("action"),
                       "command": _clip(item.get("command"), 1200),
                       "exit_code": result.get("exit_code"),
                       "stdout": _clip(result.get("stdout"), 1800),
                       "stderr": _clip(result.get("stderr"), 600)})
    view = {"total_steps": len(history), "recent": recent,
            "older_index": index,
            "archived_range": [0, len(older) - 1] if older else None,
            "recall": recalled}
    return json.dumps(view, ensure_ascii=False, separators=(",", ":"))


def recall_step(history, step):
    if type(step) is not int or step < 0 or step >= len(history):
        raise ValueError("recall step must reference an executed action")
    return {"step": step, "action": history[step]["action"],
            "command": history[step]["command"],
            "result": history[step]["result"]}
