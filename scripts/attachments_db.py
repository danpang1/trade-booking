"""Shared helper for attachments_get + writers (cashflow_insert/amend,
loan_insert/amend).

The writer scripts call insert_attachments inside their own transaction.
The reader script calls get_attachments_for_deal_ref.

Pure-logic by design: functions take an externally-managed cursor so
they participate in whatever transaction the caller already owns.
"""
from __future__ import annotations
from typing import Any, Iterable


_INSERT_SQL = """
INSERT INTO trade_attachments (
  deal_ref, drive_folder_id, drive_folder_url,
  file_name, drive_file_id, drive_view_url,
  mime_type, size_bytes, uploaded_by
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
RETURNING id, deal_ref, drive_folder_id, drive_folder_url,
          file_name, drive_file_id, drive_view_url,
          mime_type, size_bytes, status, uploaded_at, uploaded_by
"""

_SELECT_SQL = """
SELECT deal_ref, drive_folder_id, drive_folder_url,
       file_name, drive_file_id, drive_view_url,
       mime_type, size_bytes, status, uploaded_at, uploaded_by
  FROM trade_attachments
 WHERE deal_ref = %s
   AND status = 'uploaded'
 ORDER BY uploaded_at ASC, id ASC
"""


def insert_attachments(
    cur: Any,
    *,
    deal_ref: str,
    attachments: Iterable[dict],
    user_id: str,
) -> list[dict]:
    """Insert one row per attachment. Returns the inserted rows as dicts.

    `cur` is a psycopg2 cursor owned by the caller (no BEGIN/COMMIT here).
    """
    rows: list[dict] = []
    for a in attachments:
        cur.execute(
            _INSERT_SQL,
            (
                deal_ref,
                a["drive_folder_id"],
                a["drive_folder_url"],
                a["file_name"],
                a["drive_file_id"],
                a["drive_view_url"],
                a["mime_type"],
                int(a["size_bytes"]),
                user_id,
            ),
        )
        rows.append({
            "deal_ref": deal_ref,
            "drive_folder_id": a["drive_folder_id"],
            "drive_folder_url": a["drive_folder_url"],
            "file_name": a["file_name"],
            "drive_file_id": a["drive_file_id"],
            "drive_view_url": a["drive_view_url"],
            "mime_type": a["mime_type"],
            "size_bytes": int(a["size_bytes"]),
            "status": "uploaded",
            "uploaded_by": user_id,
        })
    return rows


def get_attachments_for_deal_ref(cur: Any, deal_ref: str) -> list[dict]:
    """Return live ('uploaded') attachments for a deal_ref, ordered by upload time."""
    cur.execute(_SELECT_SQL, (deal_ref,))
    rows = cur.fetchall()
    cols = [d.name for d in cur.description]
    return [
        {col: _normalize(col, val) for col, val in zip(cols, row)}
        for row in rows
    ]


def _normalize(col: str, val):
    # Stringify timestamps so the JSON serializer doesn't need a custom encoder.
    if col == "uploaded_at" and val is not None and not isinstance(val, str):
        return val.isoformat()
    return val
