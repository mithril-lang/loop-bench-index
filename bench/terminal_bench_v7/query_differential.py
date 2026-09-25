#!/usr/bin/env python3
"""Compare independent source-RDF rows with generated graph and two SPARQL files.

Exit 0 means both queries matched a nonempty source-derived result, 1 means a
measured difference, and 2 means the check could not run. No verifier data or
reference solution is read.
"""

import argparse
import json
import subprocess
import sys
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

from rdflib import Graph
from rdflib.compare import to_canonical_graph

from source_expected import expected, source_graph

QUERIES = ('cross_border_operational_points.rq', 'qualified_cross_border_points.rq')
COLUMNS = (('latitude', 'longitude', 'countryCount', 'adjacentSectionCount'),
           ('opId', 'countryCount', 'vehicleCount', 'highSpeedCount', 'maxVoltageKv'))


def normalized(row, query_index):
    values = []
    for index, value in enumerate(row):
        if value is None:
            raise ValueError('unbound SPARQL column')
        if query_index == 1 and index == 0:
            values.append(str(value))
        else:
            try:
                values.append(str(Decimal(str(value)).normalize()))
            except (InvalidOperation, ValueError) as exc:
                raise ValueError(f'non-numeric value in column {index}: {value}') from exc
    return tuple(values)


def check(target, candidate, execute):
    if execute:
        command = [sys.executable, str(candidate / 'pipeline.py'), str(target)]
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f'pipeline exited {result.returncode}: {result.stderr[-2000:]}')
    expected_rows = expected(target)
    source = source_graph(target)
    if expected_rows['source_triples'] == 0 or not expected_rows['query1'] or not expected_rows['query2']:
        raise RuntimeError('source scan or independent expected rows are empty')
    unified_path = target / 'unified.ttl'
    if not unified_path.is_file():
        raise RuntimeError(f'unified graph missing: {unified_path}')
    unified = Graph().parse(unified_path, format='turtle')
    # Canonical blank-node identifiers let us check source subgraph retention
    # after Turtle serialization changes the parser's local BNode names.
    missing_source = set(to_canonical_graph(source)) - set(to_canonical_graph(unified))
    if missing_source:
        raise RuntimeError(f'generated graph dropped {len(missing_source)} source triples')
    report = {'status': 'match', 'scanned_source_triples': len(source),
              'source_triples_preserved': len(source), 'generated_triples': len(unified),
              'queries_executed': 0, 'queries': {}}
    for query_index, (name, columns) in enumerate(zip(QUERIES, COLUMNS)):
        path = candidate / name
        if not path.is_file():
            raise RuntimeError(f'query missing: {path}')
        result = unified.query(path.read_text())
        actual_columns = tuple(map(str, result.vars))
        if actual_columns != columns:
            raise RuntimeError(f'{name}: columns {actual_columns} != {columns}')
        key = f'query{query_index + 1}'
        expected_counter = Counter(normalized(row, query_index) for row in expected_rows[key])
        actual_counter = Counter(normalized(row, query_index) for row in result)
        missing = list((expected_counter - actual_counter).elements())
        extra = list((actual_counter - expected_counter).elements())
        report['queries_executed'] += 1
        report['queries'][name] = {'expected_rows': sum(expected_counter.values()),
                                   'actual_rows': sum(actual_counter.values()),
                                   'missing': missing, 'extra': extra}
        if missing or extra:
            report['status'] = 'mismatch'
    report['provenance'] = expected_rows['provenance']
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('target', type=Path)
    parser.add_argument('--candidate', type=Path, default=Path(__file__).parent / 'candidate')
    parser.add_argument('--execute', action='store_true', help='run the candidate pipeline first')
    args = parser.parse_args()
    try:
        report = check(args.target, args.candidate, args.execute)
    except Exception as exc:
        print(json.dumps({'status': 'unmeasured', 'reason': str(exc), 'queries_executed': 0}, indent=2))
        return 2
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'match' else 1


if __name__ == '__main__':
    raise SystemExit(main())
