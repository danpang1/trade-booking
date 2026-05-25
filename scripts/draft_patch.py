"""Update the payload of a PENDING_REVIEW draft owned by the acting user.

Stdin: {"id": 42, "payload": {...new payload...}, "_acting_user": "alice"}

Stdout success:  {"ok": true, "row": {...public...}}
Stdout 404:      {"ok": false, "code": "not_found", "error": "draft not found"}
Stdout 409:      {"ok": false, "code": "conflict", "error": "draft is not PENDING_REVIEW"}
Stdout 400:      {"ok": false, "error": "<validation>"}
"""
from __future__ import annotations
import json
import sys

import draft_db


def _patch(draft_id: int, new_payload, acting: str) -> tuple[str, dict | None]:
    """Returns (status, row). status in {'ok','not_found','conflict'}."""
    if not isinstance(new_payload, dict):
        raise draft_db.ValidationError("payload must be an object")
    # Stamp user_id, then shape-validate against the current category
    # of the draft (loaded inside the txn for consistency).
    conn = draft_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT category, status FROM bookings_draft "
                    "WHERE id = %s AND created_by = %s",
                    (draft_id, acting),
                )
                row = cur.fetchone()
                if row is None:
                    return "not_found", None
                category, status = row
                if status != "PENDING_REVIEW":
                    return "conflict", None

                payload = {**new_payload, "user_id": acting}
                draft_db.validate_payload_for_category(category, payload)

                cur.execute(
                    "UPDATE bookings_draft "
                    "   SET payload = %s, updated_at = now() "
                    " WHERE id = %s "
                    "RETURNING *",
                    (json.dumps(payload), draft_id),
                )
                return "ok", draft_db.row_to_public(cur, cur.fetchone())
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
        status, row = _patch(draft_id, body.get("payload"), acting)
    except draft_db.ValidationError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 3
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5

    if status == "not_found":
        print(json.dumps({"ok": False, "code": "not_found", "error": "draft not found"}))
        return 4
    if status == "conflict":
        print(json.dumps({"ok": False, "code": "conflict", "error": "draft is not PENDING_REVIEW"}))
        return 7

    print(json.dumps({"ok": True, "row": row}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
