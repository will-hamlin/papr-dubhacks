"""SQLite records for authorization decisions, compiled proofs, and engine output."""
import json
import sqlite3
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from pathlib import Path


class ConflictError(Exception):
    pass


class MissingRequestError(Exception):
    pass


class RequestStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS requests (
                order_id TEXT PRIMARY KEY, handoff TEXT NOT NULL,
                status TEXT NOT NULL, result TEXT NOT NULL DEFAULT '{}')''')
            db.execute('''CREATE TABLE IF NOT EXISTS candidate_submissions (
                order_id TEXT NOT NULL, submission_id TEXT NOT NULL, payload TEXT NOT NULL,
                result TEXT, PRIMARY KEY (order_id, submission_id))''')

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            yield db

    def receive(self, payload: dict) -> dict:
        encoded = json.dumps(payload, sort_keys=True)
        status = 'queued' if payload['authorization']['accepted'] else 'rejected'
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO requests (order_id, handoff, status) VALUES (?, ?, ?)',
                       (payload['order_id'], encoded, status))
            stored = db.execute('SELECT handoff FROM requests WHERE order_id = ?', (payload['order_id'],)).fetchone()
            if stored[0] != encoded:
                raise ConflictError('order_id already belongs to a different handoff')
        return self.get(payload['order_id'])

    def get(self, order_id: str):
        with self.connect() as db:
            row = db.execute('SELECT handoff, status, result FROM requests WHERE order_id = ?', (order_id,)).fetchone()
        if row is None:
            return None
        return {'order_id': order_id, 'handoff': json.loads(row[0]), 'status': row[1], 'result': json.loads(row[2])}

    def next_queued(self):
        with self.connect() as db:
            row = db.execute("SELECT order_id FROM requests WHERE status IN ('queued', 'candidates_queued', 'verification_queued') ORDER BY rowid LIMIT 1").fetchone()
        return self.get(row[0]) if row else None

    def save(self, order_id: str, status: str, result: dict):
        with self.connect() as db:
            db.execute('UPDATE requests SET status = ?, result = ? WHERE order_id = ?',
                       (status, json.dumps(result), order_id))

    def recover(self):
        with self.connect() as db:
            db.execute("UPDATE requests SET status = 'interrupted' WHERE status = 'processing'")

    @staticmethod
    def retry_status(result):
        return {'preparing': 'queued', 'agent_verification': 'candidates_queued',
                'managed_verification': 'verification_queued'}.get(result.get('processing_stage'))

    def interrupted(self):
        with self.connect() as db:
            rows = db.execute("SELECT order_id, result FROM requests WHERE status='interrupted' ORDER BY rowid").fetchall()
        return [{'order_id': order_id, 'stage': json.loads(result).get('processing_stage', 'unknown'),
                 'retryable': self.retry_status(json.loads(result)) is not None} for order_id, result in rows]

    def retry_interrupted(self, order_id):
        """Only replay stages known not to submit a request to an external backend."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT status, result FROM requests WHERE order_id=?', (order_id,)).fetchone()
            if row is None:
                raise MissingRequestError('unknown request')
            if row[0] != 'interrupted':
                raise ConflictError('only interrupted requests can be retried')
            result = json.loads(row[1])
            status = self.retry_status(result)
            if status is None:
                raise ConflictError('external submission may have occurred; reconcile with the backend before any new request')
            result['recovery'] = {'retries': result.get('recovery', {}).get('retries', 0) + 1,
                                  'retried_at': datetime.now(timezone.utc).isoformat(),
                                  'stage': result['processing_stage']}
            db.execute('UPDATE requests SET status=?, result=? WHERE order_id=?',
                       (status, json.dumps(result), order_id))
        return {'order_id': order_id, 'status': status}

    def submitted(self):
        with self.connect() as db:
            ids = [row[0] for row in db.execute("SELECT order_id FROM requests WHERE status = 'submitted'")]
        return [self.get(order_id) for order_id in ids]

    def add_candidates(self, order_id: str, submission: dict):
        encoded = json.dumps(submission, sort_keys=True)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT handoff, status, result FROM requests WHERE order_id = ?', (order_id,)).fetchone()
            if row is None:
                raise MissingRequestError('unknown request')
            handoff, status, result = json.loads(row[0]), row[1], json.loads(row[2])
            if not handoff['authorization']['accepted'] or handoff['request'].get('search_mode', 'managed') != 'agent':
                raise ConflictError('request does not accept personal-agent candidates')
            prior = db.execute('SELECT payload, result FROM candidate_submissions WHERE order_id = ? AND submission_id = ?',
                               (order_id, submission['submission_id'])).fetchone()
            if prior:
                if prior[0] != encoded:
                    raise ConflictError('submission_id already belongs to different candidates')
                return {'order_id': order_id, 'status': 'verification_complete' if prior[1] is not None else status,
                        'submission_id': submission['submission_id'], 'duplicate': True}
            if status not in ('awaiting_candidates', 'verification_complete'):
                raise ConflictError('request is not ready for a candidate submission')
            if submission['requirements_id'] != result.get('requirements_id'):
                raise ConflictError('candidates refer to different request requirements')
            db.execute('INSERT INTO candidate_submissions VALUES (?, ?, ?, NULL)',
                       (order_id, submission['submission_id'], encoded))
            result['candidate_submission'] = submission
            result.pop('verification', None)
            db.execute("UPDATE requests SET status = 'candidates_queued', result = ? WHERE order_id = ?",
                       (json.dumps(result), order_id))
        return {'order_id': order_id, 'status': 'candidates_queued', 'submission_id': submission['submission_id']}

    def finish_candidates(self, order_id: str, result: dict):
        with self.connect() as db:
            db.execute('UPDATE candidate_submissions SET result = ? WHERE order_id = ? AND submission_id = ?',
                       (json.dumps(result['verification']), order_id, result['candidate_submission']['submission_id']))
            db.execute("UPDATE requests SET status = 'verification_complete', result = ? WHERE order_id = ?",
                       (json.dumps(result), order_id))
