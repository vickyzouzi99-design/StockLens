"""Production-origin, TLS-cookie and durable storage contracts without external APIs."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from app import app
import accounts
from collect_data import atomic_json, data_directory
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware


async def proxied(path, body, cookie=''):
    messages = []
    async def receive():
        return {'type': 'http.request', 'body': json.dumps(body).encode(), 'more_body': False}
    async def send(message):
        messages.append(message)
    wrapped = ProxyHeadersMiddleware(app, trusted_hosts='*')
    await wrapped({'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
        'method': 'POST', 'scheme': 'http', 'path': path, 'raw_path': path.encode(),
        'query_string': b'', 'root_path': '', 'server': ('api', 8000), 'client': ('172.20.0.2', 1234),
        'headers': [(b'host', b'stocks.example.com'), (b'origin', b'https://stocks.example.com'),
                    (b'x-forwarded-proto', b'https'), (b'x-forwarded-for', b'203.0.113.9'),
                    (b'content-type', b'application/json'), (b'cookie', cookie.encode())]}, receive, send)
    start = next(message for message in messages if message['type'] == 'http.response.start')
    payload = json.loads(b''.join(message.get('body', b'') for message in messages if message['type'] == 'http.response.body'))
    return start, payload


class ProductionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        env = patch.dict(os.environ, {'STOCKLENS_ENV': 'production', 'STOCKLENS_ACCESS_MODE': 'local',
            'STOCKLENS_CORS_ORIGINS': '', 'STOCKLENS_ACCOUNT_DB': str(Path(self.folder.name) / 'accounts/accounts.sqlite3'),
            'STOCKLENS_DATA_DIR': str(Path(self.folder.name) / 'data')})
        env.start()
        self.addCleanup(env.stop)

    async def test_https_proxy_registration_and_new_connection_restore_strategy(self):
        with accounts.database() as db:
            db.execute('INSERT INTO invites VALUES(?,?,?)', (accounts.digest('production-fixture'), int(time.time()) + 60, 2))
        start, user = await proxied('/api/account/register', {'username': 'production_test',
            'password': 'fixture-password-only', 'invite': 'production-fixture'})
        self.assertEqual(start['status'], 200)
        cookie = next(value.decode() for key, value in start['headers'] if key == b'set-cookie')
        self.assertIn('Secure', cookie)
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=lax', cookie)
        conditions = [{'metricId': key, 'enabled': key == 'pe_max', 'operator': 'positive_le' if key in ('pe_max', 'pb_max') else ('le' if key == 'vol_max' else 'ge'),
                       'value': 20 if key == 'pe_max' else (7 if key == 'roe_min' else None),
                       'unit': '倍' if key in ('pe_max', 'pb_max') else '%'}
                      for key in ('pe_max', 'profit_min', 'vol_max', 'pb_max', 'roe_min', 'revenue_min')]
        item = {'schemaVersion': 2, 'id': 'production-fixture', 'name': '持久化验收', 'query': '估值条件',
                'provider': 'deepseek', 'createdAt': '2026-11-17T00:00:00Z', 'updatedAt': '2026-11-17T00:00:00Z',
                'snapshot': {'universeId': 'CSI300', 'conditionLogic': 'AND', 'industry': None, 'conditions': conditions}}
        # These functions open independent SQLite connections, as separate requests do.
        scope = {'type': 'http', 'method': 'PUT', 'scheme': 'https', 'path': '/', 'server': ('stocks.example.com', 443),
                 'client': ('203.0.113.9', 1), 'query_string': b'',
                 'headers': [(b'host', b'stocks.example.com'), (b'origin', b'https://stocks.example.com'),
                             (b'cookie', cookie.split(';')[0].encode())]}
        from fastapi import Request
        req = Request(scope)
        accounts.put_strategies(accounts.Library(revision=0, items=[item]), req)
        restored = accounts.strategies(Request(scope))
        self.assertEqual(restored['items'][0]['snapshot']['conditions'][4]['value'], 7)
        self.assertEqual(accounts.principal(req)['id'], user['id'])
        with accounts.database() as db:
            self.assertEqual(db.execute('SELECT ip FROM attempts').fetchone()[0], '203.0.113.9')

    def test_production_rejects_development_origin_and_cannot_disable_auth(self):
        from fastapi import HTTPException, Request
        self.assertTrue(accounts.enabled())
        req = Request({'type': 'http', 'scheme': 'https', 'path': '/', 'server': ('stocks.example.com',443),
                       'headers': [(b'host', b'stocks.example.com'), (b'origin', b'http://localhost:5173')], 'query_string': b''})
        with self.assertRaises(HTTPException) as error:
            accounts.mutation_origin(req)
        self.assertEqual(error.exception.status_code, 403)

    def test_configured_snapshot_directory_is_independent_of_working_directory(self):
        from app import load_snapshot
        identity = 'd' * 32
        atomic_json(data_directory() / 'stock_snapshot_latest.json', {'metadata': {'snapshot_id': identity}, 'stocks': []})
        # Ignore a developer's optional snapshot override in this independent fixture.
        with patch.dict(os.environ, {'STOCKLENS_SNAPSHOT': ''}):
            self.assertEqual(load_snapshot()['metadata']['snapshot_id'], identity)
