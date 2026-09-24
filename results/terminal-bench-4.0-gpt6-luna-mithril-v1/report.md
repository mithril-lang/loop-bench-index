# Terminal-Bench 4.0 GPT-6 Luna paired probe

**Verifier audit correction (2026-09-24):** The `interleaved-vigenere` pair
was never validly scored. Both verifier logs say `pytest: command not found`;
their emitted reward 0.0 measures a missing dependency, not task failure.
Thus only the `ontology-kg-querying` and `react-lead-form` pairs reached their
verifiers, and all four of those trials failed. The six-row table below is a
historical record. Exclude the Vigenère rows from any task-score aggregate,
and treat the original six-trial aggregate ratios below as superseded.

This is an exploratory, custom Harbor-agent probe, not an official Terminal-Bench leaderboard result. It used three public task IDs from Terminal-Bench 4.0.0 at source commit `452bf305c6daa62fc59061d22133a7cbc7c1572e`, one run per lane per task. The user prompt, task files, verifier implementation, and task-specific artifacts are intentionally not published.

Both lanes called the same requested model (`openai/gpt-6-luna`) through OpenRouter via Hermes CLI at medium reasoning effort. Each model response selected one shell action, and the command ran only in the Harbor task container. The Mithril lane additionally compiled a terminal-action ontology and advanced enabled actions through Mithril's BPMN executor. Task score is Harbor's official verifier reward.

## Results

| Task ID | Lane | Reward | Model calls | Total tokens | Estimated cost | Agent wall time |
|---|---|---:|---:|---:|---:|---:|
| `ontology-kg-querying` | Hermes loop | 0.0 | 20 | 565,919 | $0.078378 | 429.443 s |
| `ontology-kg-querying` | Mithril BPMN loop | 0.0 | 20 | 498,914 | $0.067880 | 396.877 s |
| `react-lead-form` | Hermes loop | 0.0 | 20 | 329,669 | $0.047021 | 281.785 s |
| `react-lead-form` | Mithril BPMN loop | 0.0 | 20 | 461,635 | $0.067700 | 610.244 s |
| `interleaved-vigenere` | Hermes loop, 12-step cohort | 0.0 | 12 | 118,207 | $0.020172 | 365.450 s |
| `interleaved-vigenere` | Mithril BPMN loop, 12-step cohort | 0.0 | 12 | 73,084 | $0.013851 | 449.669 s |

Every reward file returned 0.0, but two of the six trials were verifier infrastructure failures as noted above. The remaining four are verifier-executed failures. A matching zero score does not establish equivalent task outcomes, so there are **zero parity-qualified pairs** and no token, cost, or speed efficiency index. The originally reported six-trial aggregate raw resource ratios (Mithril/Hermes) of 101.96% for tokens, 102.65% for estimated cost, and 135.30% for agent wall time are superseded because they include unmeasured trials.

Results varied by task. On `ontology-kg-querying`, Mithril used 11.84% fewer reported tokens, 13.39% lower estimated cost, and 7.58% less agent wall time, while still failing the verifier. On `react-lead-form`, Mithril used 40.03% more tokens, 43.98% higher estimated cost, and 116.56% more agent wall time. The `interleaved-vigenere` resource totals describe agent execution only; its verifier failed to run. Each cell is one run; there are no confidence intervals or variance estimates.

## Measurement scope and limitations

- `total_tokens` is Hermes' provider-reported total, including cached context; costs are provider-model-metadata estimates, not invoices.
- `agent wall time` is Harbor's `agent_execution` span. Environment setup and verifier time are excluded.
- The first two task pairs used a 20-step cap. The Vigenère pair used a later 12-step cohort, but its verifier infrastructure failed and no outcome can be assigned.
- Earlier invalid harness attempts are excluded from the six reward-emitting trials: one Harbor `ExecResult` field mismatch, one JSON response extraction failure, and one unhandled 120-second shell timeout. Their available model usage totals 19 calls and an estimated $0.038499; these are retained only in the local run archive, not assigned to a task score.
- The local runner used Harbor 0.1.43, Podman 5.6.0, and a Docker Compose compatibility shim. This compatibility environment and custom agent are not the official leaderboard runtime.
- These results show task-family attempts, not general reasoning ability, Artificial Analysis Intelligence Index performance, or production readiness.

## Reproducibility identifiers

- Mithril runtime commit: `1714d7c6d02fb37d5315f3e62daa4d4407eac84e`
- Agent adapter SHA-256: `dce6d6dbfb23b44af7bea4e4e259154ea8d944c3be0c7d48c9e7c5036a82a3ee`
- Ontology source SHA-256: `1995a502e3dcca51a84e6b82a7ea095b3b0bbd11447d2c9054de7dff97e9fd3a`
- BPMN profile SHA-256: `a4ee4a6ee2085050b25cf77716aa0f7bf65447b9980cee1dcb679f9920cfd2ca`
- Compiled ontology graph SHA-256: `403c23925ff2a8b89183f88c577b07c3006208306903931fad39cf97bf08ce0a`
