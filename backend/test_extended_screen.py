import copy
from datetime import datetime
import unittest
from unittest.mock import patch

from app import ScreenRequest
from collect_data import SHANGHAI, collect_snapshot, validate_snapshot
from industries import catalog, clean_memberships
from intent_parser import normalize_intent
from screen_engine import execute_screen
from test_api_transport import post
from test_data_refresh import FixtureClient

BANK = {'code': '881155.TI', 'name': '银行'}
STOCKS = [
    {'thscode': '000001.SZ', 'name': '样本甲', 'pb_mrq': 2, 'roe_pct': 8, 'revenue_growth_pct': 0, 'industries': [BANK]},
    {'thscode': '000002.SZ', 'name': '样本乙', 'pb_mrq': -1, 'roe_pct': 9, 'revenue_growth_pct': 10, 'industries': [BANK]},
    {'thscode': '000003.SZ', 'name': '样本丙', 'pb_mrq': None, 'roe_pct': 8, 'revenue_growth_pct': None, 'industries': None},
    {'thscode': '000004.SZ', 'name': '样本丁', 'pb_mrq': 2, 'roe_pct': 8, 'revenue_growth_pct': 0, 'industries': [{'code': '881273.TI', 'name': '白酒'}]},
]


class ExtendedTests(unittest.TestCase):
    def test_all_conditions_and_positive_pb_boundary(self):
        result = execute_screen(STOCKS, {'pb_max': 2, 'roe_min': 8, 'revenue_min': 0, 'industry': BANK['code']})
        self.assertEqual([row['status'] for row in result['results']], ['SELECTED', 'EXCLUDED', 'INSUFFICIENT_DATA', 'EXCLUDED'])
        self.assertIn('银行', result['results'][3]['checks'][-1]['reason'])

    def test_industry_only_missing_does_not_mean_not_member(self):
        result = execute_screen(STOCKS, {'industry': BANK['code']})
        self.assertEqual(result['summary'], {'selected': 2, 'excluded': 1, 'insufficient_data': 1})
        self.assertEqual(len(result['results'][0]['checks']), 1)

    def test_negative_growth_and_zero_roe_are_valid_not_missing(self):
        self.assertEqual(execute_screen([{'revenue_growth_pct': -2, 'roe_pct': 0}], {'revenue_min': -5, 'roe_min': 0})['summary']['selected'], 1)
        for params in [{'pb_max': 0}, {'roe_min': float('inf')}, {'industry': '银行'}]:
            with self.assertRaises(ValueError): ScreenRequest(**params)

    def test_parser_new_metrics_and_industry_keep_missing_thresholds(self):
        raw = {'active_metrics': ['pb_max', 'roe_min', 'revenue_min'], 'parameters': {'pb_max': 2, 'roe_min': 8}, 'sources': {'pb_max': 'user', 'roe_min': 'user'}, 'industry': BANK['code']}
        result = normalize_intent(raw, 'test', industry_catalog=[BANK])
        self.assertEqual(result['industry'], BANK['code'])
        self.assertEqual(result['parameters']['pb_max'], 2)
        self.assertIsNone(result['parameters']['revenue_min'])
        self.assertTrue(result['questions'])
        self.assertTrue(normalize_intent(raw, 'test', industry_catalog=[])['unsupported'])

    def test_industry_alone_needs_no_financial_clarification(self):
        result = normalize_intent({'active_metrics': [], 'industry': BANK['code']}, 'test', industry_catalog=[BANK])
        self.assertEqual(result['status'], 'ready')
        self.assertFalse(result['clarifications'])

    def test_provider_cannot_silently_omit_an_explicit_industry_or_guarantee(self):
        result = normalize_intent({'active_metrics': ['pb_max'], 'parameters': {'pb_max': 2}, 'sources': {'pb_max': 'user'}, 'industry': None}, 'test', '银行股，市净率不超过2倍', [BANK])
        self.assertTrue(result['unsupported'])
        result = normalize_intent({'active_metrics': [], 'clarifications': ['请明确必涨的含义']}, 'test', '找科技板块未来必涨的股票')
        self.assertTrue(result['unsupported'])

    def test_membership_cleaning_rejects_concept_bad_and_ambiguous_data(self):
        raw = {'thscode': BANK['code'], 'name': BANK['name'], 'type': 'industry'}
        self.assertEqual(clean_memberships([raw, raw]), [BANK])
        for value in [None, [], [dict(raw, type='cn_concept')], [dict(raw, thscode='bad')], [raw, dict(raw, name='另一分类')]]:
            self.assertIsNone(clean_memberships(value))
        self.assertEqual(next(item['count'] for item in catalog(STOCKS) if item['code'] == BANK['code']), 2)

    def test_new_fields_and_industry_participate_in_publication_gate(self):
        data = collect_snapshot(FixtureClient(), limit=5, now=datetime(2026, 11, 16, 16, tzinfo=SHANGHAI), progress=lambda _: None)
        self.assertEqual(validate_snapshot(data, 5)['industries'], 1)
        for field in ['pb_mrq', 'roe_pct', 'revenue_growth_pct', 'industries']:
            broken = copy.deepcopy(data)
            for row in broken['stocks']: row[field] = None
            with self.assertRaises(ValueError): validate_snapshot(broken, 5)


class ExtendedTransportTests(unittest.IsolatedAsyncioTestCase):
    @patch('app.load_snapshot', return_value={'stocks': STOCKS, 'metadata': {}})
    async def test_industry_and_new_metrics_http_contract(self, _):
        status, result = await post('/api/screen', {'pb_max': 2, 'industry': BANK['code']})
        self.assertEqual(status, 200)
        self.assertEqual(result['summary'], {'selected': 1, 'excluded': 2, 'insufficient_data': 1})
        status, _ = await post('/api/screen', {'industry': '881999.TI'})
        self.assertEqual(status, 422)
        status, result = await post('/api/compare', {'before': {'industry': BANK['code']}, 'after': {'industry': BANK['code'], 'pb_max': 2}})
        self.assertEqual(status, 200)
        self.assertEqual([row['thscode'] for row in result['changes']['no_longer_selected']], ['000002.SZ'])
