"""Report fields that the final report relies on: grounded innovations,
fix/optimize suggestion types and server-bounded metric tolerances."""
import unittest

from articheck.hosted_review import tolerance_rule, validate_assessment

from test_hosted_review import materials, output, prepare_assessment

QUOTE = 'The routing layer groups related patches into learned windows.'


def paper_context():
    context, _ = prepare_assessment(materials())
    context['paper_excerpts'] = [{'page': 1, 'text': 'Table 1. Ours 93.40 on the test split. ' + QUOTE}]
    context['method_chunks'] = [{'id': 'M1', 'kind': 'method', 'page': 1, 'section': '3 Method', 'text': QUOTE * 2}]
    return context


def answer_with_metric(context, tolerance):
    answer = output(context)
    answer['metrics'] = [{'id': 'M1', 'reference': 'Table 1', 'page': 1, 'quote': 'Ours 93.40', 'value': 93.4,
                          'unit': '', 'metric': 'accuracy', 'model': 'Ours', 'dataset': 'test', 'author_method': True}]
    answer['plan']['metric_patterns'] = [{'metric_id': 'M1', 'stage_id': 'S1', 'pattern': 'acc: ([0-9.]+)',
                                          'tolerance': tolerance}]
    return answer


class ToleranceRuleTests(unittest.TestCase):
    def test_bounds_follow_printed_precision_and_relative_cap(self):
        metric = {'value': 93.4, 'quote': 'Ours 93.40'}
        self.assertEqual(tolerance_rule(metric, 0.3)[0], 0.3)
        applied, basis = tolerance_rule(metric, 5)
        self.assertAlmostEqual(applied, 0.934)
        self.assertIn('1%', basis)
        self.assertEqual(tolerance_rule(metric, 0)[0], 0.005)
        self.assertEqual(tolerance_rule({'value': 0.8338, 'quote': '0.8338'}, 0)[0], 0.00005)

    def test_relative_cap_applies_to_coarse_small_and_zero_values(self):
        self.assertEqual(tolerance_rule({'value': 1, 'quote': 'Ours 1'}, 5)[0], 0.01)
        self.assertEqual(tolerance_rule({'value': 0, 'quote': 'Ours 0'}, 5)[0], 0)
        self.assertAlmostEqual(tolerance_rule({'value': 0.00012, 'quote': 'Ours 1.20e-4'}, 0)[0], 0.0000005)

    def test_model_tolerance_is_recorded_but_cannot_widen_acceptance(self):
        context = paper_context()
        pattern = validate_assessment(answer_with_metric(context, 5), context)['plan']['metric_patterns'][0]
        self.assertAlmostEqual(pattern['tolerance'], 0.934)
        self.assertEqual(pattern['model_tolerance'], 5)
        self.assertTrue(pattern['tolerance_basis'])


class ReportFieldTests(unittest.TestCase):
    def test_only_evidence_backed_errors_are_required_fixes(self):
        context = paper_context()
        answer = output(context)
        answer['findings'] = [
            {'title': '表文数字不一致', 'severity': 'high', 'detail': '正文 4.2，表 1 为 3.7', 'suggestion': '统一数字',
             'area': 'paper', 'confirmed_error': True, 'page': 1, 'file': None},
            {'title': '未报告方差', 'severity': 'high', 'detail': '单次运行', 'suggestion': '报告标准差',
             'area': 'paper', 'confirmed_error': True, 'page': None, 'file': None}]
        findings = validate_assessment(answer, context)['findings']
        self.assertEqual([f['suggestion_type'] for f in findings], ['fix', 'optimize'])

    def test_missing_contributions_are_not_filled_with_the_summary(self):
        context = paper_context()
        answer = output(context)
        answer['paper_contributions'] = []
        result = validate_assessment(answer, context)
        self.assertEqual(result['paper_contributions'], [])

    def test_contribution_metric_links_keep_only_grounded_ids(self):
        context = paper_context()
        answer = answer_with_metric(context, 0.3)
        answer['method_graph'] = [{'id': 'c1', 'title': 'Patch routing layer', 'summary': '按窗口组织图块',
                                   'chunk_id': 'M1', 'quote': QUOTE}]
        answer['contribution_metrics'] = [{'contribution_id': 'c1', 'metric_ids': ['M1', 'M9']},
                                          {'contribution_id': 'invented', 'metric_ids': ['M1']},
                                          {'contribution_id': ['c1'], 'metric_ids': ['M1']}]
        result = validate_assessment(answer, context)
        self.assertEqual([row['local_id'] for row in result['method_graph']], ['c1'])
        self.assertEqual(result['contribution_metrics'], {'c1': ['M1']})


if __name__ == '__main__':
    unittest.main()
