"""Route-handler integration tests; no network, credentials or httpx required."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import CompareRequest, ScreenParams, compare, data_status, screen
from pydantic import ValidationError

EXAMPLE = {
    "metadata": {"universe": "CSI 300", "universe_size": 300, "sample_size": 3},
    "stocks": [
        {"name": "甲", "thscode": "A", "pe_ttm": 18, "parent_net_profit_growth_pct": -4, "volatility_20d_pct": 5, "sources": {}},
        {"name": "乙", "thscode": "B", "pe_ttm": 30, "parent_net_profit_growth_pct": 25, "volatility_20d_pct": 1, "sources": {}},
        {"name": "丙", "thscode": "C", "pe_ttm": None, "parent_net_profit_growth_pct": 25, "volatility_20d_pct": 1, "sources": {}},
    ],
}


class APITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "stock_snapshot_test.json"
        self.path.write_text(json.dumps(EXAMPLE, ensure_ascii=False), encoding="utf-8")
        self.previous = os.environ.get("STOCKLENS_SNAPSHOT")
        os.environ["STOCKLENS_SNAPSHOT"] = str(self.path)

    def tearDown(self):
        if self.previous is None:
            os.environ.pop("STOCKLENS_SNAPSHOT", None)
        else:
            os.environ["STOCKLENS_SNAPSHOT"] = self.previous
        self.directory.cleanup()

    def test_valuation_only(self):
        data = screen(ScreenParams(pe_max=20))
        self.assertEqual(data["summary"], {"selected": 1, "excluded": 1, "insufficient_data": 1})
        self.assertEqual(len(data["strategy"]["conditions"]), 1)

    def test_zero_conditions_rejected(self):
        with self.assertRaises(ValidationError):
            ScreenParams()

    def test_compare_adding_condition(self):
        data = compare(CompareRequest(
            before=ScreenParams(profit_min=10),
            after=ScreenParams(profit_min=10, vol_max=1.0),
        ))
        self.assertEqual(data['before']['summary']['selected'], 2)
        self.assertEqual(data['after']['summary']['selected'], 2)
        self.assertEqual(data['changes']['newly_selected'], [])

    def test_status_metadata(self):
        data = data_status()
        self.assertEqual(data['stock_count'], 3)


if __name__ == '__main__':
    unittest.main()
