import unittest
from intent_parser import normalize_intent


class SuggestionTests(unittest.TestCase):
    def raw(self):
        return {'active_metrics': ['pe_max', 'profit_min'], 'parameters': {'pe_max': 30, 'profit_min': 10}, 'sources': {'pe_max': 'user', 'profit_min': 'user'},
                'suggestions': [{'metric': 'revenue_min', 'reason': '与利润增长对照，观察收入是否同步增长', 'limitation': '收入增长不等于现金流改善', 'value': 10}]}

    def test_suggestions_never_become_active_or_generate_thresholds(self):
        result = normalize_intent(self.raw(), 'test')
        self.assertEqual(result['active_metrics'], ['pe_max','profit_min'])
        self.assertIsNone(result['parameters']['revenue_min'])
        self.assertNotIn('value', result['suggestions'][0])
        self.assertEqual(result['suggestions'][0]['metric'], 'revenue_min')

    def test_explicit_narrow_scope_or_blocked_goal_has_no_extra_suggestions(self):
        self.assertFalse(normalize_intent(self.raw(), 'test', '只看估值和利润增长')['suggestions'])
        raw = self.raw(); raw['clarifications'] = ['风险低是什么意思']
        self.assertFalse(normalize_intent(raw, 'test')['suggestions'])

    def test_invalid_optional_metric_cannot_enter_editor(self):
        raw = self.raw(); raw['suggestions'][0]['metric'] = 'made_up'
        with self.assertRaises(ValueError): normalize_intent(raw, 'test')
