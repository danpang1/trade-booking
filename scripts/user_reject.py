"""Admin-only: hard-delete a pending registration.

Active users are removed via the existing DELETE endpoint (user_delete.py);
this script refuses to touch them.

Stdin:  {"user_id": N}
Stdout: {"ok": true}                                                       (exit 0)
        {"ok": false, "error": "user not found"}                           (exit 4)
        {"ok": false, "code":"conflict",
         "error":"can only reject pending users"}                          (exit 5)
Manual smoke:
  echo '{"user_id":1}' | python3 scripts/user_reject.py
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
        print(str(e), file=sys.stderr)
        print(json.dumps({"ok": False, "error": "invalid JSON on stdin"}))
        return 2

    user_id = payload.get("user_id")
    if not isinstance(user_id, int):
        print(json.dumps({"ok": False, "error": "user_id (int) required"}))
        return 3

    conn = None
    try:
        conn = user_db.connect()
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM users WHERE id=%s AND status='pending'",
                    (user_id,),
                )
                if cur.rowcount == 0:
                    cur.execute("SELECT status FROM users WHERE id=%s", (user_id,))
                    existing = cur.fetchone()
                    if existing is None:
                        print(json.dumps({"ok": False, "error": "user not found"}))
                        return 4
                    print(json.dumps({
                        "ok": False, "code": "conflict",
                        "error": "can only reject pending users",
                    }))
                    return 5
        print(json.dumps({"ok": True}))
        return 0
    except Exception as e:
        print(str(e), file=sys.stderr)
        print(json.dumps({"ok": False, "error": "DB error"}))
        return 5
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
