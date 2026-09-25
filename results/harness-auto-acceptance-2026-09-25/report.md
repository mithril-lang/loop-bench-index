# Auto-acceptance on Terminal-Bench: invalid because of a harness defect

Date: 2026-09-25. Harbor ran `ontology-kg-querying` (checksum
`36696def…345d`) twice, sequentially, through `harness/run.py`: first
`mithril`, then `auto-acceptance`. Both used `openai/gpt-6-luna` via Hermes at
medium reasoning, a 48-step cap, and repeat `auto-acc-02`. Public rows are in
`paired-results.json`. The task is contaminated (v8), so at most this could
have been a development pair.

An earlier attempt, `auto-acc-01`, is **unmeasured**. The `docker` shim
symlink pointed into a deleted clone, so Harbor failed at environment start
before any model call. `run.py` now refuses a missing or dangling shim.

| Measure | `mithril` | `auto-acceptance` |
|---|---:|---:|
| Verifier assertions | 9/13 | 9/13 (same four failures) |
| Steps | 17 | 30 |
| Hermes calls / provider API calls | 18 / 29 | 33 / 69 |
| Input + output tokens | 852,525 | 3,609,813 |
| Estimated cost (USD) | 0.082310765 | 0.259382905 |
| Agent wall (s) | 745.986 | 1,462.150 |
| Harness acceptance runs (exit 0) | — | 8 (0) |

## Why the auto-acceptance lane is invalid

The acceptance spec was admitted (all values verbatim in the instruction).
The harness then ran the acceptance check after all 8 modifies, and all 8
exited 1.

- **One was a real defect in the agent's pipeline.** It parsed a Turtle
  `.owl` file as RDF/XML.
- **Seven were false.** The check treated every `*.owl` and `*.ttl` file in
  the bundle as a source. The bundle also contains `validation_shapes.owl`
  (SHACL shapes), which the task does not name as an input. The agent's
  pipeline correctly left it out, so the check reported about 1,000 "missing"
  source triples. The Terminal-Bench verifier's own preservation assertions
  passed.

The lane fed the agent false failure reports seven times. Its outcome and its
costs measure a broken harness component, not the auto-acceptance idea. It is
excluded from comparisons.

The two `mithril` runs of the day (48 and 17 steps, $0.319 and $0.082, both
9/13) show a 4× cost spread within one lane. A single pair cannot separate a
lane effect from that variance.

## Fix

The typed acceptance spec now carries `sources`: exact file names, or
`*.<ext>` for a whole extension. Each entry is admitted only if the name, or
the extension, appears in backticks in the instruction.
`preservation-check`, `vocabulary-check` and `acceptance-check` take those
patterns. A test bundle now holds a non-source `shapes.owl`, which the
pipeline excludes; the check must pass. Removing the patterns from the check
reproduces the false report (`MISSING_FROM_OUTPUT 1`), and the test fails on
it.

The defect was not caught earlier because the offline test bundles contained
only source files. That is question 1 of the verification checklist: what
does the check do with input it was not written for?
