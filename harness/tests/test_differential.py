"""Run: python3 -m unittest harness/tests/test_differential.py (no Harbor needed)"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mithril_harness.differential import (compare, coverage_gaps, independence_violations,
                          parse_rows, validate_submission)

OK = lambda text: {'exit_code': 0, 'stdout': text}


class Compare(unittest.TestCase):
    def test_match_is_exit_0(self):
        r = compare(OK('a\t1\nb\t2\n'), OK('b\t2.0\n<a>\t"1"\n'))
        self.assertEqual((r['exit'], r['reason']), (0, 'rows-match'))
        self.assertEqual((r['answer_rows'], r['derivation_rows']), (2, 2))

    def test_mismatch_is_exit_1_with_rows(self):
        r = compare(OK('a\t1\nc\t3\n'), OK('a\t1\nb\t2\n'))
        self.assertEqual((r['exit'], r['reason']), (1, 'row-mismatch'))
        self.assertEqual(r['missing'], [['b', '2']])
        self.assertEqual(r['extra'], [['c', '3']])

    def test_duplicate_count_boundary(self):
        # Same set, different multiplicity: exactly one row apart is a mismatch.
        r = compare(OK('a\na\n'), OK('a\n'))
        self.assertEqual((r['exit'], r['extra_count'], r['missing_count']), (1, 1, 0))

    def test_empty_sides_are_unmeasured_not_pass(self):
        self.assertEqual(compare(OK(''), OK(''))['reason'], 'answer-produced-no-rows')
        self.assertEqual(compare(OK('a'), OK('\n\n'))['reason'], 'derivation-produced-no-rows')
        self.assertEqual(compare(OK(''), OK(''))['exit'], 2)

    def test_failed_commands_are_unmeasured(self):
        r = compare({'exit_code': 1, 'stdout': 'a'}, OK('a'))
        self.assertEqual((r['exit'], r['reason']), (2, 'answer-command-failed'))
        r = compare(OK('a'), {'exit_code': 124, 'stdout': 'a'})
        self.assertEqual((r['exit'], r['reason']), (2, 'derivation-command-failed'))

    def test_numeric_canonicalization(self):
        self.assertEqual(parse_rows('1.50\t10\t1e1'), [('1.5', '10', '10')])


REQUIRED = ['/app/q1.rq', '/app/pipeline.py']
PAIR = {'name': 'q1', 'answer_command': 'python3 /app/run.py /app/q1.rq /app/data/unified.ttl',
        'derivation_command': 'python3 /app/derive_q1.py /app/data',
        'answer_paradigm': 'SPARQL over unified graph',
        'derivation_paradigm': 'Python over source Turtle'}


class Independence(unittest.TestCase):
    def test_clean_pair_passes(self):
        self.assertEqual(independence_violations(PAIR, REQUIRED, {'/app/derive_q1.py': 'import rdflib'}), [])

    def test_derivation_script_reading_answer_query_is_refused(self):
        reasons = independence_violations(PAIR, REQUIRED, {'/app/derive_q1.py': "open('/app/q1.rq')"})
        self.assertIn('derivation-file-mentions:/app/derive_q1.py:q1.rq', reasons)

    def test_derivation_reading_answer_graph_is_refused(self):
        pair = dict(PAIR, derivation_command='python3 /app/derive_q1.py /app/data/unified.ttl')
        self.assertIn('derivation-command-mentions:unified.ttl',
                      independence_violations(pair, REQUIRED, {}))

    def test_same_paradigm_is_refused(self):
        pair = dict(PAIR, derivation_paradigm=' sparql over UNIFIED graph ')
        self.assertIn('paradigm-not-distinct', independence_violations(pair, REQUIRED, {}))

    def test_identical_commands_are_refused(self):
        pair = dict(PAIR, derivation_command=PAIR['answer_command'])
        self.assertIn('derivation-identical-to-answer', independence_violations(pair, REQUIRED, {}))


class Coverage(unittest.TestCase):
    def test_uncovered_required_artifact_is_a_gap(self):
        self.assertEqual(coverage_gaps([PAIR], [], REQUIRED), ['/app/pipeline.py'])

    def test_declared_with_reason_closes_gap(self):
        self.assertEqual(coverage_gaps([PAIR], [{'path': '/app/pipeline.py', 'reason': 'builds the graph'}], REQUIRED), [])

    def test_declared_without_reason_does_not(self):
        self.assertEqual(coverage_gaps([PAIR], [{'path': '/app/pipeline.py', 'reason': ' '}], REQUIRED), ['/app/pipeline.py'])


class Submission(unittest.TestCase):
    def test_shape_refusals_are_literal(self):
        self.assertEqual(validate_submission(None)[2], 'differential-not-object')
        self.assertEqual(validate_submission({'pairs': []})[2], 'differential-has-no-pairs')
        self.assertEqual(validate_submission({'pairs': [{'name': 'x'}]})[2], 'pair-missing-name-or-commands')
        self.assertIsNone(validate_submission({'pairs': [PAIR]})[2])


if __name__ == '__main__':
    unittest.main()
