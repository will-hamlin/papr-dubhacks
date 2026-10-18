"""Operator-owned accounts, company policies, credentials and expiring OAuth records."""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError

from .models import Policy, User

PASSWORDS = PasswordHasher()
# Unknown accounts perform the same password work as known accounts.
DUMMY_PASSWORD = PASSWORDS.hash(secrets.token_urlsafe(32))


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class AccountStore:
    def __init__(self, path: Path, clock=None):
        self.path = path
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS companies (id TEXT PRIMARY KEY, config TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
                    company_id TEXT NOT NULL REFERENCES companies(id), config TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS clients (id TEXT PRIMARY KEY, config TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS credentials (
                    hash TEXT PRIMARY KEY, kind TEXT NOT NULL, data TEXT NOT NULL,
                    expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS credentials_expiry ON credentials(expires);
                CREATE TABLE IF NOT EXISTS account_purchases (
                    order_id TEXT PRIMARY KEY, company_id TEXT NOT NULL, job TEXT,
                    day TEXT NOT NULL, total INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS rate_limits (
                    key TEXT PRIMARY KEY, starts REAL NOT NULL, count INTEGER NOT NULL);
            ''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def now(self):
        return self.clock().timestamp()

    def company(self, raw: dict):
        policy = Policy.model_validate(raw)
        ZoneInfo(policy.timezone)
        if policy.spent_date is None:
            policy.spent_date = self.clock().astimezone(ZoneInfo(policy.timezone)).date().isoformat()
        with self.db() as db:
            db.execute('INSERT INTO companies VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET config=excluded.config',
                       (policy.id, policy.model_dump_json()))
        return policy.id

    def create_account(self, company_id: str, raw: dict, password: str):
        user = User.model_validate(raw)
        email = user.email.strip().casefold()
        if '@' not in email or len(email) > 254:
            raise ValueError('a valid login email is required')
        if not 12 <= len(password) <= 1024:
            raise ValueError('password must have 12 to 1024 characters')
        account_id = 'a_' + secrets.token_hex(16)
        with self.db() as db:
            db.execute('INSERT INTO accounts(id,email,password,company_id,config) VALUES (?,?,?,?,?)',
                       (account_id, email, PASSWORDS.hash(password), company_id, user.model_dump_json()))
        return account_id

    def update_user(self, account_id: str, raw: dict):
        user = User.model_validate(raw)
        with self.db() as db:
            if not db.execute('UPDATE accounts SET config=? WHERE id=?', (user.model_dump_json(), account_id)).rowcount:
                raise ValueError('unknown account')

    def disable(self, account_id: str):
        with self.db() as db:
            db.execute('UPDATE accounts SET enabled=0 WHERE id=?', (account_id,))
        self.revoke_account(account_id)

    def profile(self, account_id: str):
        with self.db() as db:
            row = db.execute('SELECT a.config AS user, c.config AS company FROM accounts a '
                             'JOIN companies c ON a.company_id=c.id WHERE a.id=? AND a.enabled=1',
                             (account_id,)).fetchone()
        return (User.model_validate_json(row['user']), Policy.model_validate_json(row['company'])) if row else None

    def authenticate(self, email: str, password: str):
        if len(password) > 1024 or len(email) > 254:
            return None
        with self.db() as db:
            row = db.execute('SELECT * FROM accounts WHERE email=?', (email.strip().casefold(),)).fetchone()
        try:
            PASSWORDS.verify(row['password'] if row else DUMMY_PASSWORD, password)
        except (VerificationError, InvalidHashError):
            return None
        return row['id'] if row and row['enabled'] else None

    def rate_limit(self, key: str, limit: int, seconds=300):
        """Persistent limits, without storing login names or trusting forwarded IP headers."""
        key = digest(key)
        now = self.now()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM rate_limits WHERE starts < ?', (now - seconds,))
            row = db.execute('SELECT count FROM rate_limits WHERE key=?', (key,)).fetchone()
            if row and row['count'] >= limit:
                return False
            db.execute('INSERT INTO rate_limits VALUES (?,?,1) ON CONFLICT(key) DO UPDATE SET count=count+1',
                       (key, now))
        return True

    def put(self, kind: str, data: dict, ttl: int, db=None):
        token = secrets.token_urlsafe(32)
        args = (digest(token), kind, json.dumps(data), self.now() + ttl)
        if db is not None:
            db.execute('INSERT INTO credentials(hash,kind,data,expires) VALUES (?,?,?,?)', args)
        else:
            with self.db() as conn:
                conn.execute('DELETE FROM credentials WHERE expires < ?', (self.now() - 86400,))
                conn.execute('INSERT INTO credentials(hash,kind,data,expires) VALUES (?,?,?,?)', args)
        return token

    def get(self, token: str, kind: str, db=None, include_used=False):
        if not isinstance(token, str) or len(token) > 200:
            return None
        if db is None:
            with self.db() as conn:
                return self.get(token, kind, conn, include_used)
        row = db.execute('SELECT * FROM credentials WHERE hash=? AND kind=? AND expires>?',
                         (digest(token), kind, self.now())).fetchone()
        if not row or (row['used'] and not include_used):
            return None
        return {**json.loads(row['data']), '_expires': row['expires'], '_used': bool(row['used'])}

    def consume(self, token: str, db):
        return db.execute('UPDATE credentials SET used=1 WHERE hash=? AND used=0 AND expires>?',
                          (digest(token), self.now())).rowcount == 1

    def revoke_family(self, family: str, db):
        db.execute("UPDATE credentials SET used=1 WHERE json_extract(data,'$.family')=?", (family,))

    def revoke_account(self, account_id: str):
        with self.db() as db:
            db.execute("UPDATE credentials SET used=1 WHERE json_extract(data,'$.account_id')=?", (account_id,))

    def save_client(self, config: dict):
        client_id = 'c_' + secrets.token_hex(16)
        with self.db() as db:
            db.execute('INSERT INTO clients VALUES (?,?)', (client_id, json.dumps(config)))
        return client_id

    def client(self, client_id: str):
        with self.db() as db:
            row = db.execute('SELECT config FROM clients WHERE id=?', (client_id,)).fetchone()
        return json.loads(row['config']) if row else None

    def spend(self, policy: Policy, job: str | None):
        today = self.clock().astimezone(ZoneInfo(policy.timezone)).date().isoformat()
        with self.db() as db:
            daily = db.execute('SELECT COALESCE(SUM(total),0) FROM account_purchases WHERE company_id=? AND day=?',
                               (policy.id, today)).fetchone()[0]
            on_job = db.execute('SELECT COALESCE(SUM(total),0) FROM account_purchases WHERE company_id=? AND job=?',
                                (policy.id, job)).fetchone()[0] if job else 0
        return (daily + (policy.spent_today_cents if policy.spent_date == today else 0),
                on_job + policy.spent_by_job.get(job, 0))

    def record_purchase(self, order_id, company_id, job, total):
        with self.db() as db:
            row = db.execute('SELECT config FROM companies WHERE id=?', (company_id,)).fetchone()
            policy = Policy.model_validate_json(row['config'])
            today = self.clock().astimezone(ZoneInfo(policy.timezone)).date().isoformat()
            db.execute('INSERT OR IGNORE INTO account_purchases VALUES (?,?,?,?,?)',
                       (order_id, company_id, job, today, total))
            return db.execute('SELECT total FROM account_purchases WHERE order_id=?', (order_id,)).fetchone()[0]
