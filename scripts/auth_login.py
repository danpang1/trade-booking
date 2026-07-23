"""Verify password and create a session row.

Stdin:  {"username": "...", "password": "..."}
Stdout success: {"ok": true, "sid": "<uuid>", "user": {…}, "expires_at": "..."}
Stdout failure: {"ok": false, "error": "invalid credentials"}    (401 via exit 6)
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
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": "invalid JSON on stdin", "detail": str(e)}))
        return 2

    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    if not username or not password:
        print(json.dumps({"ok": False, "error": "invalid credentials"}))
        return 6

    conn = None
    try:
        conn = user_db.connect()
        with conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM sessions WHERE expires_at < now()")
                cur.execute(
                    "SELECT id, username, email, role, password_hash, status, access_tms "
                    "FROM users WHERE LOWER(username) = LOWER(%s)",
                    (username,),
                )
                row = cur.fetchone()
                if row is None or not user_db.verify_password(password, row[4]):
                    print(json.dumps({"ok": False, "error": "invalid credentials"}))
                    return 6
                user_id, u_name, u_email, u_role, _, u_status, u_access_tms = row

                if u_status != "active":
                    print(json.dumps({"ok": False, "error": "Account pending admin approval"}))
                    return 6

                if not u_access_tms:
                    print(json.dumps({"ok": False, "error": "Account has no TMS access — ask an admin"}))
                    return 6

                cur.execute(
                    "INSERT INTO sessions (user_id, expires_at) "
                    f"VALUES (%s, now() + interval '{SESSION_HOURS} hours') "
                    "RETURNING session_id, expires_at",
                    (user_id,),
                )
                sid, exp = cur.fetchone()
        print(json.dumps({
            "ok": True,
            "sid": str(sid),
            "user": {"id": user_id, "username": u_name, "email": u_email, "role": u_role},
            "expires_at": exp.isoformat(),
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
