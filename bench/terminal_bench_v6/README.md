# Domain-prefilled Mithril research loop (v6)

This development runner extends v5. The Mithril lane performs a single prefill before terminal actions:

1. A read-only Python probe runs inside the task container. It reads the target bundle's `ontology_*.owl` and submission `*.ttl` files, collecting class/property declarations, subclass and subproperty edges, replacement edges, and observed term counts. It never opens verifier files, fixtures, or a reference solution.
2. GPT-6 Luna maps the task instruction and that inventory to bounded goals, constraints, falsifiable hypotheses, and exact source-vocabulary focus terms. Unknown focus terms are rejected.
3. Mithril writes and compiles a `.mith` task/domain ontology containing those goal and hypothesis nodes plus the source class hierarchy. OWL 2 RL derives the subclasses of selected focus classes. The ontology digest and inferred families are recorded.
4. On every terminal turn, the task text, prefill plan, hypotheses, and latest observation pass through Mithril's lossless RDF encode/decode and SHACL validation. Classes observed in the latest output are reclassified by OWL against the focus classes. Those entailments return to the model prompt for the next experiment. The v5 action ontology and BPMN token still govern execution.
5. The controller excludes `inspect` after six consecutive inspections until a modification or verification action occurs. The action parser tolerates the two observed malformed JSON suffixes; any other malformed reply receives one short model repair call, which is also metered.

The prefill is a model call and is included in provider usage, wall time, and cost. Mithril helper time is reported separately but remains part of total agent wall. Local raw probes, prompts, RDF, and receipts stay under `BENCH_RUN_ROOT`; public reports contain aggregates and digests only.

This implementation reasons over source class inheritance and observed class evidence. It does not provide a complete OWL 2 DL reasoner for arbitrary railway RDF or prove query correctness. Standalone SPARQL execution and verifier results remain the correctness authority. Compare success before resource ratios. The runner is not Artificial Analysis's native harness or an official Terminal-Bench score.

The v6 development trial documented in the result report remained at 9/13 and spent substantially more tokens than v5c. Keep v6 experimental; prefill and class entailment alone did not resolve query semantics.

Use the v4 Podman/Harbor setup with `PYTHONPATH` pointed at this directory, `BENCH_RUN_ROOT` outside the repo, `MITHRIL_CLASSPATH` from the Mithril runtime, and a shared `BENCH_MAX_STEPS`. Import `agent:MithrilDomainPrefillAgent` for the Mithril lane. The `HermesBaselineAgent` remains the v5 baseline implementation.
