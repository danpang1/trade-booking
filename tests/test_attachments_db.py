"""Tests for trade-booking/scripts/attachments_db.py — pure-logic only.

The functions take a cursor; tests use a fake cursor that records SQL +
params for inspection. The real psycopg2 cursor is exercised by manual
smoke in the writer-script tasks.
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "trade-booking" / "scripts"))

import attachments_db  # noqa: E402


class FakeCursor:
    def __init__(self, fetch_rows=None, fetch_cols=None):
        self.calls = []
        self._fetch_rows = fetch_rows or []
        self._fetch_cols = fetch_cols or []
        self.description = [type("D", (), {"name": c})() for c in self._fetch_cols]

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchall(self):
        return list(self._fetch_rows)


def _att(file_name="confirm.pdf", drive_file_id="abc"):
    return {
        "drive_folder_id": "FOLDER1",
        "drive_folder_url": "https://drive.google.com/drive/folders/FOLDER1",
        "file_name": file_name,
        "drive_file_id": drive_file_id,
        "drive_view_url": f"https://drive.google.com/file/d/{drive_file_id}/view",
        "mime_type": "application/pdf",
        "size_bytes": 1024,
    }


def test_insert_attachments_writes_one_row_per_file_in_order():
    cur = FakeCursor()
    rows = attachments_db.insert_attachments(
        cur,
        deal_ref="MCF00000042",
        attachments=[_att("a.pdf", "ID_A"), _att("b.png", "ID_B")],
        user_id="PWY",
    )
    assert len(cur.calls) == 2
    assert "INSERT INTO trade_attachments" in cur.calls[0][0]
    # Ordered by input array (params is a tuple; file_name is at index 3
    # per the bind sequence: deal_ref, drive_folder_id, drive_folder_url,
    # file_name, ...).
    assert "a.pdf" in cur.calls[0][1]
    assert "b.png" in cur.calls[1][1]
    # All bound params include user_id at the uploaded_by position
    for sql, params in cur.calls:
        assert "PWY" in params
    # Returns dicts shaped like the table rows
    assert len(rows) == 2
    assert rows[0]["file_name"] == "a.pdf"
    assert rows[1]["drive_file_id"] == "ID_B"


def test_insert_attachments_empty_list_is_noop():
    cur = FakeCursor()
    rows = attachments_db.insert_attachments(
        cur, deal_ref="MCF00000042", attachments=[], user_id="PWY"
    )
    assert cur.calls == []
    assert rows == []


def test_get_attachments_filters_to_uploaded_status_and_orders_by_time():
    cur = FakeCursor(
        fetch_rows=[
            ("MCF00000042", "FOLDER1", "url", "a.pdf", "ID_A",
             "view", "application/pdf", 1024, "uploaded",
             "2026-05-19T08:14:22+00:00", "PWY"),
        ],
        fetch_cols=[
            "deal_ref", "drive_folder_id", "drive_folder_url",
            "file_name", "drive_file_id", "drive_view_url",
            "mime_type", "size_bytes", "status", "uploaded_at", "uploaded_by",
        ],
    )
    rows = attachments_db.get_attachments_for_deal_ref(cur, deal_ref="MCF00000042")
    assert len(cur.calls) == 1
    sql, params = cur.calls[0]
    assert "FROM trade_attachments" in sql
    assert "WHERE deal_ref = %s" in sql
    assert "status = 'uploaded'" in sql
    assert "ORDER BY uploaded_at" in sql
    assert params == ("MCF00000042",)
    assert rows[0]["file_name"] == "a.pdf"
    assert rows[0]["status"] == "uploaded"
