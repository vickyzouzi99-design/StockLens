"""Prepare isolated disposable browser accounts; never touches the normal account DB."""
import argparse
import json
import os
from pathlib import Path
import secrets
import time

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true', required=True)
    args = parser.parse_args()
    directory = ROOT / 'artifacts'
    directory.mkdir(exist_ok=True)
    os.environ['STOCKLENS_ACCOUNT_DB'] = str(directory / 'browser-acceptance.sqlite3')
    import accounts
    for name in ('e2e-account', 'account-ui', 'multi-industry', 'ai-review'):
        credentials = {'username': 'accept_' + secrets.token_hex(5), 'password': secrets.token_urlsafe(24), 'invite': secrets.token_urlsafe(24)}
        with accounts.database() as db:
            db.execute('INSERT INTO invites VALUES(?,?,?)', (accounts.digest(credentials['invite']), int(time.time()) + 3600, 10))
            if name == 'ai-review':
                db.execute('INSERT INTO users VALUES(?,?,?,?)', (secrets.token_hex(16), credentials['username'], accounts.password_hash(credentials['password']), 5))
        (directory / (name + '.json')).write_text(json.dumps(credentials), encoding='utf-8')
    print('Isolated browser acceptance credentials prepared in artifacts; values are not displayed.')
    print('Start acceptance API with STOCKLENS_ACCOUNT_DB=artifacts/browser-acceptance.sqlite3, port 8001.')
    print('Paid AI calls occur only when running workflow.spec.ts or ai-review.spec.ts.')


if __name__ == '__main__':
    main()
