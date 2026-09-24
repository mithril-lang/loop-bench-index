# Terminal-Bench 4.0 paired runner (v2)

This adapter runs GPT-6 Luna (medium reasoning, OpenRouter through Hermes) in
Harbor's task container. Both lanes see the entire action/observation transcript
and can execute multi-line bash commands. The Mithril lane additionally checks
each action against a compiled BPMN process and advances its token after the
execution receipt. The ontology and process source are versioned here.

This is **not** Artificial Analysis's mini-swe-agent. Their published Terminal-
Bench 4.0 protocol uses all 66 tasks, three repeats, 500 steps, default
mini-swe-agent prompts/native bash and full transcript. Our Hermes JSON action
adapter, 64-step pilot cap, model route, and Podman environment are different.
The published model result is a reference point, not a directly comparable
control. See <https://artificialanalysis.ai/methodology/intelligence-benchmarking>
and <https://artificialanalysis.ai/evaluations/terminalbench-4-0>.

## Run

Run from a task worktree. Provide a working Harbor/Docker-compatible engine,
Hermes, `kbb`, and a Mithril runtime checkout. Set `MITHRIL_CLASSPATH` to the
runtime classpath. `BENCH_RUN_ROOT` must be outside this public repository: it
contains benchmark instructions, terminal output, and usage files that must
stay local. The model endpoint is the same in both lanes.

```sh
export PYTHONPATH="$PWD/bench/terminal_bench_v2"
export MITHRIL_CLASSPATH="$(cd /Users/junkawasaki/.hermes/runtime/mithril && kbb -Spath)"
export BENCH_RUN_ROOT=/tmp/terminal-bench-v2
export BENCH_MAX_STEPS=64
harbor run --path /path/to/terminal-bench/tasks/html-js-filter \
  --agent-import-path agent:MithrilBpmnAgent --model openai/gpt-6-luna \
  --job-name html-js-filter-mithril-v2 --jobs-dir "$BENCH_RUN_ROOT/jobs" \
  --n-concurrent 1
```

Use `agent:HermesBaselineAgent` for the paired baseline. A valid observation
requires a Harbor trial result, verifier reward, usage, and agent receipt.
Environment failure or missing verifier output is `unmeasured`, not reward 0.
The private instruction, terminal transcript, and verifier details are not
published. Export only task ID, source revision, aggregate reward, token/cost/
time measures, reasoned failure class, and digests.

## Measurement stages

1. **Admission:** one trial on a task absent from the prior three-task probe
   confirms container access, model route, Mithril transitions, and verifier.
   This is harness validation and never part of an efficiency index.
2. **Paired sample:** predeclare task IDs and seeds/repeats, run both lanes with
   the same model effort and limits, then publish every valid trial including
   failures. Report task-clustered success rates and intervals; do not convert
   an all-fail sample into an efficiency improvement claim.
3. **Full qualification:** 66 tasks × 3 repeats per lane. Report pass@1,
   tokens, estimated provider cost, and agent wall time. Efficiency on equal
   successful outcomes uses only matched task-repeat pairs and always states
   its eligible denominator. Success-adjusted cost needs at least one success.

AA-Briefcase v1.1's 91 scored tasks are private. Its public Lite scenario can
be used only as a separate artifact-quality probe, never as an official score.
See <https://artificialanalysis.ai/evaluations/aa-briefcase>.
