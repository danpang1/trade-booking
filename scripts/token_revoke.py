"""Revoke a single api_tokens row (soft-delete: sets revoked_at).

Stdin: {"id": 42, "_acting_user": "alice"}
Stdout success: {"ok": true}
Stdout failure: {"ok": false, "error": "...", "code": "not_found"}  (404)

Only the token owner can revoke. Returns 404 (not 403) for tokens owned
by others — avoids leaking existence to unauthorized callers.
"""
from __future__ import annotations
import json
import sys

import token_db


def _revoke(token_id: int, acting: str) -> bool:
    conn = token_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE api_tokens t "
                    "   SET revoked_at = now() "
                    "  FROM users u "
                    " WHERE t.id = %s "
                    "   AND t.user_id = u.id "
                    "   AND LOWER(u.username) = LOWER(%s) "
                    "   AND t.revoked_at IS NULL "
                    "RETURNING t.id",
                    (token_id, acting),
                )
                return cur.fetchone() is not None
    finally:
        conn.close()


def main() -> int:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig").strip() or "{}"
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        err_msg = "invalid JSON on stdin"
        print(json.dumps({
            "ok": False,
            "error": err_msg,
            "detail": str(e)
        }))
        return 2

    token_id = payload.get("id")
    acting = payload.get("_acting_user")
    if not isinstance(token_id, int) or token_id <= 0:
        print(json.dumps({
            "ok": False,
            "error": "id must be positive integer"
        }))
        return 3
    if not isinstance(acting, str) or not acting:
        print(json.dumps({
            "ok": False,
            "error": "missing _acting_user (server bug)"
        }))
        return 3

    try:
        ok = _revoke(token_id, acting)
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": "DB error",
            "detail": str(e)
        }))
        return 5

    if not ok:
        print(json.dumps({
            "ok": False,
            "code": "not_found",
            "error": "token not found"
        }))
        return 4

    print(json.dumps({"ok": True}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
