# Bounded-history Mithril terminal loop (v4)

**Experimental and rejected as an efficiency improvement.** The one-task
development pair in [the v4 report](../../results/terminal-bench-4.0-gpt6-luna-mithril-v4/report.md)
failed to create the required artifact in both lanes. Keep this runner for
reproducing the failure and developing a typed state projection; do not make
it the production default.

Both lanes use GPT-6 Luna medium through the same Hermes/OpenRouter route and
the same JSON bash-action interface. The v4 prompt carries the task in full,
the last four actions with bounded outputs, and a short index of twelve older
actions. A `recall` action retrieves the complete local receipt for any earlier
step without executing a shell command. Each model call records its prompt
length, provider usage, and cost. The local receipt remains private.

The Mithril lane still compiles the `.mith` action ontology, checks its pinned
digest, materializes OWL 2 RL, queries the entailed action class with SPARQL,
validates the proposal with SHACL, and advances a BPMN token. The helper now
compiles the ontology on `select`, immediately before any shell action. It
returns the next enabled set with each `complete`, so the runner does not launch
an extra `enabled` process after every action. `mithril_wall_seconds` records
helper wall time separately from model and shell time.

The bounded-history policy changes the agent's information surface. **Do not
compare v4 to v3 as an ontology-only A/B**. Compare v4 baseline and v4 Mithril
on the same predeclared task/repeat cohort. Also report success first; lower
token usage on failures does not establish task efficiency. This runner is not
Artificial Analysis's native mini-swe-agent harness or official score.

Use the v2 README's setup, replacing `terminal_bench_v2` with
`terminal_bench_v4`. `BENCH_RUN_ROOT` must remain outside the public repo.
`BENCH_MAX_STEPS` defaults to 500. Set a shared `BENCH_REPEAT_ID` for each
paired attempt. Local results are summarized with `summarize.py JOBS_DIR`.
On a Podman-only host, install `podman-compose` in an isolated environment,
put a symlink named `docker` to `docker-podman-compat.py` first on `PATH`, and
set `PODMAN_COMPOSE_BIN` to that environment's `podman-compose` executable.
Run an oracle-positive control before any scored trial; a missing Compose
`exec` or `cp` can otherwise produce a plausible-looking zero reward.

For a size-only replay of a private v3 receipt, run
`python3 measure_context.py /path/to/receipt.json`. It prints aggregate
history character counts only. Character reduction is not provider-token or
wall-time reduction; only a scored Harbor run establishes those values.
