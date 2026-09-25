# Mithril harness: co-scientist derivation of the target model

Date: 2026-09-25. This is a design derivation, not a benchmark result. It
applies the co-scientist cycle (generate → review → rank → evolve →
meta-review) to the question "which agent-loop model should the Mithril
harness converge to?". The judge in the review step is **measured evidence
already in this repository**. Where no evidence exists, the entry says
*unmeasured*; it is not scored. Inputs were the [co-scientist loop
analysis](coscientist-loop-analysis-2026-09-25.md), the v5–v8 reports, and two
externally proposed architectures supplied with the request: a Jev System-1 /
POMDP / best-first proposal, and a typed belief-graph runtime with L0–L3 graphs,
an AND/OR search, and an "LLM-sparse" objective. The resulting model is the
best-supported design, not a proven optimum. Section 6 lists what must be
measured before any part of it can be called optimal.

## 1. Evidence base

| # | Evidence | Value | Source |
|---|---|---|---|
| E1 | Agent-lane verifier outcome on `ontology-kg-querying` | 9/13 in every lane (v6d, v7 Jev, no-knowledge, knowledge). No agent success | v7, sequential reports |
| E2 | What discriminated right from wrong rows | Only a source-derived differential; the fixed candidate reached 13/13 (nonblind) | v8 report |
| E3 | Knowledge supplied as retrievable text | No accuracy change; ≥2.69× tokens, 2.82× wall | sequential report |
| E4 | Jev choice distribution | 39/39 `independent_check`; the request instruction said "Prefer an independent result check" | v7 report, `jev_interleave.py` |
| E5 | Unit cost per call, v7 | Luna ≈ 61,141 tokens and $0.005495 per Hermes call; Jev ≈ 1,328 tokens, $0.0000528, 0.232 s. That is 46× fewer tokens and 104× lower cost per Jev call | derived from v7 report totals |
| E6 | Are logged actions choosable from a finite set? | 146 inspect/modify/verify actions in 7 local receipts (v6, v7, sequential pair): **0 exact repeats**; median command 900 chars, p90 3,216. A coarse template key (program + script path + heredoc) repeats 69/146 — a loose upper bound | measured on local receipts, this document |
| E7 | Cutting replayed history alone | v4: −89% history chars, both lanes stuck in `inspect`, no artifact | v4 report |
| E8 | Cost of the symbolic layer | Mithril helper 222–465 s per trial (17–25% of agent wall); ~36 s per action otherwise | v7 report |
| E9 | Mithril's own action model | The runtime defines a typed semantic delta (`assert / retract / query / infer / compile / stop`) and notes that a Jev-like policy may select operation and arguments without a text decoder | `mithril-lang/mithril` README |
| E11 | Differential judge as an agent lane (admission pair, one trial each) | 9/13 in both lanes. The judge passed twice while the verifier failed: the derivation shared the answer's error. Judge lane: 69% of tokens, 74% of cost, 32 vs 48 steps, with equal failure | [judge-a report](harness-judge-a-2026-09-25/report.md) |
| E12 | Typed action coverage (rung 2) | 218 model actions in 9 receipts: pure 45 (strict) – 127 (signature); inspect 68/104, verify 59/81, modify 0/33 pure. `acceptance-check` is the largest operation (74 segments). Hand check 27/30 agree | [coverage report](typed-action-coverage-2026-09-25/report.md) |
| E10 | Co-scientist judges in this workspace | `yui/coscientist.kotoba` and `sha256d/evolve.cljk` rank with deterministic Elo whose fitness is a measurement, never an LLM debate | those repositories |

Two claims in the supplied material were **not** used as evidence. TypeSafe's
published speed/cost multipliers are vendor-reported; the vendor says they are
likely high for real workflows. E5 replaces them with our own metered values.
The second proposal cites a "Mithril" security service and its tool-call
execution policy. That is a different product from `mithril-lang`. Neither
citation describes this harness.

## 2. Generate: candidate models

| id | Model | Origin |
|---|---|---|
| H0 | ReAct + Mithril gates (prefill, OWL/SHACL task state, BPMN, critical review) | current `mithril` lane |
| H1 | H0 + measured judge: harness-run differential gates finish | analysis §3.2, `judge` lane |
| H2 | Jev System-1 chooses next action among tools; LLM only when uncertain | proposal 1 |
| H3 | Typed action IR: harness-generated parameterized operations; LLM authors only artifacts and derivations | proposal 2 §3, E9 |
| H4 | Typed belief graph L0–L3 + event graph; context = goal-local subgraph instead of transcript | proposal 2 §4–5 |
| H5 | AND/OR goal graph searched best-first with Jev as heuristic h(n) | proposal 1, proposal 2 §6 |
| H6 | Co-scientist population: competing candidates, Elo on discriminating rows, recombination | analysis §2 |
| H7 | System-dynamics / budget meta-controller (explore / reason / stop pressure) | proposal 2 §7 |
| H8 | Cost-sensitive POMDP policy: argmax of P(success) + IG − λ·tokens − μ·time | proposal 1 |

