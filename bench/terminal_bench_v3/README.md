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
The summarizer marks known missing-verifier-dependency failures `unmeasured`;
each scored trial also needs verifier execution evidence, since an emitted
reward file alone can be a false score.
