"""Update a user. Any subset of {email, role, password} may be supplied.

Stdin:  {"id": N, "email"?: "...", "role"?: "...", "password"?: "...", "_acting_user": "username"}
Stdout: {"ok": true, "user": {…}}  or  {"ok": false, "error": "..."}
"""
from __future__ import annotations
import json
import sys

import psycopg2
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

    sets: list[str] = []
    vals: list = []
    try:
        if "email" in payload:
            sets.append("email = %s")
            vals.append(user_db.validate_email(payload["email"]))
        if "role" in payload:
            sets.append("role = %s")
            vals.append(user_db.validate_role(payload["role"]))
        if "password" in payload:
            sets.append("password_hash = %s")
            vals.append(user_db.hash_password(user_db.validate_password(payload["password"])))
    except user_db.ValidationError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 3

    if not sets:
        print(json.dumps({"ok": False, "error": "nothing to update"}))
        return 3
    sets.append("updated_at = NOW()")
    sets.append("updated_by = %s")
    vals.append(payload.get("_acting_user"))

    conn = user_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                # Last-admin guard
                if payload.get("role") == "user":
                    cur.execute("SELECT role FROM users WHERE id=%s", (user_id,))
                    r = cur.fetchone()
                    if r is None:
                        print(json.dumps({"ok": False, "code": "not_found", "error": "user not found"}))
                        return 4
                    if r[0] == "admin" and user_db.count_admins(cur) <= 1:
                        print(json.dumps({"ok": False, "error": "cannot demote the last admin"}))
                        return 3

                cur.execute(
                    f"UPDATE users SET {', '.join(sets)} WHERE id = %s RETURNING *",
                    (*vals, user_id),
                )
                row = cur.fetchone()
                if row is None:
                    print(json.dumps({"ok": False, "code": "not_found", "error": "user not found"}))
                    return 4
                user = user_db.row_to_public(cur, row)
        print(json.dumps({"ok": True, "user": user}))
        return 0
    except psycopg2.errors.UniqueViolation as e:
        print(json.dumps({"ok": False, "code": "conflict", "error": "email already in use", "detail": str(e).strip()}))
        return 5
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
