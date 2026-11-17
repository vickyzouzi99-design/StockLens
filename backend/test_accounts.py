import os
import tempfile
import time
import unittest
from unittest.mock import patch
from fastapi import HTTPException, Request, Response
import accounts
from strategy_contract import validate_library


def request(cookie='', origin=None):
    headers = [(b'cookie', cookie.encode())]
    if origin: headers.append((b'origin', origin.encode()))
    return Request({'type': 'http', 'method': 'POST', 'scheme': 'http', 'path': '/', 'headers': headers, 'server': ('test',80), 'client': ('test',1), 'query_string': b''})


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        env = patch.dict(os.environ, {'STOCKLENS_ACCOUNT_DB': self.folder.name+'/accounts.sqlite3', 'STOCKLENS_GLOBAL_DAILY_LIMIT': '2'})
        env.start(); self.addCleanup(env.stop)

    def signup(self, username, invite):
        with accounts.database() as db:
            db.execute('INSERT INTO invites VALUES(?,?,?)', (accounts.digest(invite), int(time.time())+60, 1))
        response = Response()
        user = accounts.register(accounts.Credentials(username=username, password='long-test-password', invite=invite), request(), response)
        return user, request(response.headers['set-cookie'].split(';')[0])

    def test_invite_once_login_logout_and_opaque_sessions(self):
        user, req = self.signup('test_one', 'one')
        self.assertEqual(accounts.principal(req)['id'], user['id'])
        with self.assertRaises(HTTPException): accounts.register(accounts.Credentials(username='test_two', password='long-test-password', invite='one'), request(), Response())
        with self.assertRaises(HTTPException): accounts.login(accounts.Credentials(username='test_one', password='wrong-password'), request(), Response())
        response = Response()
        accounts.login(accounts.Credentials(username='test_one', password='long-test-password'), request(), response)
        self.assertIn('HttpOnly', response.headers['set-cookie'])
        with accounts.database() as db:
            self.assertNotIn('long-test-password', db.execute('SELECT password FROM users').fetchone()[0])
        accounts.logout(req, Response())
        with self.assertRaises(HTTPException): accounts.principal(req)

    def test_account_isolation_revision_and_budget(self):
        user1, req1 = self.signup('test_one', 'one')
        _, req2 = self.signup('test_two', 'two')
        self.assertEqual(accounts.put_strategies(accounts.Library(revision=0, items=[]), req1)['revision'], 1)
        self.assertEqual(accounts.strategies(req2)['revision'], 0)
        with self.assertRaises(HTTPException): accounts.put_strategies(accounts.Library(revision=0, items=[]), req1)
        accounts.reserve_call(user1['id'])
        with self.assertRaises(HTTPException) as error: accounts.reserve_call(user1['id'])
        self.assertEqual(error.exception.status_code, 429)

    def test_origin_and_production_cannot_bypass_login(self):
        with self.assertRaises(HTTPException): accounts.mutation_origin(request(origin='https://evil.invalid'))
        with patch.dict(os.environ, {'STOCKLENS_ENV':'production', 'STOCKLENS_ACCESS_MODE':'local'}): self.assertTrue(accounts.enabled())
        with self.assertRaises(HTTPException): validate_library([{'schemaVersion': 9}])
