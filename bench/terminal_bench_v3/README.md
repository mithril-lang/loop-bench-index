# Mithril semantic terminal loop (v3)

This runner keeps the v2 full-transcript Hermes bash loop and adds an executed
Mithril semantic admission step for each proposed action. The `.mith` ontology
declares each terminal action as a subclass of `ProposedAction`. The Mithril
helper compiles the ontology, checks its digest against the bot profile,
materializes OWL 2 RL entailments, queries the inferred superclass with SPARQL,
validates action kind and command text with SHACL, and records a semantic
receipt. BPMN then selects the action. A nonzero terminal exit restores the
previous gateway; a zero exit advances the process token.

The baseline lane calls the same model with the same full transcript and
terminal command interface, without the Mithril admission/transition work.
`BENCH_MAX_STEPS` defaults to 500, matching the published Artificial Analysis
step cap, but the model route and JSON adapter still differ from their native
mini-swe-agent harness. Claims about the official leaderboard require the
official 66-task, three-repeat protocol and are not made here.

Use the v2 README's environment setup, replacing `terminal_bench_v2` with
`terminal_bench_v3`. Local `BENCH_RUN_ROOT` stores private task instructions and
transcripts. Public reports contain only task identifiers and summary metrics.
Run each predeclared repeat in a separate Harbor invocation with a shared
`BENCH_REPEAT_ID` (for example `r1`) across the two lanes; do not rely on
Harbor's `--n-attempts` to identify paired repeats. Each agent instance gets a
fresh random state/usage directory so one trial cannot reuse another's BPMN
token or model usage files.
The summarizer marks known missing-verifier-dependency failures `unmeasured`;
each scored trial also needs verifier execution evidence, since an emitted
reward file alone can be a false score.

`summarize.py JOBS_DIR > rows.json` exports public-safe per-trial rows.
`analyze.py rows.json` then reports scored coverage, oracle controls, success
rates, and task-clustered intervals when at least five distinct tasks exist.
It refuses a model row without an oracle-positive control for the same task
checksum or a cohort that mixes task revisions. Pass@1 averages per-task
repeat success rates; the report flags tasks without three scored repeats.
The resource index remains null until ten matched successful repeats span at
least five tasks. This floor only prevents a tiny sample from displaying an
index; it is not a claim that ten repeats establish statistical significance.
An empty or receipt-free input is refused rather than reported as success.
