"""Paired comparison of micro-loop reports that share seeds.

  python3 harness/micro/compare.py <report.json>... [--json out.json]

Pairs are (seed, lane). Only rows whose status is `scored` or `timeout`, and
which have verifier results, count as measured. A seed enters a lane-pair
comparison only when both lanes are measured on it; excluded seeds are
listed. For success, the exact two-sided sign test on discordant pairs
(McNemar exact) is reported. With n this small it detects only large
effects, and a non-significant result is not evidence of no effect.
"""

import argparse
import itertools
import json
import math
import statistics
import sys


def exact_sign_p(b, c):
    n = b + c
    if n == 0:
        return None
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('reports', nargs='+')
    parser.add_argument('--json')
    args = parser.parse_args()
    rows, loops = [], []
    for path in args.reports:
        report = json.load(open(path))
        loops.append({'report': path, 'loop_wall_seconds': report['loop_wall_seconds'], 'seeds': report['seeds']})
        rows += report['rows']
    measured = {(r['lane'], r['seed']): r for r in rows
                if r.get('status') in ('scored', 'timeout') and 'passed' in r}
    lanes = sorted({r['lane'] for r in rows})
    seeds = sorted({r['seed'] for r in rows})
    per_lane = {}
    for lane in lanes:
        mine = [measured[(lane, s)] for s in seeds if (lane, s) in measured]
        allrows = [r for r in rows if r['lane'] == lane]
        cost = sum(r.get('cost_usd') or 0 for r in allrows)
        succ = sum(bool(r['success']) for r in mine)
        prompt = sum((r.get('uncached_input_tokens') or 0) + (r.get('cache_read_tokens') or 0) for r in allrows)
        per_lane[lane] = {
            'trials': len(allrows), 'measured': len(mine),
            'not_measured': sorted((r['seed'], r.get('status')) for r in allrows if (lane, r['seed']) not in measured),
            'successes': succ,
            'success_rate': round(succ / len(mine), 4) if mine else None,
            'mean_assertion_fraction': round(statistics.mean(r['passed'] / r['total'] for r in mine), 4) if mine else None,
            'finished_rate': round(sum(bool(r.get('finished')) for r in mine) / len(mine), 4) if mine else None,
            'timeouts': sum(r.get('status') == 'timeout' for r in allrows),
            'cost_usd': round(cost, 6),
            'cost_per_success_usd': round(cost / succ, 6) if succ else None,
            'median_trial_wall_seconds': statistics.median(r['trial_wall_seconds'] for r in mine) if mine else None,
            'median_steps': statistics.median(r.get('steps') or 0 for r in mine) if mine else None,
            'cache_hit_ratio': round(sum(r.get('cache_read_tokens') or 0 for r in allrows) / prompt, 4) if prompt else None,
            'output_tokens': sum(r.get('output_tokens') or 0 for r in allrows),
        }
    pairs = {}
    for a, b in itertools.combinations(lanes, 2):
        common = [s for s in seeds if (a, s) in measured and (b, s) in measured]
        only_a = sum(1 for s in common if measured[(a, s)]['success'] and not measured[(b, s)]['success'])
        only_b = sum(1 for s in common if measured[(b, s)]['success'] and not measured[(a, s)]['success'])
        diffs = [measured[(b, s)]['passed'] / measured[(b, s)]['total'] - measured[(a, s)]['passed'] / measured[(a, s)]['total']
                 for s in common]
        cost_diffs = [(measured[(b, s)].get('cost_usd') or 0) - (measured[(a, s)].get('cost_usd') or 0) for s in common]
        pairs[f'{a} vs {b}'] = {
            'paired_seeds': len(common), 'excluded_seeds': [s for s in seeds if s not in common],
            f'success_only_{a}': only_a, f'success_only_{b}': only_b,
            'mcnemar_exact_p': exact_sign_p(only_a, only_b),
            f'mean_assertion_fraction_diff_{b}_minus_{a}': round(statistics.mean(diffs), 4) if diffs else None,
            f'mean_cost_diff_usd_{b}_minus_{a}': round(statistics.mean(cost_diffs), 6) if cost_diffs else None,
        }
    out = {'loops': loops, 'seeds': seeds, 'lanes': per_lane, 'pairs': pairs}
    if args.json:
        json.dump(out, open(args.json, 'w'), indent=2)
    print(json.dumps(out, indent=2))
    if not measured:
        print('SCANNED\t0 measured rows', file=sys.stderr)
        raise SystemExit(2)


if __name__ == '__main__':
    main()