## 3. Review against the evidence

- **H0** — measured: 9/13 (E1). Baseline. Every other candidate must beat it on
  success before cost.
- **H1** — supported in mechanism (E2), but **insufficient as a judge by
  itself** (E11). In the admission pair, the agent's own derivation agreed with
  its wrong answer twice (6 and 2 rows). The verifier then failed the same four
  assertions. A self-built agreeing derivation is weak evidence. It becomes a
  judge only when paired with a source of disagreement that does not come from
  the same reading of the task (H3's axiom-delta alternatives, H6's population).
- **H2 as stated** — **refuted for this loop.** Choosing among tools presupposes
  a finite action set. E6 shows every action was a newly generated command,
  so there was no earlier command to pick again. Jev is cheap (E5), but if
  nothing is choosable it saves nothing. Revived only on top of H3.
- **H3** — required by H2/H5/H8 and anticipated by Mithril (E9). Measured
  (E12): a generic 20-operation library expresses 20.6–58.3% of 218
  model-chosen actions without model-written text. Most pure verify actions
  are one composite acceptance check that needs no choice at all.
- **H4** — the goal is right, but E7 limits it. Shrinking context without
  carrying the state it held failed. A subgraph context is admissible only
  after the belief graph demonstrably holds what the transcript held:
  hypotheses, refutations, artifact state, and last differential rows. The L0–L3
  separation fits existing Mithril boundaries: ontology (L0), RDF task state
  (L1), `.mith` hypotheses (L2), BPMN/receipts (L3).
- **H5** — structurally correct. Acceptance is an AND of goals: each required
  artifact × judge pair × SHACL. Solutions are an OR over candidates. A learned
  h(n) is not admissible, so this is best-first search with no A*/AO*
  optimality guarantee. Needs H3 (typed edges) and a judge (H1) to score leaves.
- **H6** — the OR-nodes of H5 *are* the co-scientist population. It needs H1's
  judge; without one, E1/E3 show more candidates only add cost.
- **H7** — premature. With zero solved tasks, the stop and budget pressures have
  no success-qualified signal to regulate. Solved/tokens = 0 in every lane.
- **H8** — the right objective form, but its terms have unequal status.
  - IG: deterministically computable once candidates exist (rows each
    experiment would split).
  - Token and time costs: measurable per action type from receipts (E5, E8).
  - P(success) from Jev: **uncalibrated**. The v7 0.6 threshold was never
    calibrated, and E4 shows the distribution was prompt-driven. Until
    calibration exists, P(success) is set to α = 0.

## 4. Rank

The order is lexicographic and fixed before scoring:

1. Acts on the binding constraint.
2. Its prerequisites are measured.
3. It lowers LLM calls.

Criterion 1 comes first because solved/tokens is 0/x for every lane (E1).
While success is zero, no cost reduction can raise token efficiency, and an
LLM-sparse objective "min N_LLM s.t. P(correct) ≥ τ" is infeasible until τ is
met at least once.

| Rank | Candidate | 1: binding constraint | 2: prerequisites measured | 3: fewer LLM calls |
|---|---|---|---|---|
| 1 | H3 typed action IR, incl. axiom-delta alternatives | yes: supplies disagreement H1 lacked (E11) | coverage measurable offline | yes, bounded by coverage |
| 2 | H6 population on OR-nodes, forced to differ in interpretation | yes, with H1 as leaf score | H1 implemented; agreement ≠ correctness (E11) | no |
| 3 | H1 judge as leaf score (not finish permission) | necessary, not sufficient (E11) | implemented, measured once | no (adds steps) |
| 4 | H5 best-first AND/OR | yes, given H1+H3 | needs H3 | yes |
| 5 | H8 policy (IG + costs, α=0 until calibrated) | indirect | IG/cost yes, P no | yes |
| 6 | H4 belief-graph context | no (cost) | needs state-carriage proof (E7) | yes (tokens) |
| 7 | H2 Jev over typed actions | no (cost) | needs H3 + calibration | yes |
| 8 | H7 budget controller | no | needs solved pairs | yes |
| — | H2 as stated | refuted (E6) | — | — |

## 5. Evolve: the synthesized model M*

**State.** B_t = (O, W_t, H_t, S_t, P), kept as separate Mithril graphs:

| Symbol | Contents | Existing Mithril mechanism |
|---|---|---|
| O | L0 ontology: source schema, action ontology, task goals | OWL 2 RL closure, cached per digest |
| W_t | L1 world facts: files, source triples, executed-query rows | RDF task state |
| H_t | L2 beliefs: candidate hypotheses and candidate artifacts with weights | `.mith` hypothesis nodes, SHACL-admitted |
| S_t | L3 search/event record: action, result, cost, parent | BPMN receipts |
| P | Provenance of every node | graph digests |

