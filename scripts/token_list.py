"""List api_tokens belonging to the acting user.

Stdin: {"_acting_user": "alice"}
Stdout: {"ok": true, "tokens": [{…public…}, ...]}

Public fields only — token_hash never leaves the DB.
"""
from __future__ import annotations
import json
import sys

import token_db


def _list(acting: str) -> list[dict]:
    conn = token_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT t.* FROM api_tokens t "
                    "JOIN users u ON u.id = t.user_id "
                    "WHERE LOWER(u.username) = LOWER(%s) "
                    "ORDER BY t.created_at DESC",
                    (acting,),
                )
                rows = cur.fetchall()
                return [token_db.row_to_public(cur, r) for r in rows]
    finally:
        conn.close()


def main() -> int:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig").strip() or "{}"
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        d = {"ok": False, "error": "invalid JSON on stdin", "detail": str(e)}
        print(json.dumps(d))
        return 2

    acting = payload.get("_acting_user")
    if not isinstance(acting, str) or not acting:
        d = {"ok": False, "error": "missing _acting_user (server bug)"}
        print(json.dumps(d))
        return 3

    try:
        tokens = _list(acting)
    except Exception as e:
        d = {"ok": False, "error": "DB error", "detail": str(e)}
        print(json.dumps(d))
        return 5

    print(json.dumps({"ok": True, "tokens": tokens}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
