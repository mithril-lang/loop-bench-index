# Mithril research loop (v5)

This is a development harness for Terminal-Bench 4.0, using GPT-6 Luna through Hermes/OpenRouter. `HermesBaselineAgent` retains the v3 full transcript and action protocol. `MithrilCoscientistAgent` adds a task-state research cycle:

1. The model states a hypothesis and a falsifiable prediction with its action.
2. A command is run in the isolated task container and its result becomes the next observation. Failed commands move the next prompt to reflection.
3. Mithril encodes the task text, recent hypotheses, and last observation as a typed RDF state graph; decodes it and checks exact equality; applies the state ontology with OWL 2 RL and SHACL; then infers a research-state class from the `.mith` research ontology.
4. The existing `.mith` action ontology and BPMN helper admits the proposed terminal action. A finish proposal checks explicitly listed output files and is refused when any file is missing.
5. With `BENCH_CRITICAL_REVIEW=1` (default), the first finish proposal is held for a skeptical acceptance review and an additional successful verification action. Set `BENCH_CRITICAL_REVIEW=0` to reproduce the initial v5 development variant.

The task-state helper emits `state-graph-digest`, node count, SHACL status, and an OWL entailment flag per call. `RUN_ROOT/receipts` keeps local action and semantic receipts; do not publish private task transcripts. The state codec and OWL inference run locally outside the benchmark container. They must be included in wall-time comparisons.

The Mithril prompt and finish gate differ from the baseline, so their score delta cannot be attributed to ontology alone. Report task success before token or cost ratios. This is not the Artificial Analysis native harness or an official Terminal-Bench score.

Use the v4 setup for Podman/Harbor. Set `PYTHONPATH` to this directory, `BENCH_RUN_ROOT` to a scratch directory, `MITHRIL_CLASSPATH` to the Mithril runtime classpath, and `BENCH_MAX_STEPS` to a shared limit. Run an oracle control and both lanes against the same pinned task before publishing a comparison. The v3 `summarize.py` accepts the Harbor jobs directory.
