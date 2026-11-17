"""Run: python -m unittest discover -s backend -p 'test_dynamic_screen.py' -v"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from screen_engine import build_strategy, execute_screen
from intent_parser import normalize_intent
from app import ScreenParams
from pydantic import ValidationError

STOCKS = [
    {"thscode": "A", "name": "甲", "pe_ttm": 18.0,
     "parent_net_profit_growth_pct": -8.0, "volatility_20d_pct": 4.0},
    {"thscode": "B", "name": "乙", "pe_ttm": 35.0,
     "parent_net_profit_growth_pct": 20.0, "volatility_20d_pct": 1.0},
    {"thscode": "C", "name": "丙", "pe_ttm": None,
     "parent_net_profit_growth_pct": 33.0, "volatility_20d_pct": 1.0},
    {"thscode": "D", "name": "丁", "pe_ttm": -8.0,
     "parent_net_profit_growth_pct": 50.0, "volatility_20d_pct": 1.0},
]


class ScreenTests(unittest.TestCase):
    def test_valuation_only_ignores_other_values(self):
        result = execute_screen(STOCKS, {"pe_max": 20, "profit_min": None, "vol_max": None})
        self.assertEqual(result["summary"], {"selected": 1, "excluded": 2, "insufficient_data": 1})
        self.assertEqual(result["results"][0]["status"], "SELECTED")
        self.assertTrue(all(len(item["checks"]) == 1 for item in result["results"]))

    def test_profit_only(self):
        result = execute_screen(STOCKS, {"pe_max": None, "profit_min": 10, "vol_max": None})
        self.assertEqual(result["summary"]["selected"], 3)

    def test_two_conditions_and(self):
        result = execute_screen(STOCKS, {"pe_max": 40, "profit_min": 10, "vol_max": None})
        self.assertEqual(result["summary"]["selected"], 1)
        self.assertEqual(result["summary"]["insufficient_data"], 1)
        self.assertTrue(all(len(item["checks"]) == 2 for item in result["results"]))

    def test_zero_conditions_rejected(self):
        with self.assertRaises(ValueError):
            build_strategy({"pe_max": None, "profit_min": None, "vol_max": None})
        with self.assertRaises(ValidationError):
            ScreenParams()

    def test_ambiguous_valuation_only(self):
        result = normalize_intent({
            "active_metrics": ["pe_max"],
            "parameters": {"pe_max": None, "profit_min": None, "vol_max": None},
            "sources": {"pe_max": "missing", "profit_min": "missing", "vol_max": "missing"},
            "interpretation": "筛选低估值股票",
            "unsupported": [],
        }, "test-model")
        self.assertEqual(result["active_metrics"], ["pe_max"])
        self.assertEqual(len(result["questions"]), 1)
        self.assertEqual(result["status"], "needs_confirmation")

    def test_inactive_parameters_cleared(self):
        result = normalize_intent({
            "active_metrics": ["pe_max"],
            "parameters": {"pe_max": 20, "profit_min": 10, "vol_max": 2.5},
            "sources": {"pe_max": "user", "profit_min": "user", "vol_max": "user"},
        }, "test-model")
        self.assertIsNone(result["parameters"]["profit_min"])
        self.assertIsNone(result["parameters"]["vol_max"])
        self.assertEqual(result["status"], "ready")

    def test_invalid_unknown_metric_rejected(self):
        with self.assertRaises(ValueError):
            normalize_intent({"active_metrics": ["industry"]}, "test-model")


if __name__ == "__main__":
    unittest.main()
