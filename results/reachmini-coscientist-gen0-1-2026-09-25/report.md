# reachmini co-scientist generations 0–1: graph toolkit and knowledge packs

Date: 2026-09-25. The question: does giving the agent graph tooling and more
ontology knowledge (domain rules and observed failure cases) make it better
at a multi-hop reachability task? The task family is reachmini
(`harness/attack/reachmini.py`), a synthetic, defensive exposure analysis.
Given hosts, roles and data stores split across RDF sources, the agent must
find which exposed entry hosts reach sensitive data stores, and in how few
hops. The reference solution passes every level. Removing any single trap
handling fails at the levels where that trap exists
(`harness/tests/test_reachmini.py`).

All runs used `openai/gpt-6-luna` at medium reasoning through the chat
transport, with a 20-step cap and loops of at most 10 minutes. Rows are in
`runs.json`; ranking and paired statistics are in the JSON files beside this
report.

## Lanes (generation 0 hypotheses)

| Lane | Adds |
|---|---|
| `react` | nothing (baseline) |
| `graph` | `/opt/harness/graphkit.py`: RDF loading, subclass-aware instance lookup, BFS, no task rules |
| `domain` | Mithril-compiled `reach-domain` pack (v1 in gen 0, v2 in gen 1): algorithm, policy, data and check rules |
| `failures` | Mithril-compiled `failure-cases-v1` pack: 8 observed failure cases with evidence, 4 anticipated ones |
| `combined` | both packs and the toolkit |

Packs go into the static task message, so with the append-only chat
transport they sit in the cached prefix.

## Results

| Generation | Knobs | Seeds | Outcome |
|---|---|---|---|
| 0 | depth 6, size 30, noise 0 (rules explicit) | 2 | every lane 7/7 |
| 0 | depth 6, size 30, noise 2 (explicit rules + name variants) | 2 | every lane 7/7 |
| 1 | depth 8, size 60, noise 2 | 4 | every lane 7/7 |
| 1 | depth 8, size 60, noise 3 (rules only in ontology comments and data; names linked by aliases) | 12 | table below |

Loops took 95–200 s. Trials cost about $0.002–0.012 each.

At noise 3 over 12 paired seeds:

| Lane | Success | Mean score | Cost per success | Elo |
|---|---:|---:|---:|---:|
| react | 11/12 | 0.95 | $0.0073 | 1526 |
| graph | 11/12 | 0.95 | $0.0072 | 1545 |
| failures | 10/12 | 0.93 | $0.0080 | 1491 |
| domain | 9/12 | 0.88 | $0.0087 | 1455 |
| combined | 7/12 | 0.76 | $0.0112 | 1483 |

Paired exact McNemar tests against `react`:
- `combined` 0:4 discordant, p = 0.125
- `domain` 1:3, p = 0.625
- `failures` 1:2, p = 1.0
- `graph` 1:1, p = 1.0

None is significant. The direction is consistent: the more knowledge a lane
carries, the lower its success rate.

## Meta-review

- **Structural multi-hop reasoning is not where the agent fails.** Whenever
  the rules are explicit, every lane writes a BFS in its solver and succeeds.
  The graph toolkit adds nothing measurable, because the model already turns
  graph reasoning into code.
- **Failures are identity and authority errors.** The final `solve.py` of
  every failed trial was saved and re-run. Most failures under-count roles
  and data stores: a host-to-role edge was lost because the host resolved to
  the wrong node. In the failed `domain` trial on seed 522, the alias table
  was built from every `rc:Host` node, including the network and IAM
  sources' own host nodes. The successful `react` solution on the same seed
  restricted it to inventory hosts. This is the observed failure case
  FC-03 (identity split), and it was in the pack.
- **General knowledge text did not prevent the failure it describes, and may
  hurt.** The domain pack's identity rule ("join by the normalized name the
  task defines") fits noise 2, not the alias-based noise 3. Longer guidance
  also coincided with more general, more complex joins. This is a
  hypothesis; the data shows only the direction, not the mechanism.

## Proposed generation 2 (not yet run)

1. **Data-grounded schema card instead of generic text.** A deterministic
   probe of the environment's own ontology and data lists which classes each
   source uses, which properties carry `rdfs:comment` rules, where aliases
   are declared, and how many referenced names resolve to exactly one
   authoritative entity. This is ontology information computed from the task
   data, not written in advance.
2. **Executable invariants from the failure cases.** Turn FC-03 into a
   harness check that runs after each modify: every host referenced in any
   source resolves to exactly one inventory host, and the count of
   unresolved references is reported. This targets the meaning error the
   form-only checks missed.
3. **Domain pack v3** without the rule that assumes a stated normalization.
4. Admit the new candidate failure case (inventory is the authority for
   identity) only if a lane carrying it improves on held-out seeds.
