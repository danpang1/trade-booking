"""Create one api_tokens row for the acting user. Returns plaintext ONCE.

Stdin (server mode only — no CLI mode):
  {"name": "Alice's MacBook", "expires_in_days": 90, "_acting_user": "alice"}

Stdout success: {"ok": true, "token": "tkmo_...", "row": {…public fields…}}
Stdout failure: {"ok": false, "error": "..."}
"""
from __future__ import annotations
import json
import sys

import token_db


def _insert(payload: dict) -> tuple[str, dict]:
    name = token_db.validate_name(payload.get("name"))
    days = token_db.validate_expires_in_days(payload.get("expires_in_days"))
    acting = payload.get("_acting_user")
    if not isinstance(acting, str) or not acting:
        raise token_db.ValidationError("missing _acting_user (server bug)")

    plaintext = token_db.generate_token()
    t_hash = token_db.hash_token(plaintext)
    t_prefix = token_db.token_prefix(plaintext)

    conn = token_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM users WHERE LOWER(username) = LOWER(%s)",
                    (acting,),
                )
                row = cur.fetchone()
                if row is None:
                    raise token_db.ValidationError(f"unknown user: {acting}")
                user_id = row[0]

                cur.execute(
                    "INSERT INTO api_tokens "
                    "(user_id, token_hash, token_prefix, name, expires_at) "
                    f"VALUES (%s, %s, %s, %s, now() + interval '{days} days') "
                    "RETURNING *",
                    (user_id, t_hash, t_prefix, name),
                )
                public = token_db.row_to_public(cur, cur.fetchone())
    finally:
        conn.close()
    return plaintext, public


def main() -> int:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig").strip() or "{}"
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": "invalid JSON on stdin", "detail": str(e)}))
        return 2

    try:
        plaintext, row = _insert(payload)
    except token_db.ValidationError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 3
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5

    print(json.dumps({"ok": True, "token": plaintext, "row": row}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
