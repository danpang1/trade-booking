"""List all users (PUBLIC_COLUMNS only — no password_hash).

Stdin:  {} (or empty)
Stdout: {"ok": true, "rows": [{…}]}
"""
from __future__ import annotations
import json
import sys

import user_db


def main() -> int:
    conn = user_db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, email, role, status, approved_at, approved_by, "
                "       created_at, updated_at "
                "FROM users ORDER BY id"
            )
            rows = [user_db.row_to_public(cur, r) for r in cur.fetchall()]
        print(json.dumps({"ok": True, "rows": rows}))
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
