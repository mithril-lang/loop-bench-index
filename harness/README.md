# Mithril harness

One agent loop, composable components, and a lane registry for the paired
Terminal-Bench measurements in this repository. It replaces the copy-per-version
layout of `bench/terminal_bench_v2`–`v7`, which stay frozen so their published
reports remain reproducible. The model it is converging to, and the order in
which parts may be added, is derived in
[results/harness-model-derivation-2026-09-25.md](../results/harness-model-derivation-2026-09-25.md).

## Layout

```text
harness/
  mithril_harness/
    loop.py          HarnessLoop: the executor every lane shares (Harbor BaseAgent)
    components.py    KnowledgeRetrieval, JevPriority, DifferentialJudge
    differential.py  pure row differential, independence and coverage checks
    lanes.py         LANES (runnable) and PLANNED (declared, refused by the runner)
  assets/            Mithril helpers and ontologies (byte-identical copies of v6/v7)
  run.py             sequential lane runner with verifier and checksum refusals
  tests/             equivalence, judge-lane, differential tests and scripted doubles
```

## Loop and hooks

`HarnessLoop.semantic = False` is the plain ReAct loop. `True` adds the
Mithril layer:
- source ontology probe and Luna prefill;
- `.mith` domain ontology with OWL 2 RL class closure;
- RDF/SHACL task state every step;
- BPMN action admission;
- the inspect budget;
- critical review;
- the required-artifact finish check.

Components change the loop only through five hooks:
- `task_text`: text placed in the TASK section;
- `before_query`: per-step policy or retrieval;
- `execute_action`: runs a non-finish action (default: bash);
- `finish_refusal`: a reason string that holds a finish, or None;
- `extra_metadata`: fields merged into Harbor metadata.

## Lanes

| Lane | Adds | Reproduces |
|---|---|---|
| `react` | — | v6 `HermesBaselineAgent` |
| `mithril` | Mithril semantic layer | v6 `MithrilDomainPrefillAgent` (v6d) |
| `knowledge` | + precompiled `.mith` rule retrieval (task-assisted) | v7 `MithrilKnowledgeAgent` |
| `jev-v7` | + Jev priority, v7 instruction | v6 `MithrilJevInterleavedAgent` |
| `knowledge-jev` | + both (task-assisted) | v7 `MithrilKnowledgeJevAgent` |
| `jev-neutral` | + Jev priority without the preferred-option sentence | new |
| `judge` | + DifferentialJudge (ablation a) | new |

`PLANNED` lanes are not implemented, and `run.py` refuses them with their
prerequisite: `typed-actions`, `belief-context`, `jev-policy`, `population`,
`budget-controller`.

## DifferentialJudge (`judge`)

`finish` is refused (`no-passing-differential`,
`differential-stale-after-artifact-change`) until the harness itself has run
every submitted answer/derivation pair and all pairs compare equal.

- **How the agent submits:** `action="verify"` with a
  `differential: {pairs, uncovered}` object.
- **Row format:** one row per line, tab-separated, no header. Fields are
  trimmed. `<…>` and surrounding quotes are removed and decimals normalized.
  Rows are compared as multisets.
- **Exit codes:**
  - 0: both sides nonempty and equal.
  - 1: measured mismatch. Up to 20 missing and 20 extra rows go back to the
    agent.
  - 2: unmeasured. A side failed or was empty, the submission was malformed,
    independence was refused, or there was a coverage gap.
- **Independence guard:** paradigms must be declared and must differ. Commands
  must differ. The derivation command, and each existing file it names (first
  256 KiB, one level), must not mention a required artifact or a file the answer
  command names. This is cheap, and it is not a proof: a derivation that shares
  the answer's misunderstanding still passes.
- **Coverage:** every required file is used by an answer command or declared
  uncovered with a reason.
- **Staleness:** the `sha256sum` of the required files is recorded at a pass and
  rechecked at finish.

The harness supplies no calculator, rule, or expected row.

## Tests

From the repository root:

```sh
python3 -m unittest harness/tests/test_differential.py
PYTHONPATH=harness/tests <harbor-venv>/bin/python -m unittest \
  harness/tests/test_equivalence.py harness/tests/test_judge_lane.py
```

- `test_equivalence` runs each reproducing lane and its frozen v6/v7 class over
  one scripted scenario. The scenario covers the inspect budget, malformed-JSON
  repair, critical review, the missing-artifact refusal and finish. The test
  asserts identical model prompts, action history, hypotheses, task-state phases
  and Jev inputs, and byte-identical assets. Adding one space to the loop's
  research prompt made it fail with `prompt 1 differs`.
- `test_judge_lane` drives the judge through the full loop: finish refused, a
  mismatch with its rows, independence refused, stale after a change, and
  admitted. A control run shows the same replies without the judge never hit
  the gate.
- `test_differential` pins the comparison, the canonicalization, the empty and
  failed sides, the duplicate-count boundary, and the independence and coverage
  refusal literals.

## Run

Use the v4 Podman setup: the `docker` shim first on `PATH`, and
`PODMAN_COMPOSE_BIN` set. Then:

```sh
python3 harness/run.py --task /path/to/task --output /private/dir \
  --repeat-id r01 --lanes mithril,judge --max-steps 48
```

Lanes run in the given order, never concurrently. Raw jobs, prompts and usage
stay in the private output directory. Summarize with
`bench/terminal_bench_v6/summarize.py <output>/<lane>/jobs`.

`ontology-kg-querying` is contaminated for blind evaluation (v8). Runs on it
are harness admission only. Claims require the predeclared held-out cohort in
the benchmark redesign.
