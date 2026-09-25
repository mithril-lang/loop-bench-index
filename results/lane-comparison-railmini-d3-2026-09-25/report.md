# Lane comparison on railmini level 3: react vs mithril vs auto-acceptance

Date: 2026-09-25. The model was `openai/gpt-6-luna` at medium reasoning,
through the chat transport (direct OpenRouter, append-only messages). Trials
used resident Mithril, a 20-step cap, a 540 s trial cap and a 590 s loop
deadline. Seeds were 401–412, shared across lanes (paired), run as three
loops of 4 seeds × 3 lanes = 12 concurrent trials. Rows are in `runs.json`;
the paired analysis (`harness/micro/compare.py`) is in `comparison.json`.
railmini success is not a Terminal-Bench score.

## First round: invalidated by two harness defects

The first round (`comparison-before-fixes.json`) showed `react` at 5/12,
`mithril` at 6/12 and `auto-acceptance` at 8/12. Two defects made it
unusable as a comparison:

1. **Parsing.** Six `react` trials returned `finish` as their first action,
   after 6.6K–14K output tokens, and scored 0/13. The parser took the *last*
   action object in a reply. A reply that wrote out a whole plan ending in
   `finish` was therefore executed as `finish`. The Mithril lanes refuse an
   early finish at their gates, so this defect hit `react` alone. After the
   fix, 20 `react` replies were found to contain more than one action.
2. **Runaway generation.** Two `mithril` trials timed out because a single
   request produced 65,536 output tokens over 401–475 s. The 120 s socket
   read timeout never fired. The abandoned request threads also held the
   process open about 290 s after the loop ended.

Fixes in `8863b8d`:
- The chat transport executes the first of several actions in one reply and
  counts it. The frozen Hermes path keeps the old behaviour for
  reproduction.
- Requests get `max_tokens` 16,384 and a wall-clock deadline run in a daemon
  thread.
- Raw replies are saved privately.
- The acceptance check gets its own span.

## Second round (after the fixes)

| | react | mithril | auto-acceptance |
|---|---:|---:|---:|
| Success (measured) | 9/11 | 9/12 | 8/12 |
| Mean assertion fraction | 0.979 | 0.949 | 0.936 |
| Finished within 20 steps | 10/11 | 4/12 | 8/12 |
| Cost (12 trials) | $0.115 | $0.176 | $0.172 |
| Cost per success | $0.0128 | $0.0195 | $0.0215 |
| Median trial wall | 237 s | 353 s | 396 s |
| Cache hit ratio | 0.881 | 0.901 | 0.896 |
| Replies with several actions | 20 | 6 | 7 |
| Length-capped calls / failed attempts | 0 / 0 | 0 / 0 | 2 / 0 |

- `react` seed 402 was cancelled at the loop deadline and is not measured;
  the two comparisons that involve `react` use 11 paired seeds.
- **No pair differs significantly on success.** The paired exact McNemar p
  is 1.0 (mithril vs auto-acceptance), 0.625 (react vs auto-acceptance) and
  1.0 (react vs mithril), from discordant pairs 4:3, 3:1 and 3:2.
- With 11–12 seeds, only differences of about 5 discordant pairs to 0 could
  reach p < 0.07. This is not evidence of no effect.
- Loop walls were 601, 395 and 584 s. The first loop ran 1 s past 600 s
  because cancellation and cleanup ran after the 590 s deadline. The
  default deadline is now 570 s. Process exit followed the loop within 2–4 s.

## What this says

- On this task family, the Mithril semantic layer and the auto-acceptance
  check did not improve success over plain `react`. They cost about 1.5× per
  success and ran 1.5–1.7× longer. The point estimates favour `react`, but
  none of the differences is significant.
- The earlier apparent deficit of `react` was a harness artifact. The
  last-action parse is also the frozen Hermes behaviour, so earlier Hermes
  baseline comparisons could carry the same artifact wherever the baseline
  had no finish gate. Those have not been re-examined.
- The Mithril lanes mostly stop at the step cap (4/12 finished) rather than
  finishing. The critical review and gates consume steps.
- `auto-acceptance` trials that timed out were waiting on the acceptance
  check itself (up to 313 s unaccounted in one trial): it runs the agent's
  pipeline on two bundles after every modify.
- Level 3 is now solved 67–82% of the time. To separate lanes, the next
  cohort needs a harder level or many more seeds; ~40 paired seeds per lane
  pair would be needed to detect a 20-point difference with reasonable
  power.
