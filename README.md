# loop-bench-index

Machine-readable index of paired agent-loop benchmark cohorts. Each record
keeps the corpus digest, per-lane requested and resolved model identities,
receipt coverage, exact-result parity, and resource indices. Failed and
unmeasured runs stay visible and never contribute to a parity-qualified index.

The initial suite is the Mithril read-only Git-status corpus. It compares the
configured Hermes chat model with Mithril's TypeSafe Jev decision model. Its
`:stack` index is an operational stack comparison; because the models differ,
it does not isolate the causal effect of loop architecture. A future
`:same-model` cohort is eligible only when both runners can call the same model
endpoint and report the same resolved model.

## Record format

- `resources/cohort-v1.edn` declares required cohort and receipt fields.
- `results/` stores immutable EDN cohort reports and their run receipts.
- `src/loop_bench_index.cljc` validates a report and projects a compact index
  row. It does not repair or infer missing provider measurements.

Call `index-row` with the report plus `{:receipts receipts :runner-revision
<commit>}` to include per-lane resolved model identities and run counts. The
recorded `results/index.edn` follows that shape and links each cohort to its
full report and receipts.

To add a cohort, retain its predeclared plan, all run receipts, full report,
runner revision, Hermes version, and Mithril revision. Do not publish indices
for pairs without exact expected-result parity. The denominator and eligible
pair count accompany each aggregate.

External task-family probes are kept separately from paired resource indices.
They are not official benchmark scores and do not enter `results/index.edn`:
see [the 2026-09-24 probe report](results/external-task-probes-2026-09-24.md)
and [the Terminal-Bench 4.0 GPT-6 Luna paired probe](results/terminal-bench-4.0-gpt6-luna-mithril-v1/report.md).

The [2026-09-24 benchmark redesign](results/benchmark-redesign-2026-09-24.md)
audits false zero rewards caused by missing verifier dependencies and defines
the repeated, oracle-controlled measurement path. Versioned Terminal-Bench
runners live under `bench/terminal_bench_v2/` and `bench/terminal_bench_v3/`.
The [v2 verifier-failure admission trial](results/terminal-bench-4.0-gpt6-luna-mithril-v2/report.md)
and [v3 semantic-loop development pair](results/terminal-bench-4.0-gpt6-luna-mithril-v3/report.md)
preserve the measured boundary; neither supplies a success-qualified
efficiency index.

The [GPT-6 Luna + Mithril + Jev interleaved trial](results/terminal-bench-4.0-gpt6-luna-mithril-jev-v7/report.md)
records 39 metered Jev decisions on the pinned railway task. It retained the
same 9/13 partial result as the Luna + Mithril reference; its success-qualified
indices are null.

The [co-scientist loop analysis](results/coscientist-loop-analysis-2026-09-25.md)
reads the v5–v8 trials and proposes a measured-judge tournament design using
Mithril OWL/SHACL; it is a design analysis with no new measurement.

The [Mithril harness](harness/README.md) is the maintained loop: one executor,
composable components (knowledge, Jev priority, differential judge) and a lane
registry, byte-equivalent to the frozen v6/v7 agents it reproduces. Its target
model is derived in [the harness model derivation](results/harness-model-derivation-2026-09-25.md).

The [10-minute verification loop](results/micro-loop-2026-09-25/report.md)
runs harness lanes on seeded railmini micro tasks in parallel, with a
prompt-cache-aware chat transport and a resident Mithril helper.

The [Terminal-Bench co-scientist record](results/tb-coscientist-gen0-2026-09-25/report.md)
compares the Mithril harness with an AA-aligned mini-swe-agent on real
Terminal-Bench 4.0 tasks: generation 0 results, the unmeasured generation 1
and the resume point.

## AA-Briefcase-Lite exploratory cohort

`results/aa-briefcase-lite-w1-t1-gpt6-luna-v1/` records one retrospective
same-model comparison on the public W1-T1 Market Structure Map task. Both lanes
used GPT-6 Luna through OpenRouter; the Mithril lane additionally used a compiled
market ontology and bounded BPMN action/effect gates. This is not an Artificial
Analysis leaderboard result or Intelligence Index score. Both PDFs compiled to
one page, but both failed the task's visual render-integrity check (overlap or
clipping), so the outcomes are not parity-qualified and the index values remain
null. Raw token, estimated cost, and available wall measurements are preserved
with their different timing scopes explicitly labeled. The remaining rubric
checks were not scored; the cohort is exploratory and not preregistered.
