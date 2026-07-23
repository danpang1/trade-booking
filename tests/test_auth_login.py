"""Behavioural tests for auth_login.py status branching.

Uses a FakeConnection that returns canned rows so we don't need real DB
or bcrypt round-trips. The actual password check is delegated to
user_db.verify_password, which is unit-tested separately.
"""
from __future__ import annotations
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import pytest  # noqa: E402
import user_db  # noqa: E402
import auth_login  # noqa: E402


class FakeCursor:
    def __init__(self, user_row=None):
        self._user_row = user_row
        self.calls = []
        self.description = None

    def execute(self, sql, params=None):
        self.calls.append((sql.strip().split()[0].upper(), params))

    def fetchone(self):
        return self._user_row

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


class FakeConn:
    def __init__(self, cursor):
        self._cur = cursor
        self.closed = False

    def cursor(self):
        return self._cur

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def close(self):
        self.closed = True


def _run(stdin_payload, user_row):
    """Drive auth_login.main() with a fake connection + given user row."""
    cur = FakeCursor(user_row=user_row)
    conn = FakeConn(cur)
    fake_in = io.BytesIO(json.dumps(stdin_payload).encode("utf-8"))
    fake_in.buffer = fake_in  # match sys.stdin.buffer pattern
    out = io.StringIO()
    with patch.object(user_db, "connect", return_value=conn), \
         patch.object(sys, "stdin", fake_in), \
         patch.object(sys, "stdout", out):
        code = auth_login.main()
    return code, json.loads(out.getvalue() or "{}"), cur


def _pending_row():
    pw_hash = user_db.hash_password("CorrectHorse9!")
    # (id, username, email, role, password_hash, status, access_tms)
    return (1, "pending_user", "p@x.z", None, pw_hash, "pending", True)


def _active_row():
    pw_hash = user_db.hash_password("CorrectHorse9!")
    return (2, "active_user", "a@x.z", "user", pw_hash, "active", True)


def _no_tms_row():
    pw_hash = user_db.hash_password("CorrectHorse9!")
    return (3, "ace_only_user", "n@x.z", "user", pw_hash, "active", False)


def test_pending_account_correct_password_returns_pending_message():
    code, body, cur = _run(
        {"username": "pending_user", "password": "CorrectHorse9!"},
        _pending_row(),
    )
    assert code == 6
    assert body == {"ok": False, "error": "Account pending admin approval"}
    # No INSERT INTO sessions should have run
    assert not any(verb == "INSERT" for verb, _ in cur.calls), cur.calls


def test_pending_account_wrong_password_returns_invalid_credentials():
    code, body, cur = _run(
        {"username": "pending_user", "password": "WRONG"},
        _pending_row(),
    )
    assert code == 6
    assert body == {"ok": False, "error": "invalid credentials"}


def test_no_tms_access_correct_password_is_refused():
    code, body, cur = _run(
        {"username": "ace_only_user", "password": "CorrectHorse9!"},
        _no_tms_row(),
    )
    assert code == 6
    assert body == {"ok": False, "error": "Account has no TMS access — ask an admin"}
    assert not any(verb == "INSERT" for verb, _ in cur.calls), cur.calls


def test_active_account_correct_password_returns_session():
    cur = FakeCursor(user_row=_active_row())
    fetches = [_active_row(), ("11111111-1111-1111-1111-111111111111", datetime(2099, 1, 1, tzinfo=timezone.utc))]
    cur.fetchone = lambda: fetches.pop(0)
    conn = FakeConn(cur)
    fake_in = io.BytesIO(json.dumps(
        {"username": "active_user", "password": "CorrectHorse9!"}
    ).encode("utf-8"))
    fake_in.buffer = fake_in
    out = io.StringIO()
    with patch.object(user_db, "connect", return_value=conn), \
         patch.object(sys, "stdin", fake_in), \
         patch.object(sys, "stdout", out):
        code = auth_login.main()
    assert code == 0
    assert any(verb == "INSERT" for verb, _ in cur.calls)
