# Typed action coverage of logged agent actions (rung 2)

Date: 2026-09-25. This is rung 2 of the [harness model
derivation](../harness-model-derivation-2026-09-25.md). The question: how many
of the actions the model chose could the harness have generated itself from
typed parameters? Those actions need no LLM-written text, so a policy (Jev or
a deterministic rule) could choose them instead of a Luna call. No model was
called for this measurement. Aggregate counts are in `coverage.json`. Receipts
and per-action commands stay local because they contain task text.

## Library and classifier

`harness/mithril_harness/typed_actions.py` defines 20 operations in three
tiers:

| Tier | Meaning | Operations |
|---|---|---|
| `pure` | harness-generated from paths, source-vocabulary terms and integers | `list-files`, `show-file`, `grep-terms`, `schema-summary`, `term-usage`, `describe-class`, `run-entrypoint`, `run-queries`, `preservation-check`, `vocabulary-check`, `result-contract`, `acceptance-check`, `env-check`, `workspace-setup`, `install-requirements` |
| `authored` | typed, but one argument is model-written | `sparql-probe`, `python-probe`, `differential` |
| `llm` | writes an artifact | `write-file`, `patch-file` |

The library names no task class, property or answer. `acceptance-check` runs
the entrypoint on each bundle, then preservation, vocabulary and the declared
queries. Every generator with an implementation was executed against a
synthetic RDF bundle, and each check was shown to fail for its stated reason
(`harness/tests/test_typed_actions.py`).

`harness/tools/action_coverage.py` works in four steps:
1. It splits each command into segments. Heredocs and quoted `-c` bodies stay
   whole, the split is quote-aware, and `bash -c` wrappers are unwrapped.
2. It maps each segment to an operation.
3. It gives the action the worst tier among its segments.
4. It counts harness gate entries separately; they are not model actions.

It has two modes:
- `strict` maps shell-level operations only. Every Python heredoc counts as an
  authored probe. This gives a **lower bound**.
- `signature` also maps Python heredocs by what they do (run `.rq` files, check
  preservation, run the entrypoint). This gives an **upper bound**: a script
  matched as `acceptance-check` can carry bespoke assertions a library call
  would not make.

The tool refuses (exit 2) when no model action was scanned, or when a receipt
is unreadable.

## Result

There were 9 receipts: v6 development trials (4), v7 Jev (1), the sequential
knowledge pair (2), and the harness judge pair (2). They hold 224 entries: 218
model actions and 6 harness gate entries.

| | strict | signature |
|---|---:|---:|
| `pure` | 45 (20.6%) | 127 (58.3%) |
| `authored` | 138 | 56 |
| `llm` | 35 | 35 |

By action kind (signature):
- **inspect:** 68/104 pure.
- **verify:** 59/81 pure.
- **modify:** 0/33 pure.

The largest single operation is `acceptance-check`, with 74 segments. It is
the same run-pipeline / check-preservation / run-queries sequence, rewritten
from scratch by the model in most verify turns.

**Hand check.** I labelled a random sample of 30 actions (seed `20260925`),
as a single rater who could see the classifier's output. 27/30 agreed. There
was one false `pure` (a query run bundled with bespoke voltage printing) and
two false `authored` (Python scripts that only filter lines by keyword, which
is equivalent to `grep-terms`). The classifier found 17/30 pure; the rater
found 18/30. Measurement also found three classifier defects: a quote-unaware
split, an unwrapped `bash -lc`, and `printf … > file` counted as a header.
Each is fixed and pinned by a test in `harness/tests/test_action_coverage.py`.

## What it means

- Between 21% and 58% of model-chosen actions could have been produced
  without model-written text. That is the ceiling on Luna calls a typed policy
  could replace. It is not a measured saving. It assumes the policy chooses
  as well as Luna did, and that the replaced calls cost as much as the
  average one. Neither has been measured.
- Most pure verify actions are one repeated composite. It needs no *choice*
  at all: a BPMN rule can run `acceptance-check` after every `modify` and put
  the report into the next observation. This deterministic step needs neither
  Jev nor Luna. It becomes the next candidate lane, `auto-acceptance`.
- Pure inspect actions still require choosing *which* terms, files or classes
  to look at. That choice is over a finite source vocabulary. It is where a
  Jev policy would act (derivation H2 on H3), after calibration.
- Every artifact write and 56 probes stayed with the model. The probes
  (`sparql-probe`, `python-probe`) are the semantic reasoning part the
  derivation keeps for the LLM.

## Limits

- One task family: the railway RDF/SPARQL task.
- The library was designed after reading these receipts, so this is
  in-sample coverage and likely optimistic for unseen tasks.
- The sample check had one non-blind rater.
- Coverage says nothing about success: all these trials failed the same four
  assertions.
- Per-call token cost by action kind was not measured, so no dollar ceiling is
  stated.

## Reproduce

```sh
python3 harness/tools/action_coverage.py <receipt.json>... [--details /private/rows.jsonl]
python3 -m unittest harness/tests/test_action_coverage.py harness/tests/test_typed_actions.py
```

The receipts are `receipts/*.json` under each lane's private `BENCH_RUN_ROOT`
for the runs listed above.
