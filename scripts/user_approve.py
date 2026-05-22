"""Admin-only: approve a pending registration and assign a role.

Stdin:  {"user_id": N, "role": "user"|"admin", "_acting_user": "<admin username>"}
Stdout: {"ok": true,  "user": {…}}                                       (exit 0)
        {"ok": false, "error": "..."}                                     (exit 3)
        {"ok": false, "error": "user not found"}                          (exit 4)
        {"ok": false, "code":"conflict", "error":"user already active"}  (exit 5)
Manual smoke:
  echo '{"user_id":1,"role":"user","_acting_user":"peter"}' | python3 scripts/user_approve.py
"""
from __future__ import annotations
import json
import sys

import user_db


def main() -> int:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig").strip() or "{}"
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": "invalid JSON on stdin", "detail": str(e)}))
        return 2

    user_id = payload.get("user_id")
    if not isinstance(user_id, int):
        print(json.dumps({"ok": False, "error": "user_id (int) required"}))
        return 3

    try:
        role = user_db.validate_role(payload.get("role", ""))
    except user_db.ValidationError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 3

    acting = payload.get("_acting_user") or "system"

    conn = None
    try:
        conn = user_db.connect()
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users "
                    "   SET status='active', role=%s, "
                    "       approved_at=now(), approved_by=%s, "
                    "       updated_at=now(), updated_by=%s "
                    " WHERE id=%s AND status='pending'",
                    (role, acting, acting, user_id),
                )
                if cur.rowcount == 0:
                    cur.execute("SELECT status FROM users WHERE id=%s", (user_id,))
                    existing = cur.fetchone()
                    if existing is None:
                        print(json.dumps({"ok": False, "error": "user not found"}))
                        return 4
                    print(json.dumps({
                        "ok": False, "code": "conflict",
                        "error": "user already active",
                    }))
                    return 5
                cur.execute("SELECT * FROM users WHERE id=%s", (user_id,))
                row = user_db.row_to_public(cur, cur.fetchone())
        print(json.dumps({"ok": True, "user": row}))
        return 0
    except Exception as e:
        # Push the raw error to stderr (Grafana captures it via spawnPython
        # on non-zero exit) but don't leak DB internals to the response.
        print(str(e), file=sys.stderr)
        print(json.dumps({"ok": False, "error": "DB error"}))
        return 5
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
