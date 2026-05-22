"""Pure-logic tests for user_reject."""
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
import user_reject  # noqa: E402


class FakeCursor:
    def __init__(self, delete_rowcount=1, existing_status=None):
        self.calls = []
        self.rowcount = delete_rowcount
        self._existing_status = existing_status
    def execute(self, sql, params=None):
        self.calls.append((sql, params))
    def fetchone(self):
        return (self._existing_status,) if self._existing_status else None
    def __enter__(self): return self
    def __exit__(self, *a): pass


class FakeConn:
    def __init__(self, cur): self._c = cur
    def cursor(self): return self._c
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def close(self): pass


def _run(payload, delete_rowcount, existing_status=None):
    cur = FakeCursor(delete_rowcount=delete_rowcount, existing_status=existing_status)
    conn = FakeConn(cur)
    fake_in = io.BytesIO(json.dumps(payload).encode("utf-8"))
    fake_in.buffer = fake_in
    out = io.StringIO()
    with patch.object(user_db, "connect", return_value=conn), \
         patch.object(sys, "stdin", fake_in), \
         patch.object(sys, "stdout", out):
        code = user_reject.main()
    return code, json.loads(out.getvalue() or "{}")


def test_reject_pending_deletes_row():
    code, body = _run({"user_id": 1}, delete_rowcount=1)
    assert code == 0
    assert body == {"ok": True}


def test_reject_active_returns_conflict():
    code, body = _run({"user_id": 1}, delete_rowcount=0, existing_status="active")
    assert code == 5
    assert body.get("code") == "conflict"


def test_reject_nonexistent_returns_404():
    code, body = _run({"user_id": 999}, delete_rowcount=0, existing_status=None)
    assert code == 4
