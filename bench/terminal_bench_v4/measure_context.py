"""Compare v3 and v4 history payload sizes without exporting private contents."""

import json
import sys
from pathlib import Path

from context import history_view


def main(path):
    actions = json.loads(Path(path).read_text())["actions"]
    old = [len(json.dumps(actions[:n], ensure_ascii=False)) for n in range(len(actions))]
    new = [len(history_view(actions[:n])) for n in range(len(actions))]
    if not actions:
        raise SystemExit("REFUSE: no executed actions")
    print(json.dumps({"actions": len(actions),
                      "v3_history_chars_total": sum(old),
                      "v4_history_chars_total": sum(new),
                      "history_chars_reduction_pct": round(100 * (1 - sum(new) / sum(old)), 2) if sum(old) else None,
                      "v3_history_chars_max": max(old),
                      "v4_history_chars_max": max(new)}, sort_keys=True))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: measure_context.py receipt.json")
    main(sys.argv[1])
