"""Co-scientist rank and meta-review over micro-loop reports that share seeds.

  python3 harness/attack/tournament.py <report.json>... [--json out.json]

Rank: for every seed and lane pair, the lane with the higher verifier score
(passed / total) wins; equal scores go to the lower cost; equal both is a
draw. Unmeasured rows (deadline, error without a verifier result) are left
out, and so is their pair. Elo (K=16, start 1500) is averaged over 200 fixed
random orderings of the matches, so the ranking does not depend on the order
the loops ran in.

Meta-review: failed assertions are tallied per lane. Each group becomes a
candidate failure case with its evidence (lane, seeds). Candidates are
proposals: they enter a knowledge pack only after the next generation shows,
on held-out seeds, that the lane carrying them does better.
"""

import argparse
import collections
import itertools
import json
import random


def matches(rows):
    by_seed = collections.defaultdict(dict)
    for r in rows:
        if 'passed' in r and r.get('status') in ('scored', 'timeout'):
            by_seed[r['seed']][r['lane']] = r
    out = []
    for seed in sorted(by_seed):
        for a, b in itertools.combinations(sorted(by_seed[seed]), 2):
            ra, rb = by_seed[seed][a], by_seed[seed][b]
            sa, sb = ra['passed'] / ra['total'], rb['passed'] / rb['total']
            if sa != sb:
                result = 1.0 if sa > sb else 0.0
            elif (ra.get('cost_usd') or 0) != (rb.get('cost_usd') or 0):
                result = 1.0 if (ra.get('cost_usd') or 0) < (rb.get('cost_usd') or 0) else 0.0
            else:
                result = 0.5
            out.append((seed, a, b, result))
    return out


def elo(match_list, lanes, orderings=200, k=16.0):
    totals = {lane: 0.0 for lane in lanes}
    rng = random.Random(20260925)
    for _ in range(orderings):
        ratings = {lane: 1500.0 for lane in lanes}
        order = match_list[:]
        rng.shuffle(order)
        for _, a, b, result in order:
            expected = 1 / (1 + 10 ** ((ratings[b] - ratings[a]) / 400))
            ratings[a] += k * (result - expected)
            ratings[b] -= k * (result - expected)
        for lane in lanes:
            totals[lane] += ratings[lane]
    return {lane: round(totals[lane] / orderings, 1) for lane in lanes}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('reports', nargs='+')
    parser.add_argument('--json')
    args = parser.parse_args()
    rows = []
    for path in args.reports:
        rows += json.load(open(path))['rows']
    lanes = sorted({r['lane'] for r in rows})
    match_list = matches(rows)
    wins = {a: {b: 0.0 for b in lanes if b != a} for a in lanes}
    for _, a, b, result in match_list:
        wins[a][b] += result
        wins[b][a] += 1 - result
    per_lane = {}
    for lane in lanes:
        mine = [r for r in rows if r['lane'] == lane]
        measured = [r for r in mine if 'passed' in r and r.get('status') in ('scored', 'timeout')]
        per_lane[lane] = {'trials': len(mine), 'measured': len(measured),
                          'successes': sum(bool(r.get('success')) for r in measured),
                          'mean_score': round(sum(r['passed'] / r['total'] for r in measured) / len(measured), 4) if measured else None,
                          'cost_usd': round(sum(r.get('cost_usd') or 0 for r in mine), 6)}
    ratings = elo(match_list, lanes)
    candidates = collections.defaultdict(lambda: {'lanes': collections.Counter(), 'seeds': set()})
    for r in rows:
        for assertion in r.get('failed_assertions') or []:
            key = assertion.split('_', 1)[1] if '_' in assertion else assertion
            candidates[key]['lanes'][r['lane']] += 1
            candidates[key]['seeds'].add(r['seed'])
    proposals = [{'failed_check': key, 'lanes': dict(v['lanes']), 'seeds': sorted(v['seeds']),
                  'status': 'candidate (not admitted; needs held-out evidence)'}
                 for key, v in sorted(candidates.items(), key=lambda kv: -sum(kv[1]['lanes'].values()))]
    out = {'matches': len(match_list), 'ranking': sorted(ratings.items(), key=lambda kv: -kv[1]),
           'wins': wins, 'lanes': per_lane, 'meta_review_candidates': proposals}
    if args.json:
        json.dump(out, open(args.json, 'w'), indent=2)
    print(json.dumps(out, indent=2))
    if not match_list:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
