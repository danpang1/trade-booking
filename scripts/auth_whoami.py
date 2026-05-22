"""Resolve a session id to the user payload, AND extend the session.

Stdin:  {"sid": "<uuid>"}
Stdout success: {"ok": true, "user": {id, username, email, role}}
Stdout failure: {"ok": false}     (no error string — caller maps to 401)
"""
from __future__ import annotations
import json
import sys

import user_db


SESSION_HOURS = 8


def main() -> int:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig").strip() or "{}"
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = {}
    sid = payload.get("sid")
    if not sid:
        print(json.dumps({"ok": False}))
        return 6

    conn = None
    try:
        conn = user_db.connect()
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE sessions "
                    f"   SET expires_at = now() + interval '{SESSION_HOURS} hours', "
                    "       last_seen_at = now() "
                    " WHERE session_id = %s AND expires_at > now() "
                    " RETURNING user_id",
                    (sid,),
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
        print(json.dumps({"ok": True, "user": {
            "id": u[0], "username": u[1], "email": u[2], "role": u[3]
        }}))
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
