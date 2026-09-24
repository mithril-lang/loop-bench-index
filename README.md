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
