"""Self-registration: insert a pending user awaiting admin approval.

Public endpoint — no session required. Validates inputs via user_db,
hashes password with bcrypt cost 12, INSERTs a row with status='pending'
and role=NULL. Admin must then call user_approve.py.

Stdin:  {"username": "...", "email": "...", "password": "..."}
Stdout: {"ok": true,  "user": {id,username,email,role,status,...}}     (exit 0)
        {"ok": false, "error": "...", "detail": "..."}                  (exit 3)
        {"ok": false, "code":"conflict", "error":"username or email already taken"}  (exit 5)
Manual smoke:
  echo '{"username":"x","email":"x@y.z","password":"Secret-123"}' | python3 scripts/auth_register.py
"""
from __future__ import annotations
import json
import sys

import psycopg2  # for UniqueViolation
import user_db


def main() -> int:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig").strip() or "{}"
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": "invalid JSON on stdin", "detail": str(e)}))
        return 2

    try:
        username = user_db.validate_username(payload.get("username", ""))
        email    = user_db.validate_email(payload.get("email", ""))
        password = user_db.validate_password(payload.get("password", ""))
    except user_db.ValidationError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 3

    pw_hash = user_db.hash_password(password)

    conn = None
    try:
        conn = user_db.connect()
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO users "
                    "  (username, email, password_hash, status, role, created_by, updated_by) "
                    "VALUES (%s, %s, %s, 'pending', NULL, NULL, NULL) "
                    "RETURNING *",
                    (username, email, pw_hash),
                )
                row = user_db.row_to_public(cur, cur.fetchone())
        print(json.dumps({"ok": True, "user": row}))
        return 0
    except psycopg2.errors.UniqueViolation as e:
        print(json.dumps({
            "ok": False, "code": "conflict",
            "error": "username or email already taken",
            "detail": str(e).strip(),
        }))
        return 5
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
