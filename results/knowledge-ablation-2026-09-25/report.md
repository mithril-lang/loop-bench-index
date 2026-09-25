# Precompiled Mith knowledge: paired development measurement

Date: 2026-09-25. Model: `openai/gpt-6-luna` via Hermes/OpenRouter, medium reasoning. The source was the versioned general and railway `.mith` ontologies in `bench/terminal_bench_v7/knowledge/`. Mithril compiled 5 general rules and 5 task rules and proved the configured railway OWL subclass entailment. Digests: general `sha256:b910d592f27005590893794ac3438883be10b1a4c9eda470559d667bd9bd1103`; task `sha256:ab927dd4cb65c77a90b3375086066599d4092f5180231bd0479e65a46571be06`.

## Decision diagnostic

`bench/terminal_bench_v7/knowledge_ab.py` asked 8 paired railway ontology decisions (4 allow, 4 reject). Each was evaluated in three lanes: no preloaded rules, all 10 preloaded rules, and up to 4 retrieved rules. The question and scoring condition were identical across lanes. Every call had a complete Hermes usage receipt. `rows.json` contains public-safe per-case scores, times, prompt hashes, token counts, and costs. Raw prompts, output, and provider receipts remain local under `/tmp/knowledge-ab-20260925`.

| Lane | Correct | Total tokens | Reasoning tokens | Estimated USD | Model wall seconds |
|---|---:|---:|---:|---:|---:|
| No rules | 8/8 | 32,727 | 217 | 0.00428715 | 75.060 |
| All 10 rules | 8/8 | 35,711 | 146 | 0.00463915 | 67.885 |
| Bounded retrieval | 8/8 | 34,194 | 303 | 0.004512525 | 70.248 |

Relative to no rules, bounded retrieval used **4.48% more total tokens** and **5.26% more estimated cost**. All-rule prefill used **9.12% more tokens** and **8.21% more cost**. The observed wall time was 6.41% and 9.56% lower, respectively, but the calls were sequential and subject to service latency; this is not evidence of a speedup. Accuracy did not improve because all three lanes got all eight decisions right. The ontology compile/retrieval time is excluded from the model wall column, so end-to-end latency for the knowledge lanes is understated. Reasoning-token counts vary without a corresponding accuracy difference and should not be interpreted as improved reasoning efficiency.

These are short, source-derived decisions with answer-relevant facts in each question. The precreated railway knowledge is task-specific and was developed after earlier task feedback. This is a nonblind diagnostic, not an unseen-task Terminal-Bench score or a statistically significant sample. It cannot establish that prior knowledge improves SPARQL construction, hidden-bundle correctness, or the full agent loop.

## Full agent-loop attempt

We also started a paired Harbor run on `ontology-kg-querying` task checksum `36696def4524165e9caad8f162fb58f8a37f5769ca192139b724d2493648345d`, with the same Luna/Mithril domain-prefill loop, 64-step ceiling, and only the static knowledge mixin changed. The knowledge lane compiled both `.mith` ontologies before prefill, then Hermes exited 2 on its eighth model call. The no-knowledge lane progressed through 16 model calls, but the task container disappeared during the overlapping run and the trial was cancelled. Neither trial ran the verifier. Both are **unmeasured**, not zero-score trials, and no agent-loop accuracy, speed, or cost uplift can be calculated from them. Running two Harbor jobs concurrently on the 2 GiB Podman VM was an invalid execution setup; any future paired rerun must be sequential and retain provider failure output.

The prior fixed candidate's 13/13 is a nonblind development control, not an agent result. The earlier v7 Luna/Mithril/Jev agent result remains 9/13 and is not a matched no-knowledge control for this ablation.

## Reproduce

Set `MITHRIL_CLASSPATH` to `kbb -Spath` in the Mithril runtime and run:

```sh
python3 bench/terminal_bench_v7/knowledge_ab.py --output /tmp/knowledge-ab-repeat
```

The script refuses to proceed if ontology compilation or OWL entailment fails. It marks incomplete provider calls unmeasured and writes the score after each completed call. Run in a private output directory because raw model prompts and responses are recorded there.
