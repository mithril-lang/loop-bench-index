# Bounded-history terminal-loop development probe (2026-09-24)

This is a one-task, one-repeat development probe, not an Artificial Analysis
score or a statistically significant efficiency result. The pinned
Terminal-Bench 4.0 `ontology-kg-querying` task is at source commit
`452bf305c6daa62fc59061d22133a7cbc7c1572e`, task checksum
`36696def4524165e9caad8f162fb58f8a37f5769ca192139b724d2493648345d`.
Both lanes used Hermes/OpenRouter `openai/gpt-6-luna`, medium reasoning, the
same v4 bounded-history prompt policy, and a 24-step cap. The Mithril lane
also applied its `.mith` action ontology, OWL 2 RL/SPARQL/SHACL admission,
and BPMN transitions. The oracle control passed all 13 assertions on the
same task and verifier.

| Measure | Hermes baseline | Mithril loop | Oracle |
|---|---:|---:|---:|
| Reward | 0.0 | 0.0 | **1.0** |
| Artifact gate | `pipeline.py` missing | `pipeline.py` missing | 13/13 assertions |
| Model calls | 24 | 24 | — |
| Executed bash actions | 24 | 20 | — |
| `inspect` actions | 24 | 20 | — |
| `recall` calls | 0 | 4 | — |
| Provider API calls | 37 | 33 | — |
| Provider total tokens | 322,337 | 302,957 | — |
| Reasoning tokens (within total) | 3,615 | 2,626 | — |
| Estimated model cost | $0.03233901 | $0.03131450 | — |
| Agent wall | 392.000 s | 507.874 s | — |
| Mithril helper wall (part of agent wall) | 0 | 147.187 s | — |
| Semantic admission receipts | 0 | 20 | — |

The raw Mithril/baseline differences are **−6.01% total tokens, −3.17%
estimated model cost, and +29.56% wall**. Both lanes failed before the
13-assertion verifier body because neither produced the required artifact.
The success-qualified efficiency index and task-clustered confidence interval
are therefore null. There is no evidence that ontology reasoning improved
task intelligence here. OWL was used for terminal action admission, not for
the task's own KG queries.

An offline replay of the earlier v3 19-action receipts reduced the *history
payload* from 1,594,535 to 174,506 characters (Mithril, −89.06%) and from
1,765,428 to 180,636 (baseline, −89.77%). This is a prompt-character
measurement, not an API-token measurement. The v4 model calls no longer
replayed the entire transcript, but the bounded history lost useful progress
context: both lanes spent the full 24-call budget inspecting and made no edit.
Consequently this policy is **rejected as an efficiency improvement**. Do not
compare v4 with v3 as an ontology-only A/B: history policy, step cap, and
stochastic trajectories differ. A viable next candidate must preserve a
compact, typed task state (requirements, discovered files/facts, attempted
commands, pending artifact, and verification state), support exact receipt
recall, and compute static OWL entailments once per ontology digest. It must
restore at least v3's verifier coverage before resource savings count.

Two setup failures were excluded before the scored pair. A separate 64-call
Mithril run also failed infrastructure validation: `podman-compose` rejected
every `exec -it` and then could not copy the verifier tests. Its 50 failed
bash actions and unrun verifier are **unmeasured**, despite recorded model
usage. The versioned `docker-podman-compat.py` shim was added; the oracle
control then passed reward 1.0 before the valid 24-call pair ran. This is why
the harness requires both an oracle-positive control and verifier evidence.

Local Harbor result JSON SHA-256 digests (raw prompts and task artifacts stay
local): baseline `8d92b29d562e85ea1211b489f749044aff05d4e9d1a649aa5c9973c7cea2a0e6`,
Mithril `3e1c2a34342dcd156fc2410361990cc2cf4a37a9305e93c1e611cf6000d35f06`,
oracle `1fb4c13e2c712aa74145abe1397ee9587e77ae83e16c8969bebe0245966164c9`.
