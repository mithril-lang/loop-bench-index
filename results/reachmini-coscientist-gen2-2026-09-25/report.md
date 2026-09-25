# reachmini co-scientist generation 2: data-grounded schema card and executable invariants

Date: 2026-09-25. Generation 1's meta-review found that failures at noise 3
were identity and authority errors. It also found that general knowledge
text did not prevent them, even when the failure case was in the pack.
Generation 2 tests the alternative: information computed from the task's own
data, and failure cases turned into executable checks.

The task: reachmini, depth 8, size 60, noise 3. Rules live only in ontology
comments and data values, and names are linked through inventory aliases.
There were 12 new seeds (531–542) run in two loops of 30 trials (164 s and
174 s), plus a one-seed pilot. The model was `openai/gpt-6-luna` at medium
reasoning through the chat transport, with a 20-step cap.

## New lanes

| Lane | Adds |
|---|---|
| `schema` | `schema_probe.py card`: per-source classes and properties (subclasses rolled up), ontology `rdfs:comment`s, singleton-class parameters, and, for classes named in several sources, the source that resolves the most names used elsewhere with a resolution table. Describes the data; computes no answer. |
| `invariants` | After each modify, the harness runs `solve.py` and `schema_probe.py check-reach`, with necessary conditions from failure case FC-03: output host names are authority names; every entry host is listed; an entry host that runs as a role reaches at least one role. |
| `grounded` | both |
| `domain-v3` | reach-domain pack with the identity rule rewritten (no assumed normalization) |

Before use, the check was validated on generation 1's saved final
solutions. It passes the reference solution and flags 6 of the 7 failed
trials on the target environment; the seventh failed only on the hidden
environment. The first version of the card named the wrong authority,
because entry hosts are typed with a subclass. It was fixed to roll up
subclasses and to choose the reference by resolution before any run.

## Results (12 paired seeds)

| Lane | Success | Mean score | Cost per success | Median wall | Elo |
|---|---:|---:|---:|---:|---:|
| invariants | 12/12 | 1.000 | $0.0065 | 108 s | 1518 |
| schema | 11/12 | 0.976 | $0.0066 | 105 s | 1553 |
| grounded | 11/12 | 0.964 | $0.0062 | 93 s | 1544 |
| react | 11/12 | 0.964 | $0.0072 | 99 s | 1491 |
| domain-v3 | 11/12 | 0.952 | $0.0096 | 130 s | 1393 |

No pair differs significantly (paired exact McNemar p ≥ 1.0 or undefined).
This seed set was easier than generation 1's (`react` 11/12 in both), so
success is near the ceiling.

## Mechanism: the invariant check catches and corrects the failure mode

The check reported violations in 17 of the 24 `invariants` and `grounded`
trials. In 16 of those, the agent then fixed its solver and finished with
every assertion passing. The violations were:

- "entry host … runs as a role but reports 0 reachable roles" — the
  identity split behind generation 1's failures;
- "entry hosts missing from blast_radius.tsv";
- early runs of incomplete code.

On seed 540, `react` failed (4/7), while both check-carrying lanes were
flagged for 0 reachable roles and then passed. The one check-carrying
failure (`grounded` 542) passed the check at its end: the check is necessary,
not sufficient.

Post hoc, the same check was run on every lane's final solution on the
target environment. Only one trial still carried the identity split at the
end (`domain-v3` 542); it is also that lane's failure.

## Meta-review

- The failure mode is the same as in generation 1. It is now caught while
  the agent can still act, but the success-rate gain cannot be measured at
  this ceiling.
- Information computed from the data (the card) costs no more than the
  baseline and ranked highest by Elo. Generic knowledge text (`domain-v3`)
  is the slowest and most expensive lane, although the rewritten identity
  rule no longer shows the generation-1 drop (unpaired comparison).
- **Candidate admitted with status "mechanism supported, effect on success
  unmeasured":** executable invariant FC-03.
- Next generation: raise difficulty so baseline success falls to about
  50–70% while keeping noise 3. Candidates are more sources with
  conflicting authority (recency decides), alias collisions, and larger
  depth and size. Then measure whether the check-carrying lanes' recovery
  converts into a success difference.
