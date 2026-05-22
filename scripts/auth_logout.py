"""Delete a session row. Idempotent.

Stdin:  {"sid": "<uuid>"}
Stdout: {"ok": true}
"""
from __future__ import annotations
import json
import sys

import user_db


def main() -> int:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig").strip() or "{}"
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = {}
    sid = payload.get("sid")
    if sid:
        conn = None
        try:
            conn = user_db.connect()
            with conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM sessions WHERE session_id = %s", (sid,))
        except Exception as e:
            print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
            return 5
        finally:
            if conn is not None:
                conn.close()
    print(json.dumps({"ok": True}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
