import unittest
from intent_conflicts import explicit_bounds, numeric_conflicts
from intent_parser import normalize_intent


class ConflictTests(unittest.TestCase):
    def test_explicit_contradiction_cannot_be_dropped_by_model(self):
        for text in ['PE小于10倍，同时大于30倍', '市盈率低于10，市盈率高于30', '利润增长超过20%，且不超过10%']:
            with self.subTest(text=text):
                result = normalize_intent({'active_metrics': ['pe_max'], 'parameters': {'pe_max': 10}, 'sources': {'pe_max': 'user'}}, 'test', text)
                self.assertTrue(result['conflicts'])
                self.assertEqual(result['status'], 'needs_confirmation')

    def test_strict_equal_bounds_are_impossible_but_inclusive_are_not(self):
        self.assertTrue(numeric_conflicts([{'metric': 'pe_max', 'op': 'gt', 'value': 10}, {'metric': 'pe_max', 'op': 'le', 'value': 10}]))
        self.assertFalse(numeric_conflicts([{'metric': 'pe_max', 'op': 'ge', 'value': 10}, {'metric': 'pe_max', 'op': 'le', 'value': 10}]))

    def test_distinct_metrics_and_compatible_bounds_are_not_conflicts(self):
        for text in ['PE低于20，利润增长超过30%', 'PE大于10且小于30', '市盈率低于20']:
            self.assertFalse(numeric_conflicts(explicit_bounds(text)))

    def test_corrections_or_alternatives_need_semantic_parsing(self):
        for text in ['PE低于10或者大于30', '不要PE低于10，改为PE大于30', 'PE低于10，补充说明：改为PE超过30']:
            self.assertEqual(explicit_bounds(text), [])

    def test_structured_constraints_detect_chinese_number_semantics(self):
        result = normalize_intent({'active_metrics': [], 'numeric_constraints': [
            {'metric': 'pe_max', 'op': 'lt', 'value': 10}, {'metric': 'pe_max', 'op': 'gt', 'value': 30}]}, 'test')
        self.assertTrue(result['conflicts'])

    def test_unimplemented_direction_cannot_be_silently_ignored(self):
        result = normalize_intent({'active_metrics': ['pe_max'], 'numeric_constraints': [{'metric': 'pe_max', 'op': 'gt', 'value': 10}]}, 'test')
        self.assertTrue(result['unsupported'])

    def test_bad_contract_is_rejected(self):
        for constraints in [None, 'text', [{'metric': 'pe_max', 'op': 'gt', 'value': float('nan')}]]:
            with self.assertRaises(ValueError):
                normalize_intent({'active_metrics': [], 'numeric_constraints': constraints}, 'test')
