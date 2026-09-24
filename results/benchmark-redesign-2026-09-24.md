# GPT-6 Luna × Mithril agent loop: revised measurement protocol

## Why the earlier numbers were inconclusive

The original Terminal-Bench 4.0 probe used three tasks once per lane, 12–20
steps, and a one-command JSON action interface. It yielded no task successes.
A verifier audit then found that the Vigenère pair's `pytest` command was
missing, so two reward zeros were infrastructure failures. A fourth task,
`html-js-filter`, also emitted reward zero after its verifier failed to import
`pytest`. These zeros are **unmeasured**, not task failures. The benchmark must
prove that assertions ran before using any reward.

Artificial Analysis reports Terminal-Bench 4.0 on all 66 tasks, three repeats
per task, with mini-swe-agent's native bash, full transcript, and at most 500
steps. The published GPT-6 Luna **high** and **max** scores are 5% and 13%; the
current local model setting is **medium** and uses OpenRouter/Hermes, so those
figures are reference values only. At a 5% success rate, zero successes in
three independent trials has probability 85.7%; three failures alone cannot
diagnose the model or loop. Sources:
<https://artificialanalysis.ai/evaluations/terminalbench-4-0>,
<https://artificialanalysis.ai/methodology/intelligence-benchmarking>,
<https://artificialanalysis.ai/models/comparisons/gpt-6-luna-high-vs-gpt-6-luna>.

AA-Briefcase v1.1 has 91 private scored tasks. Its public Lite scenarios are
useful for separate artifact checks but cannot recreate the leaderboard score
or ranking: <https://artificialanalysis.ai/evaluations/aa-briefcase>.

## Primary measures and admission gates

Each benchmark row retains the corpus revision/task checksum, model/provider/
reasoning level, runner revision, task ID, repeat, lane, verifier result,
executed assertion count, model tokens, estimated provider cost, and agent
execution wall time. Report skipped, environment-error, verifier-error, and
scored rows separately. A reward file without proof that assertions ran is
unmeasured. Run the upstream oracle in a fresh environment as a verifier
positive control before including a task family; the oracle result must be 1.

On external tasks, the primary comparison is **success rate** with a task-
clustered interval and full denominator. This remains meaningful even when
one lane has no successes. Speed, tokens and cost are reported for all scored
trials with success/failure stratification. Cost per successful task is defined
only if successes occur. The equal-outcome efficiency index requires matched
task/repeat pairs where both lanes pass; if none exist it remains null.

The **Mithril effect** is assessed in a paired same-model cohort: identical
task version, effort, prompt transcript policy, shell interface, step/time
budget, and verifier; the Mithril lane adds executed OWL 2 RL, SPARQL, SHACL
admission and BPMN transitions. Record semantic receipt count and fail-closed
refusals. v3 implements this path and uses 500 as its default step cap. It is
still a custom Hermes adapter, so its score must not be called an AA score.

## Execution stages

1. Harness admission: one oracle-positive task, one trial per lane. Verify
   actual assertion count and at least one semantic receipt. These rows are
   development evidence and excluded from qualification statistics.
2. Predeclare the CPU-feasible task subset from the pinned 66-task source and
   run three repeats per lane. Publish task selection, invalid/excluded rows,
   and per-task success counts. Do not choose tasks by observed model success.
3. Run the official full 66-task cohort only on infrastructure that satisfies
   each task's resources, including GPU requirements. Compare with AA only
   after matching model effort, agent harness, and execution environment, or
   state every mismatch next to the number.
4. Keep a separate easier deterministic paired suite for resource efficiency.
   Terminal-Bench's low Luna success rate makes equal-success pairs too sparse
   for a useful cost/speed index at small sample sizes. Do not combine its
   results with AA-Briefcase-Lite rubric outcomes.

Qualification remains open until the predeclared cohort, valid verifier
controls, and repeated outcomes exist. No speed, intelligence, or cost
advantage is claimed from the admission trials.
