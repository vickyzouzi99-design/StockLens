"""Provider routing, credential isolation and shared intent validation."""
import json
import os
import unittest
from unittest.mock import Mock, patch

import requests
from intent_parser import parse_intent
from test_api_transport import post


RAW = {"active_metrics": ["pe_max"], "parameters": {"pe_max": 20},
       "sources": {"pe_max": "user"}, "clarifications": [], "unsupported": [], 'industry': None, 'numeric_constraints': []}
ENV = {"OPENAI_API_KEY": "openai-test-only", "LLM_MODEL": "gpt-4o-mini",
       "LLM_BASE_URL": "https://api.openai.com/v1", "DEEPSEEK_API_KEY": "deepseek-test-only",
       "DEEPSEEK_MODEL": "deepseek-flash"}


def response(content=None, finish="stop"):
    return Mock(ok=True, json=lambda: {"choices": [{"finish_reason": finish, "message": {
        "content": json.dumps(RAW) if content is None else content}}]})


class ProviderTests(unittest.TestCase):
    @patch.dict(os.environ, ENV, clear=True)
    @patch("intent_parser.requests.post")
    def test_each_provider_uses_its_own_key_model_and_official_endpoint(self, request):
        request.return_value = response()
        results = []
        for provider, url, key, model in [
            ("openai", "https://api.openai.com/v1/chat/completions", ENV['OPENAI_API_KEY'], "gpt-4o-mini"),
            ("deepseek", "https://api.deepseek.com/chat/completions", ENV['DEEPSEEK_API_KEY'], "deepseek-flash"),
        ]:
            result = parse_intent("市盈率低于20倍", provider)
            results.append(result)
            args, kwargs = request.call_args
            self.assertEqual(args[0], url)
            self.assertEqual(kwargs['headers']['Authorization'], f"Bearer {key}")
            self.assertEqual(kwargs['json']['model'], model)
            self.assertEqual(kwargs['json']['response_format'], {"type": "json_object"})
            self.assertEqual(result['provider'], provider)
            self.assertEqual(result['model'], model)
        self.assertEqual(request.call_args.kwargs['json']['thinking'], {'type': 'disabled'})
        self.assertEqual(results[0]['parameters'], results[1]['parameters'])

    @patch.dict(os.environ, ENV, clear=True)
    @patch("intent_parser.requests.post", return_value=response())
    def test_omitting_provider_defaults_to_deepseek(self, request):
        self.assertEqual(parse_intent("低估值")['provider'], 'deepseek')
        self.assertEqual(request.call_args.args[0], 'https://api.deepseek.com/chat/completions')
        self.assertEqual(request.call_args.kwargs['json']['thinking'], {'type': 'disabled'})

    @patch.dict(os.environ, {**ENV, 'DEEPSEEK_API_KEY': ''}, clear=True)
    @patch("intent_parser.requests.post")
    def test_missing_deepseek_key_never_uses_openai_key_or_falls_back(self, request):
        with self.assertRaisesRegex(RuntimeError, 'DeepSeek 尚未配置'):
            parse_intent("低估值")
        request.assert_not_called()

    @patch("intent_parser.requests.post")
    def test_unknown_provider_does_not_send_request(self, request):
        with self.assertRaises(ValueError):
            parse_intent("低估值", "custom")
        request.assert_not_called()

    @patch.dict(os.environ, ENV, clear=True)
    @patch("intent_parser.requests.post")
    def test_blank_malformed_and_truncated_output_cannot_be_screened(self, request):
        incomplete = {key: value for key, value in RAW.items() if key != 'industry'}
        for content, finish in [('   ', 'stop'), ('not json', 'stop'), (json.dumps(RAW), 'length'), (json.dumps(incomplete), 'stop')]:
            with self.subTest(content=content, finish=finish):
                request.return_value = response(content, finish)
                with self.assertRaisesRegex(RuntimeError, 'DeepSeek 未返回完整有效'):
                    parse_intent("低估值", "deepseek")

    @patch.dict(os.environ, ENV, clear=True)
    @patch("intent_parser.requests.post")
    def test_failures_name_selected_provider_without_exposing_raw_error(self, request):
        request.side_effect = requests.ConnectionError('secret transport detail')
        with self.assertRaisesRegex(RuntimeError, '无法连接 DeepSeek') as caught:
            parse_intent("低估值", "deepseek")
        self.assertNotIn('secret', str(caught.exception))
        self.assertEqual(request.call_count, 1)
        request.side_effect = None
        request.return_value = Mock(ok=False, status_code=401, text='secret')
        with self.assertRaisesRegex(RuntimeError, 'DeepSeek.*401') as caught:
            parse_intent("低估值", "deepseek")
        self.assertNotIn('secret', str(caught.exception))
        self.assertTrue(all(call.args[0] == 'https://api.deepseek.com/chat/completions' for call in request.call_args_list))


class ProviderRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        snapshot = patch('app.load_snapshot', return_value={'stocks': [], 'metadata': {}})
        snapshot.start()
        self.addCleanup(snapshot.stop)

    @patch('app.parse_intent', return_value={'provider': 'deepseek'})
    async def test_explicit_provider_is_forwarded_and_unknown_provider_rejected(self, parse):
        status, body = await post('/api/interpret', {'text': '低估值', 'provider': 'deepseek'})
        self.assertEqual(status, 200)
        self.assertEqual(body['provider'], 'deepseek')
        self.assertEqual(parse.call_args.kwargs['provider'], 'deepseek')
        self.assertIn('industry_catalog', parse.call_args.kwargs)
        status, _ = await post('/api/interpret', {'text': '低估值', 'provider': 'custom'})
        self.assertEqual(status, 422)
        self.assertEqual(parse.call_count, 1)

    @patch('app.parse_intent', return_value={'provider': 'deepseek'})
    async def test_clients_without_provider_default_to_deepseek(self, parse):
        status, _ = await post('/api/interpret', {'text': '低估值'})
        self.assertEqual(status, 200)
        self.assertEqual(parse.call_args.kwargs['provider'], 'deepseek')
