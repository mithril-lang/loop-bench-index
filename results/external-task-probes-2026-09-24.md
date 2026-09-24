# External task-family probe — 2026-09-24

This report separates measured local runs from external benchmark compatibility
research. It is not an Artificial Analysis score and is not part of the paired
resource indices.

## Measured results

### Read-only Git status, cohort v3

The predeclared corpus has three Git-status states with five repetitions each
(15 pairs). Both stacks matched all 15 expected outcomes. The Mithril lane used
the deterministic ontology/BPMN path and made zero model calls; Hermes used
`openai/gpt-4o-mini`.

| Measurement | Hermes | Mithril |
|---|---:|---:|
| Exact outcomes | 15/15 | 15/15 |
| Mean wall time per task | 34.804 s | 75.982 s |
| Mean model tokens per task | 9,579.5 | 0 |
| Mean reported model cost per task | $0.00046572 | $0 |

The Mithril/Hermes wall index is 218.31, or 2.18x the Hermes wall time for
this harness and corpus. This is only evidence about these fixed Git-status
tasks.

### Interpreter-start control

Three warm invocations of `kbb --backend sci bin/mithril-hermes.cljk --help`
completed in 2.46 s, 2.35 s, and 1.89 s (mean 2.23 s). These are CLI startup
controls, not per-action timings from the benchmark run. The v3 metadata says
its runner includes repeated `kbb` process starts, but the v3 receipts record
only total `wall-ms`, not action or process spans. If the three mandatory BPMN
actions each caused one such process start, startup alone would be about 6.7 s;
the receipts do not establish that exact count. The observed 41.18 s mean gap
therefore remains unexplained by measured stage timings. The next performance
measurement needs per-action and runner-span receipts before assigning the
remaining delay to Mithril execution, process startup, or host I/O.

### Isolated governed-coding probe

One clean clone of the Mithril runtime was used, with a new state file and
separate artifact directory. The task was the bounded `.mith` WebApplication
edit used by the local coding canary, followed by compile, exact HTTP response
check, Git status, and stop.

- Step 1 (`workspace-inspect`) completed.
- Step 2 (`code-propose`) ended with `mithril.hermes/proposer-failed` after the
  configured 180,000 ms proposer timeout.
- The final state is `:failed` at step 2. No patch was applied; compile and
  task verification did not run.
- Token and provider cost for this failed proposal are **unmeasured**; no usage
  receipt was emitted.

Earlier v3–v7 coding attempts failed at `code-propose` with
`mithril.hermes/proposer-failed`; v8 failed with
`mithril.hermes/proposer-workspace-denied`; v9 failed at the clean-workspace
guard with `mithril.hermes/dirty-workspace`. None completed the task, so none
is counted as a success. The clean-clone probe removes the v9 workspace
confounder, but its proposer timeout still prevents a claim that the coding
loop completed this task.

## Artificial Analysis task-family fit

Artificial Analysis currently describes its Intelligence Index as an aggregate
of ten evaluations, including agentic knowledge work, SaaS workflows, terminal
coding, scientific coding, knowledge/reasoning, and long-context tasks. Its
AA-Briefcase evaluation page says the scored 91 tasks are private. The public
AA-Briefcase-Lite dataset is an illustrative, non-scored scenario with four
deliverables (`.tex`/`.pdf`, `.xlsx`, `.pptx`, and `.mp4`/`.srt`) and a shared
pool described as 67 sources / 147 files.

The public Lite tasks were **not executed** in this probe. Their results must
not be inferred from the Git-status cohort. Current evidence supports these
boundaries:

| Task family | Current evidence | Status |
|---|---|---|
| Fixed, read-only Git status | 15/15 exact outcomes in v3 | Demonstrated for this corpus |
| Bounded `.mith` coding task | Clean-clone proposal timed out at 180 s | Attempted, not solved |
| AA-Briefcase-Lite business analysis and office deliverables | No run; present canary catalog has no verified PDF/XLSX/PPTX/video workflow | Unverified / no demonstrated support |
| Terminal-Bench 4.0 task families | Three custom Harbor task pairs (`ontology-kg-querying`, `react-lead-form`, `interleaved-vigenere`); all six trials received verifier reward 0.0 and no pair qualified for an efficiency index | Attempted, not solved; see [paired probe report](terminal-bench-4.0-gpt6-luna-mithril-v1/report.md) |
| HLE, AA-Omniscience, and other open-ended reasoning tasks | No run; no task-family accuracy corpus or matched inference path in this probe | Unverified / no general-reasoning claim |

The current `readonly-canary` is a closed workflow: inspect workspace, run Git
status, then stop. The separate governed-coding profile has a typed patch,
compile, test, and Git action set, but the clean coding probe did not complete.
Neither result establishes broad Artificial Analysis benchmark capability.

### Sources

- [Artificial Analysis Intelligence Index overview](https://artificialanalysis.ai/)
- [AA-Briefcase evaluation and task privacy / public example description](https://artificialanalysis.ai/evaluations/aa-briefcase)
- [Official AA-Briefcase-Lite dataset card](https://huggingface.co/datasets/ArtificialAnalysis/AA-Briefcase-Lite)
- [Official Terminal-Bench repository and task harness](https://github.com/harbor-framework/terminal-bench)
