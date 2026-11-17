"""Invite-only accounts, opaque sessions and atomic daily AI budgets."""
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

router = APIRouter(prefix='/api/account')
COOKIE = 'stocklens_session'


def enabled():
    return os.getenv('STOCKLENS_ENV') == 'production' or os.getenv('STOCKLENS_ACCESS_MODE', 'required') != 'local'


@contextmanager
def database():
    path = Path(os.getenv('STOCKLENS_ACCOUNT_DB', str(Path(__file__).resolve().parent.parent / 'data/accounts.sqlite3')))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.executescript('''
    CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT UNIQUE, password TEXT, daily_limit INTEGER);
    CREATE TABLE IF NOT EXISTS invites(hash TEXT PRIMARY KEY, expires INTEGER, daily_limit INTEGER);
    CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY, user_id TEXT, expires INTEGER);
    CREATE TABLE IF NOT EXISTS usage(user_id TEXT, day TEXT, count INTEGER, PRIMARY KEY(user_id,day));
    CREATE TABLE IF NOT EXISTS libraries(user_id TEXT PRIMARY KEY, revision INTEGER, payload TEXT);
    CREATE TABLE IF NOT EXISTS attempts(ip TEXT PRIMARY KEY, start INTEGER, count INTEGER);
    ''')
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    return salt + ':' + hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()


def principal(request):
    token = request.cookies.get(COOKIE, '')
    with database() as db:
        row = db.execute('SELECT users.* FROM sessions JOIN users ON users.id=sessions.user_id WHERE sessions.hash=? AND expires>?', (digest(token), int(time.time()))).fetchone()
    if not row:
        raise HTTPException(401, '请先使用邀请码注册或登录。')
    return dict(row)


def mutation_origin(request):
    origin = request.headers.get('origin')
    allowed = {str(request.base_url).rstrip('/')}
    allowed.update(os.getenv('STOCKLENS_CORS_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173').split(','))
    if origin and origin not in allowed:
        raise HTTPException(403, '请求来源不受信任')


def reserve_call(user_id):
    day = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        limit = db.execute('SELECT daily_limit FROM users WHERE id=?', (user_id,)).fetchone()[0]
        used = db.execute('SELECT count FROM usage WHERE user_id=? AND day=?', (user_id, day)).fetchone()
        total = db.execute('SELECT COALESCE(SUM(count),0) FROM usage WHERE day=?', (day,)).fetchone()[0]
        if (used and used[0] >= limit) or total >= int(os.getenv('STOCKLENS_GLOBAL_DAILY_LIMIT', '200')):
            raise HTTPException(429, '今日 AI 调用额度已用完，请明天再试。')
        db.execute('INSERT INTO usage VALUES(?,?,1) ON CONFLICT(user_id,day) DO UPDATE SET count=count+1', (user_id, day))


class Credentials(BaseModel):
    username: str = Field(pattern=r'^[A-Za-z0-9_]{3,32}$')
    password: str = Field(min_length=10, max_length=128)
    invite: str | None = Field(default=None, max_length=128)


def throttle(request):
    ip = request.client.host if request.client else 'unknown'
    now = int(time.time())
    blocked = False
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM attempts WHERE ip=?', (ip,)).fetchone()
        count = row['count'] + 1 if row and now - row['start'] < 900 else 1
        start = row['start'] if row and now - row['start'] < 900 else now
        db.execute('INSERT OR REPLACE INTO attempts VALUES(?,?,?)', (ip, start, count))
        blocked = count > 30
    if blocked:
        raise HTTPException(429, '登录尝试过于频繁，请稍后再试。')


def session(response, db, user_id):
    token = secrets.token_urlsafe(32)
    db.execute('DELETE FROM sessions WHERE expires<=?', (int(time.time()),))
    db.execute('INSERT INTO sessions VALUES(?,?,?)', (digest(token), user_id, int(time.time()) + 604800))
    response.set_cookie(COOKIE, token, httponly=True, secure=os.getenv('STOCKLENS_ENV') == 'production', samesite='lax', max_age=604800)


