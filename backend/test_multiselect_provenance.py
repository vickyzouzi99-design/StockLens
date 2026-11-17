import copy
import unittest
from app import ScreenRequest
from intent_parser import normalize_intent
from screen_engine import execute_screen
from strategy_contract import validate_library
from test_extended_screen import STOCKS, BANK


class MultiSelectTests(unittest.TestCase):
    def test_industries_union_and_other_conditions_and(self):
        result = execute_screen(STOCKS, {'industry': ['881155.TI', '881273.TI'], 'pb_max': 2})
        self.assertEqual([r['status'] for r in result['results']], ['SELECTED', 'EXCLUDED', 'INSUFFICIENT_DATA', 'SELECTED'])
        self.assertIn('任一', result['results'][0]['checks'][-1]['reason'])
        self.assertIn('白酒', result['results'][0]['checks'][-1]['reason'])
        self.assertEqual(ScreenRequest(industry=['881155.TI', '881155.TI']).industry, '881155.TI')
        for value in [['bad'], ['881155.TI', 'bad'], []]:
            with self.assertRaises(ValueError): ScreenRequest(industry=value)

    def test_parser_preserves_all_industries_and_missing_one_blocks(self):
        catalog = [BANK, {'code': '881273.TI', 'name': '白酒'}]
        raw = {'active_metrics': [], 'industry': ['881155.TI', '881273.TI']}
        result = normalize_intent(raw, 'test', '银行或白酒', catalog)
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(set(result['industry']), {'881155.TI', '881273.TI'})
        raw['industry'] = '881155.TI'
        self.assertTrue(normalize_intent(raw, 'test', '银行或白酒', catalog)['unsupported'])

    def test_account_strategy_accepts_both_formats(self):
        conditions = [{'metricId': key, 'enabled': key == 'pe_max', 'operator': op, 'unit': unit, 'value': 20 if key == 'pe_max' else None} for key, (op, unit) in {
            'pe_max': ('positive_le', '倍'), 'pb_max': ('positive_le', '倍'), 'profit_min': ('ge', '%'), 'roe_min': ('ge', '%'), 'revenue_min': ('ge', '%'), 'vol_max': ('le', '%')}.items()]
        item = {'id': 'one', 'schemaVersion': 2, 'name': 'test', 'query': 'test', 'provider': 'deepseek', 'createdAt': '2026-11-17T00:00:00Z', 'updatedAt': '2026-11-17T00:00:00Z', 'snapshot': {'universeId': 'CSI300', 'conditionLogic': 'AND', 'industry': ['881155.TI','881273.TI'], 'conditions': conditions}}
        self.assertEqual(len(validate_library([item])[0]['snapshot']['industry']), 2)
        item['snapshot']['industry'] = '881155.TI'
        self.assertEqual(validate_library([item])[0]['snapshot']['industry'], '881155.TI')


class ProvenanceTests(unittest.TestCase):
    def test_only_enabled_sources_and_real_times_are_shown(self):
        stock = dict(STOCKS[0], valuation_timestamp=123, financial_report='2026-3', financial_fetched_at='2026-11-17T01:00:00Z')
        row = execute_screen([stock], {'pb_max': 2})['results'][0]
        self.assertEqual([p['key'] for p in row['data_provenance']], ['valuation'])
        self.assertEqual(row['data_provenance'][0]['timestamp'], 123)
        self.assertIn('PB MRQ', row['data_provenance'][0]['basis'])
        unknown = execute_screen([{}], {'roe_min': 8})['results'][0]
        self.assertIsNone(unknown['data_provenance'][0]['timestamp'])
        self.assertEqual(unknown['data_provenance'][0]['availability'], 'missing')

    def test_recorded_calculation_window_not_fabricated(self):
        bars = [{'date_ms': i*86400000, 'close_price': 100+i} for i in range(1,22)]
        stock = {'volatility_20d_pct': 1, 'recent_closes': bars}
        entry = execute_screen([stock], {'vol_max': 2})['results'][0]['data_provenance'][0]
        self.assertEqual(entry['prices'], bars)
        invalid = copy.deepcopy(stock)
        invalid['recent_closes'][1]['date_ms'] = bars[0]['date_ms']
        self.assertEqual(execute_screen([invalid], {'vol_max': 2})['results'][0]['data_provenance'][0]['prices'], [])
        self.assertEqual(execute_screen([{}], {'vol_max': 2})['results'][0]['data_provenance'][0]['prices'], [])