**Goal graph.**
- **AND**: every required artifact is produced, and each answer pair passes the
  judge and the result-shape SHACL.
- **OR**: under each AND child, the competing candidates. These are the
  co-scientist population, and equivalently the belief particles of the POMDP
  view of H8.

**Actions.** A = A_typed ∪ A_llm.
- A_typed is harness-generated from the O/W_t vocabulary: run a query over a
  bundle, show the rows two candidates disagree on, compute an axiom row-delta
  under OWL RL, run the differential, run SHACL. No model tokens.
- A_llm has exactly three expansions:
  1. author or repair a candidate artifact;
  2. author the independent derivation;
  3. propose a new hypothesis when the typed set has no discriminating
     experiment.

**Judge and ranking.**
- A leaf's value is measured: execution, source preservation, SHACL, and the
  differential (exit 0/1/2). A differential exit 0 is a leaf score, not
  permission to finish (E11). Finish also requires that no surviving
  OR-candidate with a different interpretation passes the same checks with
  different rows.
- OR-children are ranked by deterministic Elo on the discriminating rows
  (port `yui/coscientist.kotoba`).
- An LLM tie-break is allowed only when labelled as one.

**Policy.** a* = argmax over enabled BPMN actions of

Q(a) = α·P̂(success | a) + β·IG(a) + γ·ΔAND(a) − λ·tokens(a) − μ·time(a) − ν·refusal-risk(a)

- IG = expected number of OR-candidates eliminated. It is computed from
  candidate row sets; no model is needed.
- tokens and time are per-action-type medians from receipts (E5, E8).
- α = 0 until Jev's P̂ is calibrated on logged decisions against later judge
  outcomes. Only then does Jev become h(n).
- The LLM is called only when the best Q comes from an A_llm action, or when no
  A_typed action has positive IG. This is the "LLM-sparse" rule, stated as a
  condition the harness can check.

**Context.** Each A_llm call receives the goal-local subgraph of B_t plus the
last judge report, and not the full transcript. This is admitted only after the
state-carriage test in H4 passes.

**Stop.**
- Finish when every AND child has an OR child with judge exit 0 and unchanged
  artifacts, and every competing interpretation on that child has been refuted
  by a source-grounded row difference.
- Otherwise, when the budget is exhausted, submit the Elo leader and record why.

A budget controller (H7) is added only once success-qualified costs exist.

## 6. Meta-review: admission ladder and falsification

The harness lane registry (`harness/mithril_harness/lanes.py`) encodes this
ladder. The runner refuses a `PLANNED` lane until its prerequisite is recorded.

| Step | Lane | Prerequisite (measured before admission) | Falsified if |
|---|---|---|---|
| 1 | `judge` (H1) | implemented; admission pair run | judge exit 0 while the verifier fails. **Observed on the admission pair (E11).** Kept as a leaf score only |
| 2 | `typed-actions` (H3) | offline coverage by the typed library. **Measured: 20.6% (strict) – 58.3% (signature) of 218 model actions pure** ([report](typed-action-coverage-2026-09-25/report.md)) | coverage too low to remove any LLM call. Not falsified; first sub-lane `auto-acceptance` (a deterministic acceptance check after every modify) needs no policy |
| 3 | `population` (H6) | judge–verifier agreement from step 1 | on held-out tasks, no success gain over `judge` at a matched token budget |
| 4 | `jev-policy` (H2 on H3, H5, H8) | typed coverage; Jev calibration error on logged decisions | success lower than step 3, or LLM calls not reduced |
| 5 | `belief-context` (H4) | state-carriage test | success lower than the transcript context at equal budget |
| 6 | `budget-controller` (H7) | ≥1 solved matched pair | cost per solved task not reduced |

Metrics per lane:
- **Primary:** success rate with a task-clustered interval, on the predeclared
  held-out cohort.
- **Then:** LLM calls, tokens, and $ per solved task; wall time; typed vs LLM
  action counts; graph expansions; judge exit counts; judge–verifier agreement;
  Jev calibration error; recovery from error (an exit-1 differential later
  followed by exit 0).
- **Baselines:** `react` and `mithril`, same model, and at a matched budget for
  population lanes.
- `ontology-kg-querying` is contaminated, so it serves only as harness
  admission for each rung.

The next action that needs no model spend is rung 2's measurement. Define the
typed library from the Mithril action ontology, and classify the 146 logged
actions plus the 63 of the judge pair against it. Include in the library the
axiom-delta operation that turns one task reading into competing candidates.
E11 shows that source of disagreement is what the judge lacked.
