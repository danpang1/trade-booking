"""Pure-logic tests for user_approve using FakeCursor."""
from __future__ import annotations
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import pytest  # noqa: E402
import user_db  # noqa: E402
import user_approve  # noqa: E402


class FakeCursor:
    def __init__(self, rowcount=1):
        self.calls = []
        self.rowcount = rowcount
        self.description = None
    def execute(self, sql, params=None):
        self.calls.append((sql, params))
    def fetchone(self):
        return None
    def __enter__(self): return self
    def __exit__(self, *a): pass


class FakeConn:
    def __init__(self, cur): self._c = cur
    def cursor(self): return self._c
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def close(self): pass


def _run(payload, rowcount):
    cur = FakeCursor(rowcount=rowcount)
    conn = FakeConn(cur)
    # For non-zero rowcount path, the script then SELECTs the row — give it back something
    if rowcount > 0:
        cur.fetchone = lambda: (1, "u", "u@x.z", "user", "active", "2026-05-22T00:00:00+00:00", "admin1")
        cur.description = [type("D",(),{"name": n})() for n in
                           ("id","username","email","role","status","approved_at","approved_by")]
    fake_in = io.BytesIO(json.dumps(payload).encode("utf-8"))
    fake_in.buffer = fake_in
    out = io.StringIO()
    with patch.object(user_db, "connect", return_value=conn), \
         patch.object(sys, "stdin", fake_in), \
         patch.object(sys, "stdout", out):
        code = user_approve.main()
    return code, json.loads(out.getvalue() or "{}")


def test_approve_pending_user_returns_ok():
    code, body = _run({"user_id": 1, "role": "user", "_acting_user": "admin1"}, rowcount=1)
    assert code == 0
    assert body["ok"] is True
    assert body["user"]["status"] == "active"


def test_approve_nonexistent_returns_404():
    code, body = _run({"user_id": 999, "role": "user", "_acting_user": "admin1"}, rowcount=0)
    assert code == 4
    assert body["ok"] is False


def test_approve_invalid_role_returns_400():
    code, body = _run({"user_id": 1, "role": "root", "_acting_user": "admin1"}, rowcount=1)
    assert code == 3
    assert "role" in body["error"].lower()


def test_approve_missing_user_id_returns_400():
    code, body = _run({"role": "user", "_acting_user": "admin1"}, rowcount=0)
    assert code == 3
