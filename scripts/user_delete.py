"""Delete a user by id. Cascades to sessions (force-logout).

Stdin:  {"id": N, "_acting_user_id": N}
Stdout: {"ok": true}  or  {"ok": false, "error": "..."}
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

    try:
        user_id = int(payload.get("id"))
    except (TypeError, ValueError):
        print(json.dumps({"ok": False, "error": "id required (int)"}))
        return 3
    acting = payload.get("_acting_user_id")
    if acting is not None and int(acting) == user_id:
        print(json.dumps({"ok": False, "error": "cannot delete yourself"}))
        return 3

    conn = user_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT role FROM users WHERE id=%s", (user_id,))
                r = cur.fetchone()
                if r is None:
                    print(json.dumps({"ok": False, "code": "not_found", "error": "user not found"}))
                    return 4
                if r[0] == "admin" and user_db.count_admins(cur) <= 1:
                    print(json.dumps({"ok": False, "error": "cannot delete the last admin"}))
                    return 3
                cur.execute("DELETE FROM users WHERE id=%s", (user_id,))
        print(json.dumps({"ok": True}))
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
