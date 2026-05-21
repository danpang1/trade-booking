"""Create one user row.

Two modes — detected by isatty():
  • CLI:    python scripts/user_create.py --username X --email Y --role admin
            (password prompted via getpass; not echoed)
  • Stdin:  echo '{"username":"X","email":"Y","role":"user","password":"…"}' | \\
            python scripts/user_create.py

Stdout (both modes):
  Success: {"ok": true, "user": {…}}
  Failure: {"ok": false, "error": "...", "detail": "..."}
"""
from __future__ import annotations
import argparse
import getpass
import json
import sys

import psycopg2  # for IntegrityError class
import user_db


def _insert(payload: dict, acting_user: str | None) -> dict:
    username = user_db.validate_username(payload.get("username", ""))
    email = user_db.validate_email(payload.get("email", ""))
    role = user_db.validate_role(payload.get("role", ""))
    password = user_db.validate_password(payload.get("password", ""))
    pw_hash = user_db.hash_password(password)

    conn = user_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO users (username, email, role, password_hash, created_by, updated_by) "
                    "VALUES (%s, %s, %s, %s, %s, %s) RETURNING *",
                    (username, email, role, pw_hash, acting_user, acting_user),
                )
                row = user_db.row_to_public(cur, cur.fetchone())
        return row
    finally:
        conn.close()


def main() -> int:
    if sys.stdin.isatty():
        # CLI mode
        p = argparse.ArgumentParser()
        p.add_argument("--username", required=True)
        p.add_argument("--email", required=True)
        p.add_argument("--role", required=True, choices=user_db.ROLES)
        args = p.parse_args()
        pw1 = getpass.getpass("Password: ")
        pw2 = getpass.getpass("Confirm:  ")
        if pw1 != pw2:
            print("passwords do not match", file=sys.stderr)
            return 1
        payload = {"username": args.username, "email": args.email, "role": args.role, "password": pw1}
        acting = None  # bootstrap
    else:
        # Stdin mode (server)
        try:
            raw = sys.stdin.buffer.read().decode("utf-8-sig").strip() or "{}"
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            print(json.dumps({"ok": False, "error": "invalid JSON on stdin", "detail": str(e)}))
            return 2
        acting = payload.pop("_acting_user", None)

    try:
        row = _insert(payload, acting)
    except user_db.ValidationError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 3
    except psycopg2.errors.UniqueViolation as e:
        print(json.dumps({"ok": False, "code": "conflict", "error": "username or email already exists", "detail": str(e).strip()}))
        return 5
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5

    print(json.dumps({"ok": True, "user": row}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
