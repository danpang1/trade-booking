"""Resolve a Bearer plaintext token to its user, AND update last_used_at.

Stdin:  {"token": "tkmo_..."}
Stdout success: {"ok": true, "user": {id, username, email, role}}
Stdout failure: {"ok": false}     (caller maps to 401)

A token is valid iff:
  - hash matches a row in api_tokens
  - revoked_at IS NULL
  - expires_at > NOW()
The corresponding user must exist (the FK + ON DELETE CASCADE guarantees
this at write time, but we still SELECT to load the user payload).
"""
from __future__ import annotations
import json
import sys

import token_db


def main() -> int:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig").strip() or "{}"
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = {}

    plaintext = payload.get("token")
    if not isinstance(plaintext, str) or not plaintext:
        print(json.dumps({"ok": False}))
        return 6

    t_hash = token_db.hash_token(plaintext)

    conn = None
    try:
        conn = token_db.connect()
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE api_tokens "
                    "   SET last_used_at = now() "
                    " WHERE token_hash = %s "
                    "   AND revoked_at IS NULL "
                    "   AND expires_at > now() "
                    "RETURNING user_id",
                    (t_hash,),
                )
                r = cur.fetchone()
                if r is None:
                    print(json.dumps({"ok": False}))
                    return 6

                cur.execute(
                    "SELECT id, username, email, role FROM users WHERE id = %s",
                    (r[0],),
                )
                u = cur.fetchone()
                if u is None:
                    print(json.dumps({"ok": False}))
                    return 6
        print(json.dumps({
            "ok": True,
            "user": {"id": u[0], "username": u[1], "email": u[2], "role": u[3]},
        }))
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
