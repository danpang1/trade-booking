"""List bookings_draft rows owned by the acting user.

Stdin:
  {"_acting_user": "alice",
   "status": "PENDING_REVIEW" | "APPROVED" | "REJECTED" | null,
   "batch_id": "<uuid>" | null}

Stdout: {"ok": true, "drafts": [{...public...}, ...]}
"""
from __future__ import annotations
import json
import sys

import draft_db


def _list(acting: str, status, batch_id) -> list[dict]:
    where = ["created_by = %s"]
    args: list = [acting]
    if status is not None:
        if status not in draft_db.STATUSES:
            raise draft_db.ValidationError(
                f"status must be one of {draft_db.STATUSES}, got {status!r}"
            )
        where.append("status = %s")
        args.append(status)
    if batch_id is not None:
        draft_db.validate_uuid(batch_id)
        where.append("batch_id = %s")
        args.append(batch_id)

    sql = (
        "SELECT * FROM bookings_draft "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY created_at DESC"
    )

    conn = draft_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(args))
                rows = cur.fetchall()
                return [draft_db.row_to_public(cur, r) for r in rows]
    finally:
        conn.close()


def main() -> int:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig").strip() or "{}"
        body = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": "invalid JSON on stdin", "detail": str(e)}))
        return 2

    acting = body.get("_acting_user")
    if not isinstance(acting, str) or not acting:
        print(json.dumps({"ok": False, "error": "missing _acting_user (server bug)"}))
        return 3

    try:
        drafts = _list(acting, body.get("status"), body.get("batch_id"))
    except draft_db.ValidationError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 3
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5

    print(json.dumps({"ok": True, "drafts": drafts}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
