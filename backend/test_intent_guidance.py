"""Vague goals must lead to clarification, never fabricated screening rules."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import InterpretRequest, ScreenParams, interpret, screen
from intent_parser import normalize_intent


class GuidanceTests(unittest.TestCase):
    def test_potential_stock_is_a_clarification_not_a_dead_end(self):
        result = normalize_intent({"active_metrics": [], "unsupported": ["潜力股"]}, "test")
        self.assertEqual(result["unsupported"], [])
        self.assertEqual(result["clarifications"], ["潜力股"])
        self.assertEqual(result["active_metrics"], [])
        self.assertTrue(all(value is None for value in result["parameters"].values()))
        self.assertEqual(result["status"], "needs_confirmation")

    def test_no_clues_gets_plain_language_guidance(self):
        result = normalize_intent({"active_metrics": [], "unsupported": []}, "test")
        self.assertTrue(result["clarifications"])
        self.assertEqual(result["unsupported"], [])

    def test_mixed_industry_and_vague_goal_preserves_industry(self):
        result = normalize_intent({"active_metrics": [], "unsupported": ["银行行业", "潜力股"]}, "test")
        self.assertEqual(result["unsupported"], ["银行行业"])
        self.assertEqual(result["clarifications"], ["潜力股"])

    def test_concrete_predictions_are_not_rewritten(self):
        for restriction in ["明天必涨", "银行潜力股", "未来涨幅超过20%", "连续三年利润增长"]:
            with self.subTest(restriction=restriction):
                result = normalize_intent({"active_metrics": [], "unsupported": [restriction]}, "test")
                self.assertEqual(result["unsupported"], [restriction])
                self.assertEqual(result["clarifications"], [])

    def test_mixed_active_and_vague_needs_confirmation(self):
        result = normalize_intent({"active_metrics": ["pe_max"],
                                   "parameters": {"pe_max": 20}, "sources": {"pe_max": "user"},
                                   "clarifications": ["潜力股"]}, "test")
        self.assertEqual(result["parameters"]["pe_max"], 20)
        self.assertEqual(result["status"], "needs_confirmation")

    def test_missing_threshold_stays_empty(self):
        result = normalize_intent({"active_metrics": ["profit_min"], "clarifications": []}, "test")
        self.assertIsNone(result["parameters"]["profit_min"])
        self.assertEqual(result["sources"]["profit_min"], "missing")
        self.assertEqual(result["unsupported"], [])

    def test_malformed_restrictions_do_not_disappear(self):
        for field in ["unsupported", "clarifications"]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                normalize_intent({"active_metrics": [], field: "银行股"}, "test")

    @patch("intent_parser.requests.post")
    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-only", "LLM_BASE_URL": "https://api.openai.com/v1"})
    def test_followup_keeps_original_text_and_can_screen(self, post):
        raw = {"active_metrics": ["profit_min"], "parameters": {"profit_min": 10},
               "sources": {"profit_min": "user"}, "clarifications": [], "unsupported": [], 'industry': None,
               'numeric_constraints': [{'metric': 'profit_min', 'op': 'ge', 'value': 10}]}
        post.return_value = Mock(ok=True, json=lambda: {"choices": [{"message": {"content": json.dumps(raw)}}]})
        text = "我想找潜力股\n补充说明：我指的是利润比去年增长至少10%的公司"
        with patch('app.load_snapshot', return_value={'stocks': [], 'metadata': {}}):
            result = interpret(InterpretRequest(text=text))
        self.assertEqual(post.call_args.kwargs["json"]["messages"][-1]["content"], text)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["active_metrics"], ["profit_min"])
        with patch("app.load_snapshot", return_value={"stocks": [
            {"thscode": "A", "parent_net_profit_growth_pct": 15},
            {"thscode": "B", "parent_net_profit_growth_pct": 5},
        ]}):
            screened = screen(ScreenParams(**result["parameters"]))
        self.assertEqual(screened["summary"]["selected"], 1)
        self.assertEqual(screened["summary"]["excluded"], 1)


if __name__ == "__main__":
    unittest.main()
