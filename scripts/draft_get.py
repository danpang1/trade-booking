"""Fetch one bookings_draft row owned by the acting user.

Stdin: {"id": 42, "_acting_user": "alice"}
Stdout success: {"ok": true, "draft": {...public...}}
Stdout 404:     {"ok": false, "code": "not_found", "error": "draft not found"}

Drafts owned by other users return 404 (not 403) — avoids leaking
existence to unauthorized callers.
"""
from __future__ import annotations
import json
import sys

import draft_db


def _get(draft_id: int, acting: str) -> dict | None:
    conn = draft_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM bookings_draft "
                    "WHERE id = %s AND created_by = %s",
                    (draft_id, acting),
                )
                r = cur.fetchone()
                if r is None:
                    return None
                return draft_db.row_to_public(cur, r)
    finally:
        conn.close()


def main() -> int:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig").strip() or "{}"
        body = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": "invalid JSON on stdin", "detail": str(e)}))
        return 2

    draft_id = body.get("id")
    acting = body.get("_acting_user")
    if not isinstance(draft_id, int) or draft_id <= 0:
        print(json.dumps({"ok": False, "error": "id must be positive integer"}))
        return 3
    if not isinstance(acting, str) or not acting:
        print(json.dumps({"ok": False, "error": "missing _acting_user (server bug)"}))
        return 3

    try:
        draft = _get(draft_id, acting)
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5

    if draft is None:
        print(json.dumps({"ok": False, "code": "not_found", "error": "draft not found"}))
        return 4

    print(json.dumps({"ok": True, "draft": draft}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