@router.get('/me')
def me(request: Request):
    if not enabled():
        return {'local': True}
    user = principal(request)
    return {'id': user['id'], 'username': user['username'], 'daily_limit': user['daily_limit']}


@router.post('/register')
def register(payload: Credentials, request: Request, response: Response):
    mutation_origin(request)
    throttle(request)
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        invite = db.execute('SELECT * FROM invites WHERE hash=? AND expires>?', (digest(payload.invite or ''), int(time.time()))).fetchone()
        if not invite:
            raise HTTPException(400, '邀请码无效、已使用或已过期。')
        user_id = secrets.token_hex(16)
        try:
            db.execute('INSERT INTO users VALUES(?,?,?,?)', (user_id, payload.username.lower(), password_hash(payload.password), invite['daily_limit']))
        except sqlite3.IntegrityError:
            raise HTTPException(409, '用户名已被使用') from None
        db.execute('DELETE FROM invites WHERE hash=?', (invite['hash'],))
        session(response, db, user_id)
    return {'id': user_id, 'username': payload.username.lower()}


@router.post('/login')
def login(payload: Credentials, request: Request, response: Response):
    mutation_origin(request)
    throttle(request)
    with database() as db:
        user = db.execute('SELECT * FROM users WHERE username=?', (payload.username.lower(),)).fetchone()
        stored = user['password'] if user else password_hash('dummy-password')
        if not hmac.compare_digest(stored, password_hash(payload.password, stored.split(':')[0])) or not user:
            raise HTTPException(401, '用户名或密码错误')
        session(response, db, user['id'])
    return {'id': user['id'], 'username': user['username']}


@router.post('/logout')
def logout(request: Request, response: Response):
    mutation_origin(request)
    with database() as db:
        db.execute('DELETE FROM sessions WHERE hash=?', (digest(request.cookies.get(COOKIE, '')),))
    response.delete_cookie(COOKIE)
    return {'ok': True}


@router.get('/strategies')
def strategies(request: Request):
    user = principal(request)
    with database() as db:
        row = db.execute('SELECT * FROM libraries WHERE user_id=?', (user['id'],)).fetchone()
    return {'revision': row['revision'] if row else 0, 'items': json.loads(row['payload']) if row else []}


class Library(BaseModel):
    revision: int = Field(ge=0)
    items: list[dict] = Field(max_length=50)


@router.put('/strategies')
def put_strategies(payload: Library, request: Request):
    mutation_origin(request)
    user = principal(request)
    from strategy_contract import validate_library
    items = validate_library(payload.items)
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT revision FROM libraries WHERE user_id=?', (user['id'],)).fetchone()
        if (row['revision'] if row else 0) != payload.revision:
            raise HTTPException(409, '策略已在其他页面更新，请重新载入。')
        if len(items) > 30 and (not row or len(items) > len(json.loads(db.execute('SELECT payload FROM libraries WHERE user_id=?', (user['id'],)).fetchone()[0]))):
            raise HTTPException(422, '最多新建30条策略')
        db.execute('INSERT OR REPLACE INTO libraries VALUES(?,?,?)', (user['id'], payload.revision + 1, json.dumps(items, ensure_ascii=False)))
    return {'revision': payload.revision + 1, 'items': items}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Create a single-use invitation; prints it once. Keep it private.')
    parser.add_argument('--daily-limit', type=int, default=10)
    parser.add_argument('--days', type=int, default=7)
    args = parser.parse_args()
    if not 1 <= args.daily_limit <= 1000 or not 1 <= args.days <= 365: parser.error('invalid limits')
    code = secrets.token_urlsafe(24)
    with database() as db:
        db.execute('INSERT INTO invites VALUES(?,?,?)', (digest(code), int(time.time()) + args.days * 86400, args.daily_limit))
    print(code)
