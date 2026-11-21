"""Svenbot Link's *local* durable, fail-closed task inbox.

No remote listener, relay, model or executable tool calls live here. The inbox
is a state ledger for future authenticated cross-device transport, not a task
executor. Its SQLite database is local to the Mac and must not be synced.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path

MAX_TEXT = 4000
STATES = frozenset({"queued", "waiting_approval", "approved", "running",
                    "completed", "failed", "cancelled", "uncertain"})
TERMINAL = frozenset({"completed", "failed", "cancelled", "uncertain"})
TRANSITIONS = {
    "queued": {"waiting_approval", "running", "cancelled"},
    "waiting_approval": {"approved", "cancelled"},
    "approved": {"running", "cancelled"},
    "running": {"completed", "failed", "uncertain"},
    "completed": set(), "failed": set(), "cancelled": set(), "uncertain": set(),
}


class TaskConflict(ValueError):
    """An invalid, stale, conflicting or unauthorized state transition."""


def _text(value: str, name: str, limit: int = MAX_TEXT) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
        raise ValueError(f"{name} must contain 1–{limit} characters")
    if any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise ValueError(f"{name} contains control characters")
    return value.strip()


class TaskInbox:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, isolation_level=None, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout=10000")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY, device_id TEXT NOT NULL, request_id TEXT NOT NULL,
            intent TEXT NOT NULL, intent_hash TEXT NOT NULL,
            state TEXT NOT NULL, revision INTEGER NOT NULL,
            created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
            result TEXT, UNIQUE(device_id, request_id))""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS events (
            task_id TEXT NOT NULL, revision INTEGER NOT NULL, state TEXT NOT NULL,
            at INTEGER NOT NULL, PRIMARY KEY(task_id, revision),
            FOREIGN KEY(task_id) REFERENCES tasks(id))""")

    def close(self):
        self.db.close()

    def _read(self, task_id: str):
        row = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise KeyError("Unknown task")
        return dict(row)

    def submit(self, *, device_id: str, request_id: str, intent: str) -> dict:
        """Idempotent by (device, request). Reuse with different intent is rejected."""
        device_id = _text(device_id, "device_id", 128)
        request_id = _text(request_id, "request_id", 128)
        intent = _text(intent, "intent")
        digest = hashlib.sha256(intent.encode("utf-8")).hexdigest()
        now = int(time.time())
        self.db.execute("BEGIN IMMEDIATE")
        try:
            existing = self.db.execute(
                "SELECT * FROM tasks WHERE device_id=? AND request_id=?",
                (device_id, request_id)).fetchone()
            if existing:
                if existing["intent_hash"] != digest:
                    raise TaskConflict("Request ID already used for different intent")
                result = dict(existing)
            else:
                task_id = uuid.uuid4().hex
                self.db.execute("""INSERT INTO tasks
                    (id, device_id, request_id, intent, intent_hash, state, revision, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 'queued', 0, ?, ?)""",
                    (task_id, device_id, request_id, intent, digest, now, now))
                self.db.execute("INSERT INTO events VALUES (?, 0, 'queued', ?)", (task_id, now))
                result = self._read(task_id)
            self.db.execute("COMMIT")
            return result
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def get(self, task_id: str) -> dict:
        return self._read(_text(task_id, "task_id", 64))

    def list(self, *, device_id: str, limit: int = 50) -> list[dict]:
        device_id = _text(device_id, "device_id", 128)
        if not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be 1–100")
        return [dict(row) for row in self.db.execute(
            "SELECT * FROM tasks WHERE device_id=? ORDER BY created_at DESC, id DESC LIMIT ?",
            (device_id, limit))]

    def transition(self, task_id: str, *, expected_revision: int, new_state: str,
                   actor: str, result: str | None = None) -> dict:
        """CAS prevents duplicate approvals and races; no execution side effects."""
        task_id = _text(task_id, "task_id", 64)
        actor = _text(actor, "actor", 128)
        if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 0:
            raise ValueError("Invalid expected revision")
        if new_state not in STATES:
            raise ValueError("Unknown state")
        if result is not None:
            result = _text(result, "result")
        if new_state in ("completed", "failed", "uncertain") and result is None:
            raise ValueError("Terminal execution state requires a result")
        if result is not None and new_state not in ("completed", "failed", "uncertain"):
            raise ValueError("Result is only accepted for execution terminal states")
        # A future transport must authenticate actor against device enrollment.
        # This local ledger enforces *role* restrictions, not identity proofs.
        allowed_actor = {
            "queued": {"mac"},
            "waiting_approval": {"mac"},
            "approved": {"owner"},
            "running": {"mac"},
            "completed": {"mac"}, "failed": {"mac"},
            "uncertain": {"mac"}, "cancelled": {"owner", "mac"},
        }
        if actor not in allowed_actor[new_state]:
            raise TaskConflict("Actor role cannot enter requested state")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self._read(task_id)
            if row["revision"] != expected_revision:
                raise TaskConflict("Stale revision; refresh task before changing it")
            if new_state not in TRANSITIONS[row["state"]]:
                raise TaskConflict(f"Transition {row['state']} -> {new_state} denied")
            if row["state"] == "waiting_approval" and new_state == "cancelled" and actor != "owner":
                raise TaskConflict("Only owner may reject an approval")
            now = int(time.time())
            next_revision = expected_revision + 1
            self.db.execute("""UPDATE tasks SET state=?, revision=?, updated_at=?, result=?
                               WHERE id=? AND revision=?""",
                            (new_state, next_revision, now, result, task_id, expected_revision))
            self.db.execute("INSERT INTO events VALUES (?, ?, ?, ?)",
                            (task_id, next_revision, new_state, now))
            result_row = self._read(task_id)
            self.db.execute("COMMIT")
            return result_row
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def recover_interrupted(self) -> int:
        """On restart mark in-flight work UNCERTAIN, never replay side effects."""
        now = int(time.time())
        self.db.execute("BEGIN IMMEDIATE")
        try:
            rows = self.db.execute("SELECT id, revision FROM tasks WHERE state='running'").fetchall()
            for row in rows:
                revision = row["revision"] + 1
                self.db.execute("""UPDATE tasks SET state='uncertain', revision=?,
                    updated_at=?, result='Interrupted while running; reconcile externally before retry'
                    WHERE id=?""", (revision, now, row["id"]))
                self.db.execute("INSERT INTO events VALUES (?, ?, 'uncertain', ?)",
                                (row["id"], revision, now))
            self.db.execute("COMMIT")
            return len(rows)
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def history(self, task_id: str) -> list[dict]:
        task_id = _text(task_id, "task_id", 64)
        self._read(task_id)
        return [dict(r) for r in self.db.execute(
            "SELECT revision, state, at FROM events WHERE task_id=? ORDER BY revision",
            (task_id,))]
