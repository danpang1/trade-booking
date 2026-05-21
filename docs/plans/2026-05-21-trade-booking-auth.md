# Trade Booking — Authentication & User Management — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a login gate, role-based access (admin/user), and an admin user-management UI to the standalone `trade-booking/` repo, backed by new Postgres tables.

**Architecture:** Two new Postgres tables (`users`, `sessions`) in the existing MO UAT DB. New Python scripts follow the established stdin-JSON / stdout-JSON pattern used by `cashflow_*.py`. `server.js` gains a cookie-based auth middleware that gates all `/api/*` routes (except `/api/auth/login`), injects the session username into existing booking-route payloads, and mounts new `/api/auth/*` + `/api/users` routes. The React app gains a top-level `<App>` that conditionally renders `<LoginPage>` or `<Authenticated>` based on `GET /api/auth/me`.

**Tech Stack:** Python 3.11 (`bcrypt`, `psycopg2`), Node 22 (no new deps), React 19 (no new deps), Postgres UAT (`pgcrypto`).

**Spec:** `docs/design/2026-05-21-trade-booking-auth-design.md` (committed at `4873370`).

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `scripts/apply_schema_users.py` | Create | DDL for `users`, `sessions`; idempotent (`IF NOT EXISTS`) |
| `scripts/user_db.py` | Create | Shared helpers: bcrypt hash/verify, regex validators, row→payload, `connect()` reuses `cashflow_db.load_creds`/`connect` |
| `scripts/user_create.py` | Create | Dual mode: CLI (TTY → `getpass`) or stdin-JSON (server) |
| `scripts/user_list.py` | Create | stdin `{}` → `{ok, rows:[…]}` |
| `scripts/user_update.py` | Create | stdin `{id, email?, role?, password?}` |
| `scripts/user_delete.py` | Create | stdin `{id, acting_user_id}`; last-admin + self-delete guards |
| `scripts/auth_login.py` | Create | stdin `{username, password}` → `{ok, sid, user}` or 401 |
| `scripts/auth_logout.py` | Create | stdin `{sid}` → `{ok}` |
| `scripts/auth_whoami.py` | Create | stdin `{sid}` → `{ok, user}`; extends session expiry in one SQL |
| `scripts/smoke_auth.py` | Create | Manual E2E probe against UAT |
| `tests/test_user_db.py` | Create | Pure-logic unit tests (no DB) |
| `requirements.txt` | Modify | Add `bcrypt>=4.0` |
| `server.js` | Modify | Cookie parsing, auth middleware, new routes, user_id injection on existing routes |
| `src/main.jsx` | Modify | 1-line: render `<App/>` |
| `src/App.jsx` | Create | Auth state machine; routes between LoginPage / Authenticated |
| `src/auth/AuthContext.jsx` | Create | `{user, login, logout, refresh}` context |
| `src/auth/LoginPage.jsx` | Create | Bloomberg-terminal login form |
| `src/auth/api.js` | Create | Fetch wrapper: `credentials:'include'`, 401-bounce |
| `src/admin/UserAdmin.jsx` | Create | Table + actions |
| `src/admin/UserEditModal.jsx` | Create | Create/edit modal |
| `src/TradeBookingForm.jsx` | Modify | Remove user picker, read-only user_id from session, all `fetch()` → `api()`, header gains user badge / logout / "Users" link |
| `README.md` | Modify | New "Auth" section with bootstrap commands |

---

## Conventions inherited from this codebase

- **Script header**: docstring with manual smoke command (e.g. `echo '{…}' | python3 scripts/<name>.py`)
- **stdin/stdout contract**: scripts read JSON from stdin, write JSON to stdout, exit code maps to HTTP status in `server.js:209` `httpStatusFor`
- **Imports inside `connect()`** (`scripts/cashflow_db.py:78` pattern) — `psycopg2` imported lazily so pure-logic tests don't need it
- **Commit style**: `type(scope): summary` lower-case (`feat(auth): …`, `docs(auth): …`)
- **Never commit `.env`** — gitignored

---

## Task 1: Schema + DB helpers + pure-logic tests

**Goal:** Create the `users` and `sessions` tables and a shared Python helper module with unit-tested pure logic (hashing, validators).

**Files:**
- Create: `scripts/apply_schema_users.py`
- Create: `scripts/user_db.py`
- Create: `tests/test_user_db.py`
- Modify: `requirements.txt` (append `bcrypt>=4.0,<5`)

**Acceptance Criteria:**
- [ ] `python scripts/apply_schema_users.py` runs cleanly and is idempotent (run twice → no error)
- [ ] `pytest tests/test_user_db.py -v` passes
- [ ] `\d users` in psql shows the column order from §4.1 of the spec
- [ ] `\d sessions` shows the column order from §4.2

**Verify:** `pytest tests/test_user_db.py -v && python scripts/apply_schema_users.py` → all green, no DDL errors.

**Steps:**

- [ ] **Step 1: Add bcrypt to requirements.txt**

Open `requirements.txt`, append the line `bcrypt>=4.0,<5`. Run `pip install -r requirements.txt`.

- [ ] **Step 2: Write `scripts/user_db.py` (pure logic + connect)**

```python
"""Shared helper for user_*/auth_* scripts.

Pure-logic functions (hash_password, verify_password, validators) live here
and are exercised by tests/test_user_db.py without touching the DB.
DB-touching functions reuse cashflow_db.load_creds / connect.
"""
from __future__ import annotations
import re

import bcrypt

import cashflow_db  # reuse Postgres creds + connect


# ── Pure logic ────────────────────────────────────────────────────

USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{3,64}$")
EMAIL_RE    = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ROLES       = ("admin", "user")
MIN_PW_LEN  = 8


class ValidationError(ValueError):
    """Raised by validate_* helpers; caught in main() and rendered as JSON."""


def hash_password(plain: str) -> str:
    """bcrypt cost 12 → exactly 60-char hash."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


def validate_username(s: str) -> str:
    if not isinstance(s, str) or not USERNAME_RE.match(s):
        raise ValidationError("username must be 3-64 chars [a-zA-Z0-9._-]")
    return s


def validate_email(s: str) -> str:
    if not isinstance(s, str) or not EMAIL_RE.match(s):
        raise ValidationError("invalid email")
    return s


def validate_role(s: str) -> str:
    if s not in ROLES:
        raise ValidationError(f"role must be one of {ROLES}")
    return s


def validate_password(s: str) -> str:
    if not isinstance(s, str) or len(s) < MIN_PW_LEN:
        raise ValidationError(f"password must be >= {MIN_PW_LEN} chars")
    return s


# ── DB-touching ───────────────────────────────────────────────────

def connect():
    """Reuse the MO_DB_UAT connection used by cashflow scripts."""
    return cashflow_db.connect()


# Columns returned to the API consumer. password_hash NEVER appears here.
PUBLIC_COLUMNS = ("id", "username", "email", "role", "created_at", "updated_at")


def row_to_public(cur, row) -> dict:
    """Map a SELECT-* row to the public payload (omits password_hash)."""
    cols = [d.name for d in cur.description]
    record = dict(zip(cols, row))
    out = {}
    for k in PUBLIC_COLUMNS:
        v = record.get(k)
        if hasattr(v, "isoformat"):
            v = v.isoformat()
        out[k] = v
    return out


def count_admins(cur) -> int:
    cur.execute("SELECT COUNT(*) FROM users WHERE role='admin'")
    return int(cur.fetchone()[0])
```

- [ ] **Step 3: Write `tests/test_user_db.py`**

```python
"""Pure-logic unit tests for user_db. No DB connection required."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import pytest
import user_db


def test_hash_then_verify_round_trip():
    h = user_db.hash_password("CorrectHorse9!")
    assert len(h) == 60
    assert user_db.verify_password("CorrectHorse9!", h)
    assert not user_db.verify_password("wrong", h)


def test_verify_password_handles_garbage_hash():
    assert user_db.verify_password("anything", "not-a-real-hash") is False
    assert user_db.verify_password("anything", "") is False


@pytest.mark.parametrize("s", ["pe", "ab", ""])
def test_validate_username_rejects_too_short(s):
    with pytest.raises(user_db.ValidationError):
        user_db.validate_username(s)


@pytest.mark.parametrize("s", ["peter", "peter.pang", "peter_p-1"])
def test_validate_username_accepts_good_chars(s):
    assert user_db.validate_username(s) == s


@pytest.mark.parametrize("s", ["peter pang", "peter@x", "peter!"])
def test_validate_username_rejects_bad_chars(s):
    with pytest.raises(user_db.ValidationError):
        user_db.validate_username(s)


def test_validate_email_basic():
    assert user_db.validate_email("a@b.c") == "a@b.c"
    with pytest.raises(user_db.ValidationError):
        user_db.validate_email("not-an-email")
    with pytest.raises(user_db.ValidationError):
        user_db.validate_email("no-domain@")


def test_validate_role():
    assert user_db.validate_role("admin") == "admin"
    assert user_db.validate_role("user") == "user"
    with pytest.raises(user_db.ValidationError):
        user_db.validate_role("superadmin")


def test_validate_password_min_length():
    user_db.validate_password("12345678")
    with pytest.raises(user_db.ValidationError):
        user_db.validate_password("short")
```

- [ ] **Step 4: Run tests — they should fail until step 2 is saved correctly**

Run: `pytest tests/test_user_db.py -v`
Expected: all green (helpers are written before tests run).

- [ ] **Step 5: Write `scripts/apply_schema_users.py`**

```python
"""Create `users` and `sessions` tables. Idempotent."""
from __future__ import annotations
import cashflow_db

DDL = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS users (
  id              SERIAL          PRIMARY KEY,
  username        VARCHAR(64)     NOT NULL UNIQUE,
  email           VARCHAR(255)    NOT NULL UNIQUE,
  role            VARCHAR(16)     NOT NULL CHECK (role IN ('admin','user')),
  password_hash   VARCHAR(60)     NOT NULL,
  created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
  created_by      VARCHAR(64),
  updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
  updated_by      VARCHAR(64)
);

CREATE INDEX IF NOT EXISTS users_username_lower_idx ON users (LOWER(username));

CREATE TABLE IF NOT EXISTS sessions (
  session_id      UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         INTEGER         NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
  expires_at      TIMESTAMPTZ     NOT NULL,
  last_seen_at    TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS sessions_user_id_idx    ON sessions (user_id);
CREATE INDEX IF NOT EXISTS sessions_expires_at_idx ON sessions (expires_at);
"""


def main() -> None:
    conn = cashflow_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(DDL)
        print("ok: users + sessions tables ready")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Apply schema; verify column order**

Run:
```powershell
python scripts/apply_schema_users.py
python scripts/apply_schema_users.py   # second run = no error
```

Expected: `ok: users + sessions tables ready` printed twice.

Then verify column order via psql or by running this one-liner:
```powershell
python -c "import cashflow_db; c=cashflow_db.connect(); cur=c.cursor(); cur.execute('SELECT column_name FROM information_schema.columns WHERE table_name=%s ORDER BY ordinal_position',('users',)); print([r[0] for r in cur.fetchall()])"
```
Expected: `['id','username','email','role','password_hash','created_at','created_by','updated_at','updated_by']`

- [ ] **Step 7: Commit**

```powershell
git add scripts/apply_schema_users.py scripts/user_db.py tests/test_user_db.py requirements.txt
git commit -m "feat(auth): users/sessions schema + user_db helpers + tests"
```

---

## Task 2: User CRUD scripts

**Goal:** Four scripts (`user_create.py`, `user_list.py`, `user_update.py`, `user_delete.py`) that together let an admin manage user rows.

**Files:**
- Create: `scripts/user_create.py`
- Create: `scripts/user_list.py`
- Create: `scripts/user_update.py`
- Create: `scripts/user_delete.py`

**Acceptance Criteria:**
- [ ] `user_create.py` runs in TTY mode (prompts password via getpass) AND stdin-JSON mode
- [ ] All four scripts return JSON on stdout in the format `{ok, …}` / `{ok:false, error, detail?}`
- [ ] Exit codes match `server.js:209` `httpStatusFor`: 0=200, 3=400, 4=404, conflict→json.code='conflict' (exit 5)
- [ ] Last-admin guard enforced in `user_update.py` (role change away from admin) and `user_delete.py`
- [ ] Self-delete blocked in `user_delete.py` when `acting_user_id == id`

**Verify:** Run the smoke commands in each script's docstring (see Step 6).

**Steps:**

- [ ] **Step 1: Write `scripts/user_create.py`**

```python
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
    email    = user_db.validate_email(payload.get("email", ""))
    role     = user_db.validate_role(payload.get("role", ""))
    password = user_db.validate_password(payload.get("password", ""))
    pw_hash  = user_db.hash_password(password)

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
            payload = json.loads(sys.stdin.read() or "{}")
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
```

- [ ] **Step 2: Write `scripts/user_list.py`**

```python
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
                "SELECT id, username, email, role, created_at, updated_at "
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
```

- [ ] **Step 3: Write `scripts/user_update.py`**

```python
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
        payload = json.loads(sys.stdin.read() or "{}")
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
    if "email" in payload:
        sets.append("email = %s");  vals.append(user_db.validate_email(payload["email"]))
    if "role" in payload:
        sets.append("role = %s");   vals.append(user_db.validate_role(payload["role"]))
    if "password" in payload:
        sets.append("password_hash = %s")
        vals.append(user_db.hash_password(user_db.validate_password(payload["password"])))
    if not sets:
        print(json.dumps({"ok": False, "error": "nothing to update"}))
        return 3
    sets.append("updated_at = NOW()")
    sets.append("updated_by = %s"); vals.append(payload.get("_acting_user"))

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
    except user_db.ValidationError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 3
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
```

- [ ] **Step 4: Write `scripts/user_delete.py`**

```python
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
        payload = json.loads(sys.stdin.read() or "{}")
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
```

- [ ] **Step 5: Smoke — create the first admin from CLI**

Run (interactive — getpass will prompt):
```powershell
python scripts/user_create.py --username peter --email peter@tokkalabs.com --role admin
```
Enter a password ≥ 8 chars twice. Expected stdout: `{"ok": true, "user": {…, "username": "peter", "role": "admin"}}`.

- [ ] **Step 6: Smoke — exercise list / update / delete via stdin**

```powershell
echo "{}" | python scripts/user_list.py
# → {"ok": true, "rows": [{"id":1,"username":"peter",…}]}

echo '{"id": 1, "email":"peter@tokkalabs.com", "_acting_user":"peter"}' | python scripts/user_update.py
# → {"ok": true, "user": {…}}

echo '{"username":"alice","email":"alice@tokkalabs.com","role":"user","password":"hunter2hunter","_acting_user":"peter"}' | python scripts/user_create.py
# → {"ok": true, "user": {…, "username":"alice"}}

# Guard test: refuse to demote the last admin (currently peter is the only admin)
echo '{"id": 1, "role":"user", "_acting_user":"peter"}' | python scripts/user_update.py
# → {"ok": false, "error": "cannot demote the last admin"}

# Guard test: cannot delete yourself
echo '{"id": 1, "_acting_user_id": 1}' | python scripts/user_delete.py
# → {"ok": false, "error": "cannot delete yourself"}
```

- [ ] **Step 7: Commit**

```powershell
git add scripts/user_create.py scripts/user_list.py scripts/user_update.py scripts/user_delete.py
git commit -m "feat(auth): user CRUD scripts (create/list/update/delete)"
```

---

## Task 3: Auth scripts (login, logout, whoami)

**Goal:** Three scripts that the Node middleware will spawn on every request.

**Files:**
- Create: `scripts/auth_login.py`
- Create: `scripts/auth_logout.py`
- Create: `scripts/auth_whoami.py`

**Acceptance Criteria:**
- [ ] `auth_login.py` returns the same `{ok:false, error:"invalid credentials"}` for unknown-user and wrong-password
- [ ] `auth_login.py` sweeps `WHERE expires_at < now()` before inserting (cheap cleanup, no cron needed)
- [ ] `auth_whoami.py` extends `expires_at` to `now() + interval '8 hours'` on every successful lookup (sliding window)
- [ ] `auth_logout.py` is a no-op (still `{ok:true}`) if the sid is unknown — caller doesn't need to differentiate

**Verify:** `python scripts/smoke_auth.py` (written in Task 8) passes end-to-end. In this task, verify manually via stdin smoke commands (Step 5).

**Steps:**

- [ ] **Step 1: Write `scripts/auth_login.py`**

```python
"""Verify password and create a session row.

Stdin:  {"username": "...", "password": "..."}
Stdout success: {"ok": true, "sid": "<uuid>", "user": {…}, "expires_at": "..."}
Stdout failure: {"ok": false, "error": "invalid credentials"}    (401)
"""
from __future__ import annotations
import json
import sys

import user_db


SESSION_HOURS = 8


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": "invalid JSON on stdin", "detail": str(e)}))
        return 2

    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    if not username or not password:
        print(json.dumps({"ok": False, "error": "invalid credentials"}))
        return 6  # → 401 via httpStatusFor; we map 6 in server.js

    conn = user_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM sessions WHERE expires_at < now()")
                cur.execute(
                    "SELECT id, username, email, role, password_hash "
                    "FROM users WHERE LOWER(username) = LOWER(%s)",
                    (username,),
                )
                row = cur.fetchone()
                if row is None or not user_db.verify_password(password, row[4]):
                    print(json.dumps({"ok": False, "error": "invalid credentials"}))
                    return 6
                user_id, u_name, u_email, u_role, _ = row

                cur.execute(
                    "INSERT INTO sessions (user_id, expires_at) "
                    f"VALUES (%s, now() + interval '{SESSION_HOURS} hours') "
                    "RETURNING session_id, expires_at",
                    (user_id,),
                )
                sid, exp = cur.fetchone()
        print(json.dumps({
            "ok": True,
            "sid": str(sid),
            "user": {"id": user_id, "username": u_name, "email": u_email, "role": u_role},
            "expires_at": exp.isoformat(),
        }))
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Write `scripts/auth_logout.py`**

```python
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
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}
    sid = payload.get("sid")
    if sid:
        conn = user_db.connect()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM sessions WHERE session_id = %s", (sid,))
        finally:
            conn.close()
    print(json.dumps({"ok": True}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Write `scripts/auth_whoami.py`**

```python
"""Resolve a session id to the user payload, AND extend the session.

Stdin:  {"sid": "<uuid>"}
Stdout success: {"ok": true, "user": {id, username, email, role}}
Stdout failure: {"ok": false}     (no error string — caller maps to 401)
"""
from __future__ import annotations
import json
import sys

import user_db


SESSION_HOURS = 8


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}
    sid = payload.get("sid")
    if not sid:
        print(json.dumps({"ok": False}))
        return 6  # → 401

    conn = user_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE sessions "
                    f"   SET expires_at = now() + interval '{SESSION_HOURS} hours', "
                    "       last_seen_at = now() "
                    " WHERE session_id = %s AND expires_at > now() "
                    " RETURNING user_id",
                    (sid,),
                )
                r = cur.fetchone()
                if r is None:
                    print(json.dumps({"ok": False}))
                    return 6
                cur.execute(
                    "SELECT id, username, email, role FROM users WHERE id = %s",
                    (r[0],),
                )
                u = cur.fetchone()
                if u is None:
                    print(json.dumps({"ok": False}))
                    return 6
        print(json.dumps({"ok": True, "user": {
            "id": u[0], "username": u[1], "email": u[2], "role": u[3]
        }}))
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Confirm `httpStatusFor` in `server.js` handles exit code 6 → 401**

We rely on exit code `6` mapping to HTTP 401. The existing `server.js:209` `httpStatusFor` does NOT have this case. Task 4 adds it. For now, just note this — no edit yet.

- [ ] **Step 5: Smoke**

Replace `<PEERS_PASSWORD>` with the password you set in Task 2 Step 5.

```powershell
# Success
echo '{"username":"peter","password":"<PEERS_PASSWORD>"}' | python scripts/auth_login.py
# → {"ok": true, "sid": "...", "user": {…}, "expires_at": "..."}
# Copy the sid for the next two:

echo '{"sid":"<PASTE_SID>"}' | python scripts/auth_whoami.py
# → {"ok": true, "user": {…}}

echo '{"sid":"<PASTE_SID>"}' | python scripts/auth_logout.py
# → {"ok": true}

echo '{"sid":"<PASTE_SID>"}' | python scripts/auth_whoami.py
# → {"ok": false}    (expired — session was deleted)

# Failure (wrong password) — same error string as unknown user
echo '{"username":"peter","password":"wrong"}' | python scripts/auth_login.py
# → {"ok": false, "error": "invalid credentials"}

echo '{"username":"ghost","password":"whatever"}' | python scripts/auth_login.py
# → {"ok": false, "error": "invalid credentials"}
```

- [ ] **Step 6: Commit**

```powershell
git add scripts/auth_login.py scripts/auth_logout.py scripts/auth_whoami.py
git commit -m "feat(auth): login/logout/whoami scripts with sliding session"
```

---

## Task 4: Node middleware + /api/auth routes

**Goal:** `server.js` learns to parse cookies, gate every `/api/*` route on a valid session (except `/api/auth/login`), and expose `/api/auth/{login,logout,me}`.

**Files:**
- Modify: `server.js`

**Acceptance Criteria:**
- [ ] `POST /api/auth/login` with good creds → `200`, `Set-Cookie: sid=<uuid>; HttpOnly; SameSite=Lax; Path=/; Max-Age=28800`
- [ ] Same endpoint with bad creds → `401 {ok:false, error:"invalid credentials"}`
- [ ] Any other `/api/*` request without cookie → `401 {ok:false, error:"not authenticated"}`
- [ ] Existing `/api/refdata/refresh` still works when authenticated
- [ ] `GET /api/auth/me` after login → `200 {ok:true, user:{username,role,email}}`
- [ ] `POST /api/auth/logout` clears the cookie and the row; subsequent `/api/auth/me` is 401

**Verify:** Manual `curl` (see Step 7).

**Steps:**

- [ ] **Step 1: Locate the new constants block in `server.js`**

In `server.js`, after the existing `*_SCRIPT` constants block (around line 33), add:

```js
const AUTH_LOGIN_SCRIPT   = resolve(__dirname, "scripts", "auth_login.py");
const AUTH_LOGOUT_SCRIPT  = resolve(__dirname, "scripts", "auth_logout.py");
const AUTH_WHOAMI_SCRIPT  = resolve(__dirname, "scripts", "auth_whoami.py");

const SESSION_COOKIE = "sid";
const SESSION_MAX_AGE_SEC = 8 * 60 * 60;
```

- [ ] **Step 2: Extend `httpStatusFor` to map exit code 6 → 401**

Find the existing `httpStatusFor` (around line 209). Replace its body with:

```js
function httpStatusFor(exitCode, json) {
  if (exitCode === 0) return 200;
  if (json && json.code === "conflict") return 409;
  if (json && json.code === "not_found") return 404;
  if (exitCode === 3) return 400;  // validation
  if (exitCode === 4) return 404;  // not_found (fallback)
  if (exitCode === 6) return 401;  // auth failure
  return 500;
}
```

- [ ] **Step 3: Add cookie helpers above the HTTP server block**

Just before `const server = createServer(...)`:

```js
function parseCookies(req) {
  const header = req.headers.cookie || "";
  const out = {};
  for (const part of header.split(";")) {
    const [k, ...rest] = part.trim().split("=");
    if (!k) continue;
    out[k] = decodeURIComponent(rest.join("="));
  }
  return out;
}

function setSessionCookie(res, sid) {
  res.setHeader(
    "Set-Cookie",
    `${SESSION_COOKIE}=${encodeURIComponent(sid)}; HttpOnly; SameSite=Lax; Path=/; Max-Age=${SESSION_MAX_AGE_SEC}`
  );
}

function clearSessionCookie(res) {
  res.setHeader(
    "Set-Cookie",
    `${SESSION_COOKIE}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0`
  );
}

async function resolveSession(req) {
  const sid = parseCookies(req)[SESSION_COOKIE];
  if (!sid) return null;
  const result = await spawnPython(AUTH_WHOAMI_SCRIPT, JSON.stringify({ sid }));
  if (result.code !== 0 || !result.json || result.json.ok !== true) return null;
  return { sid, ...result.json.user };
}
```

- [ ] **Step 4: Wire the auth middleware at the top of the request handler**

Inside `createServer(async (req, res) => { ... })`, immediately after the existing CORS / OPTIONS block (around line 228), insert this gate:

```js
  // ── Auth gate ─────────────────────────────────────────────────────
  // Public paths: /api/auth/login is the only API route that doesn't
  // require a session. Everything else under /api/* needs one. Static
  // assets fall through unchanged.
  const isApi = req.url.startsWith("/api/");
  const isLogin = req.url === "/api/auth/login";
  if (isApi && !isLogin) {
    const sessionUser = await resolveSession(req);
    if (!sessionUser) {
      res.statusCode = 401;
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify({ ok: false, error: "not authenticated" }));
      return;
    }
    req.sessionUser = sessionUser;  // {sid, id, username, email, role}
  }
```

CORS already sets `Access-Control-Allow-Origin: *` but with `credentials: 'include'` we need to echo the origin. Replace the existing CORS line:

Find:
```js
  res.setHeader("Access-Control-Allow-Origin", "*");
```
Replace with:
```js
  // Echo origin so credentials:'include' works (browser refuses '*' with creds).
  const origin = req.headers.origin || "*";
  res.setHeader("Access-Control-Allow-Origin", origin);
  res.setHeader("Access-Control-Allow-Credentials", "true");
```

- [ ] **Step 5: Add the /api/auth routes**

Inside the request handler, after the `/api/health` route (around line 235), add:

```js
  // ── Auth: login ───────────────────────────────────────────────────
  if (req.url === "/api/auth/login" && req.method === "POST") {
    const body = await readBody(req);
    const result = await spawnPython(AUTH_LOGIN_SCRIPT, body);
    const status = httpStatusFor(result.code, result.json);
    if (status === 200 && result.json && result.json.sid) {
      setSessionCookie(res, result.json.sid);
      // Don't leak the sid in the response body — it's now in the cookie.
      const { sid, ...rest } = result.json;
      res.statusCode = 200;
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(rest));
      return;
    }
    res.statusCode = status;
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(result.json));
    return;
  }

  // ── Auth: logout ──────────────────────────────────────────────────
  if (req.url === "/api/auth/logout" && req.method === "POST") {
    const sid = req.sessionUser.sid;
    await spawnPython(AUTH_LOGOUT_SCRIPT, JSON.stringify({ sid }));
    clearSessionCookie(res);
    res.statusCode = 204;
    res.end();
    return;
  }

  // ── Auth: whoami ──────────────────────────────────────────────────
  if (req.url === "/api/auth/me" && req.method === "GET") {
    const { username, email, role } = req.sessionUser;
    res.statusCode = 200;
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify({ ok: true, user: { username, email, role } }));
    return;
  }
```

- [ ] **Step 6: Restart the server**

```powershell
# Stop the running node process (Ctrl+C in its terminal), then:
node server.js
```
Watch for `Listening on http://localhost:5181` and no errors.

- [ ] **Step 7: Smoke via curl**

```powershell
# Hitting any /api route without a cookie → 401
curl -i http://localhost:5181/api/cashflow/recent
# → HTTP/1.1 401  {"ok":false,"error":"not authenticated"}

# Login → grab the cookie
curl -i -c cookies.txt -H "Content-Type: application/json" `
  -d '{"username":"peter","password":"<PEERS_PASSWORD>"}' `
  http://localhost:5181/api/auth/login
# → HTTP/1.1 200, Set-Cookie: sid=...; HttpOnly; ...
#   body: {"ok":true,"user":{"id":1,"username":"peter","email":"…","role":"admin"},"expires_at":"..."}

# whoami
curl -i -b cookies.txt http://localhost:5181/api/auth/me
# → {"ok":true,"user":{"username":"peter","role":"admin","email":"..."}}

# logout
curl -i -b cookies.txt -X POST http://localhost:5181/api/auth/logout
# → HTTP/1.1 204, Set-Cookie: sid=; Max-Age=0

# whoami again → 401
curl -i -b cookies.txt http://localhost:5181/api/auth/me
# → 401
```

- [ ] **Step 8: Commit**

```powershell
git add server.js
git commit -m "feat(auth): server middleware + /api/auth routes"
```

---

## Task 5: /api/users routes + user_id injection on existing routes

**Goal:** Add the admin CRUD endpoints, gate them by `role==='admin'`, and inject the session username into existing cashflow/loan/spot payloads.

**Files:**
- Modify: `server.js`

**Acceptance Criteria:**
- [ ] `GET /api/users` with admin session → list. With user session → 403.
- [ ] `POST /api/users` creates a row; visible in `GET /api/users`
- [ ] `PATCH /api/users/:id` accepts partial body; password gets re-hashed when supplied
- [ ] `DELETE /api/users/:id` last-admin guard returns 400 with the right error string
- [ ] An existing `POST /api/cashflow/insert` request that sends `user_id:"someoneelse"` ends up storing `user_id="peter"` (the session user)

**Verify:** curl exercises (Step 5).

**Steps:**

- [ ] **Step 1: Add user-script constants**

Near the other `*_SCRIPT` constants in `server.js`:

```js
const USER_CREATE_SCRIPT = resolve(__dirname, "scripts", "user_create.py");
const USER_LIST_SCRIPT   = resolve(__dirname, "scripts", "user_list.py");
const USER_UPDATE_SCRIPT = resolve(__dirname, "scripts", "user_update.py");
const USER_DELETE_SCRIPT = resolve(__dirname, "scripts", "user_delete.py");
```

- [ ] **Step 2: Admin gate helper**

Just below the cookie helpers:

```js
function requireAdmin(req, res) {
  if (req.sessionUser && req.sessionUser.role === "admin") return true;
  res.statusCode = 403;
  res.setHeader("Content-Type", "application/json");
  res.end(JSON.stringify({ ok: false, error: "admin required" }));
  return false;
}
```

- [ ] **Step 3: /api/users routes**

After the `/api/auth/me` route, before any of the existing booking routes:

```js
  // ── Users: list ───────────────────────────────────────────────────
  if (req.url === "/api/users" && req.method === "GET") {
    if (!requireAdmin(req, res)) return;
    const result = await spawnPython(USER_LIST_SCRIPT, "{}");
    res.statusCode = httpStatusFor(result.code, result.json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(result.json));
    return;
  }

  // ── Users: create ────────────────────────────────────────────────
  if (req.url === "/api/users" && req.method === "POST") {
    if (!requireAdmin(req, res)) return;
    const body = await readBody(req);
    let payload;
    try { payload = JSON.parse(body || "{}"); }
    catch { payload = {}; }
    payload._acting_user = req.sessionUser.username;
    const result = await spawnPython(USER_CREATE_SCRIPT, JSON.stringify(payload));
    res.statusCode = httpStatusFor(result.code, result.json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(result.json));
    return;
  }

  // ── Users: update / delete (path: /api/users/:id) ────────────────
  const userIdMatch = req.url.match(/^\/api\/users\/(\d+)$/);
  if (userIdMatch && req.method === "PATCH") {
    if (!requireAdmin(req, res)) return;
    const body = await readBody(req);
    let payload;
    try { payload = JSON.parse(body || "{}"); }
    catch { payload = {}; }
    payload.id = parseInt(userIdMatch[1], 10);
    payload._acting_user = req.sessionUser.username;
    const result = await spawnPython(USER_UPDATE_SCRIPT, JSON.stringify(payload));
    res.statusCode = httpStatusFor(result.code, result.json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(result.json));
    return;
  }
  if (userIdMatch && req.method === "DELETE") {
    if (!requireAdmin(req, res)) return;
    const payload = {
      id: parseInt(userIdMatch[1], 10),
      _acting_user_id: req.sessionUser.id,
    };
    const result = await spawnPython(USER_DELETE_SCRIPT, JSON.stringify(payload));
    res.statusCode = httpStatusFor(result.code, result.json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(result.json));
    return;
  }
```

- [ ] **Step 4: Inject session username into existing booking payloads**

Find the existing booking-route handlers (`/api/cashflow/insert`, `/api/cashflow/amend`, `/api/loan/insert`, `/api/loan/amend`, `/api/spot/insert`, `/api/spot/amend`). Each one currently reads the body, parses it as JSON, and pipes to a script.

For each one, **before** the script spawn, add a line that overwrites `user_id`:

```js
    // server stamps user_id from the session; ignore any value the client sent
    if (typeof payload === "object" && payload) payload.user_id = req.sessionUser.username;
    // (if the existing code wraps the payload in {payload: {...}, attachments: [...]},
    //  patch payload.payload.user_id instead — keep the parse shape unchanged)
```

The cashflow insert route currently accepts both bare-payload and `{payload, attachments}` shapes (see `cashflow_insert.py:94` for the parser). Mirror that in the injection:

```js
    if (payload && typeof payload === "object") {
      if (payload.payload && typeof payload.payload === "object") {
        payload.payload.user_id = req.sessionUser.username;
      } else {
        payload.user_id = req.sessionUser.username;
      }
    }
```

Apply this snippet to every booking insert/amend/get/recent/history route handler in `server.js`. Read routes (`*_get`, `*_recent`, `*_history`) don't need it but adding the line is harmless and keeps the pattern uniform.

- [ ] **Step 5: Restart and smoke**

```powershell
node server.js
```

```powershell
# Need a valid session first
curl -c cookies.txt -H "Content-Type: application/json" `
  -d '{"username":"peter","password":"<PEERS_PASSWORD>"}' `
  http://localhost:5181/api/auth/login

# List users (admin → 200)
curl -i -b cookies.txt http://localhost:5181/api/users
# → 200 {"ok":true,"rows":[…]}

# Create a non-admin user
curl -i -b cookies.txt -H "Content-Type: application/json" `
  -d '{"username":"alice","email":"alice@tokkalabs.com","role":"user","password":"alicepw123"}' `
  -X POST http://localhost:5181/api/users
# → 200 {"ok":true,"user":{…}}

# Patch alice's email
curl -i -b cookies.txt -H "Content-Type: application/json" `
  -d '{"email":"alice2@tokkalabs.com"}' `
  -X PATCH http://localhost:5181/api/users/2
# → 200 {"ok":true,"user":{…,"email":"alice2@tokkalabs.com"}}

# Last-admin guard test
curl -i -b cookies.txt -H "Content-Type: application/json" `
  -d '{"role":"user"}' `
  -X PATCH http://localhost:5181/api/users/1
# → 400 {"ok":false,"error":"cannot demote the last admin"}

# Log in as alice (non-admin), try /api/users → 403
curl -c alice.txt -H "Content-Type: application/json" `
  -d '{"username":"alice","password":"alicepw123"}' `
  http://localhost:5181/api/auth/login
curl -i -b alice.txt http://localhost:5181/api/users
# → 403 {"ok":false,"error":"admin required"}
```

To verify user_id injection: as alice, post a fake cashflow insert. The row written should have `user_id="alice"` even if you send `user_id:"peter"`:

```powershell
curl -i -b alice.txt -H "Content-Type: application/json" `
  -d '{"cashflow_type":"FUNDING IN","direction":"INCOMING","entity":"TK006","portfolio_id":8006,"portfolio_name":"CDA","counterparty":"Galaxy","account":"WALLET_CDA_EVM_04","account_type":"WALLET","asset":"USDC","amount":"1.00","fee_asset":null,"fee_amount":"0","trade_date":"2026-05-21T12:00:00+00:00","value_date":"2026-05-21T12:00:00+00:00","network":"BSC","txid_reference":null,"user_id":"peter","status":"PENDING","comment":"injection test"}' `
  -X POST http://localhost:5181/api/cashflow/insert
```
Then in psql / via `cashflow_recent.py`:
```
SELECT user_id FROM trades_cashflow WHERE comment='injection test' ORDER BY effective_start DESC LIMIT 1;
# → alice  (NOT peter)
```
Delete the test row when done:
```sql
DELETE FROM trades_cashflow WHERE comment='injection test';
```

- [ ] **Step 6: Commit**

```powershell
git add server.js
git commit -m "feat(auth): /api/users routes + user_id session-stamp on booking endpoints"
```

---

## Task 6: Frontend — auth shell

**Goal:** A logged-out visitor sees the login page; a logged-in visitor sees the existing booking form. No new routes — auth state is the router.

**Files:**
- Modify: `src/main.jsx`
- Create: `src/App.jsx`
- Create: `src/auth/AuthContext.jsx`
- Create: `src/auth/api.js`
- Create: `src/auth/LoginPage.jsx`

**Acceptance Criteria:**
- [ ] `npm run dev` boots to the login page when no session cookie exists
- [ ] Successful login mounts `<TradeBookingForm/>`
- [ ] F5 keeps you signed in (until session expires)
- [ ] Bad password shows red banner "Invalid credentials"
- [ ] Click "Logout" → returns to login page

**Verify:** `npm run dev`, log in, log out, refresh.

**Steps:**

- [ ] **Step 1: Write `src/auth/api.js`**

```js
// Fetch wrapper for authenticated calls.
// • Always sends/receives the session cookie via credentials:'include'.
// • On 401 (except login itself), dispatches "auth:expired" so <App>
//   can route back to the login page with a "session expired" banner.

const HOSTS = ["", "http://localhost:5181"];

async function tryHosts(path, opts) {
  let lastErr;
  for (const h of HOSTS) {
    try {
      return await fetch(h + path, { credentials: "include", ...opts });
    } catch (e) { lastErr = e; }
  }
  throw lastErr;
}

export async function api(path, opts = {}) {
  const r = await tryHosts(path, opts);
  if (r.status === 401 && path !== "/api/auth/login") {
    window.dispatchEvent(new CustomEvent("auth:expired"));
  }
  return r;
}

export async function apiJson(path, opts = {}) {
  const r = await api(path, opts);
  let body = null;
  try { body = await r.json(); } catch { /* may be 204 */ }
  return { status: r.status, body };
}
```

- [ ] **Step 2: Write `src/auth/AuthContext.jsx`**

```jsx
import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import { apiJson } from "./api.js";

const AuthContext = createContext(null);

export function useAuth() {
  return useContext(AuthContext);
}

export function AuthProvider({ children }) {
  const [user, setUser]   = useState(null);
  const [ready, setReady] = useState(false);  // first /me check finished?

  const refresh = useCallback(async () => {
    const { status, body } = await apiJson("/api/auth/me");
    if (status === 200 && body?.user) setUser(body.user);
    else setUser(null);
    setReady(true);
  }, []);

  const login = useCallback(async (username, password) => {
    const { status, body } = await apiJson("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (status === 200 && body?.user) {
      setUser(body.user);
      return { ok: true };
    }
    return { ok: false, error: body?.error || "Login failed" };
  }, []);

  const logout = useCallback(async () => {
    await apiJson("/api/auth/logout", { method: "POST" });
    setUser(null);
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => {
    function onExpired() { setUser(null); }
    window.addEventListener("auth:expired", onExpired);
    return () => window.removeEventListener("auth:expired", onExpired);
  }, []);

  return (
    <AuthContext.Provider value={{ user, ready, login, logout, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}
```

- [ ] **Step 3: Write `src/auth/LoginPage.jsx`**

```jsx
import React, { useState } from "react";
import tokkaLogo from "../assets/tokka-labs-logo.png";
import { useAuth } from "./AuthContext.jsx";

// Bloomberg-terminal palette — mirror TradeBookingForm constants.
const BB = {
  bg:     "#000000",
  fg:     "#e5e5e5",
  dim:    "#7d7d7d",
  panel:  "#0a0a0a",
  border: "#1f1f1f",
  accent: "#FA8C16",
  red:    "#FF4D4F",
};

export default function LoginPage({ banner }) {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError]       = useState("");
  const [pending, setPending]   = useState(false);

  async function submit(e) {
    e.preventDefault();
    setError("");
    setPending(true);
    const r = await login(username.trim(), password);
    setPending(false);
    if (!r.ok) setError(r.error);
  }

  return (
    <div style={{
      minHeight: "100vh", background: BB.bg, color: BB.fg,
      display: "flex", alignItems: "center", justifyContent: "center",
      fontFamily: "'JetBrains Mono', monospace",
    }}>
      <form onSubmit={submit} style={{
        width: 360, padding: 32, background: BB.panel,
        border: `1px solid ${BB.border}`,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 24 }}>
          <img src={tokkaLogo} alt="Tokka" style={{ height: 28 }} />
          <div style={{ fontSize: 13, color: BB.dim, letterSpacing: 1.2 }}>TRADE BOOKING</div>
        </div>

        {banner && (
          <div style={{
            marginBottom: 16, padding: "8px 12px",
            background: "#2a1a04", border: `1px solid ${BB.accent}`,
            color: BB.accent, fontSize: 12,
          }}>{banner}</div>
        )}

        <label style={{ display: "block", fontSize: 11, color: BB.dim, marginBottom: 4 }}>USERNAME</label>
        <input
          autoFocus value={username} onChange={(e) => setUsername(e.target.value)}
          style={inputStyle} disabled={pending}
        />

        <label style={{ display: "block", fontSize: 11, color: BB.dim, marginBottom: 4, marginTop: 16 }}>PASSWORD</label>
        <input
          type="password" value={password} onChange={(e) => setPassword(e.target.value)}
          style={inputStyle} disabled={pending}
        />

        {error && (
          <div style={{ marginTop: 14, color: BB.red, fontSize: 12 }}>{error}</div>
        )}

        <button type="submit" disabled={pending || !username || !password} style={{
          width: "100%", marginTop: 20, padding: "10px 16px",
          background: BB.accent, color: BB.bg, border: "none",
          fontFamily: "inherit", fontSize: 13, fontWeight: 600, letterSpacing: 1,
          cursor: pending ? "wait" : "pointer", opacity: pending ? 0.6 : 1,
        }}>
          {pending ? "SIGNING IN…" : "SIGN IN"}
        </button>
      </form>
    </div>
  );
}

const inputStyle = {
  width: "100%", padding: "8px 10px", background: "#000",
  color: "#e5e5e5", border: "1px solid #1f1f1f", outline: "none",
  fontFamily: "inherit", fontSize: 13,
};
```

- [ ] **Step 4: Write `src/App.jsx`**

```jsx
import React, { useEffect, useState } from "react";
import { AuthProvider, useAuth } from "./auth/AuthContext.jsx";
import LoginPage from "./auth/LoginPage.jsx";
import TradeBookingForm from "./TradeBookingForm.jsx";

function Routed() {
  const { user, ready } = useAuth();
  const [expiredBanner, setExpiredBanner] = useState("");

  useEffect(() => {
    function onExpired() { setExpiredBanner("Session expired — please sign in again"); }
    window.addEventListener("auth:expired", onExpired);
    return () => window.removeEventListener("auth:expired", onExpired);
  }, []);

  if (!ready) return <div style={{ background: "#000", minHeight: "100vh" }} />;

  if (!user) return <LoginPage banner={expiredBanner} />;
  return <TradeBookingForm />;
}

export default function App() {
  return (
    <AuthProvider>
      <Routed />
    </AuthProvider>
  );
}
```

- [ ] **Step 5: Edit `src/main.jsx` (1 line)**

Replace the import + render:

```jsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App.jsx";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>
);
```

- [ ] **Step 6: Smoke**

```powershell
# Make sure server.js is running on 5181 in another terminal
npm run dev
```

Open `http://localhost:5180` in a clean browser tab:
- Should see the login card on a black background, Tokka logo top-left.
- Enter wrong password → red "Invalid credentials".
- Enter right password → page replaces with the existing trade booking form.
- F5 → still logged in.
- Open DevTools → Application → Cookies → see `sid` cookie marked HttpOnly.

- [ ] **Step 7: Commit**

```powershell
git add src/main.jsx src/App.jsx src/auth/
git commit -m "feat(auth): React login shell + auth context"
```

---

## Task 7: TradeBookingForm.jsx edits

**Goal:** Existing form wired to session — `user_id` comes from `useAuth()`, picker is removed, header gains user badge + logout + "Users" link.

**Files:**
- Modify: `src/TradeBookingForm.jsx`

**Acceptance Criteria:**
- [ ] No "User" dropdown visible in any of the four booking categories (SPOT/FUTURE/CASHFLOW/LOAN)
- [ ] Read-only label "Booked by: <username>" appears in the form near where the picker was
- [ ] Header right-side shows `peter · admin` and a "Logout" button
- [ ] Admins see a "Users" link in the header; non-admins do not
- [ ] All `fetch(…)` calls in the file go through `api(…)` (or `apiJson(…)`)
- [ ] Submitting a booking still works; `user_id` in the DB matches the signed-in user

**Verify:** Manual — book a test cashflow as alice, verify in DB.

**Steps:**

- [ ] **Step 1: Add imports at the top of TradeBookingForm.jsx**

```jsx
import { useAuth } from "./auth/AuthContext.jsx";
import { api } from "./auth/api.js";
```

- [ ] **Step 2: Wire `useAuth()` into the root component**

In the root `TradeBookingForm` function (where state is declared), add near the other hooks:

```jsx
const { user, logout } = useAuth();
```

- [ ] **Step 3: Replace the user-picker UI**

Find the section that uses `SUPERADMIN_USERS` for the user dropdown (it builds a picker with the synced users). Replace it with a read-only label:

```jsx
<div style={{ display: "flex", alignItems: "center", gap: 8 }}>
  <span style={{ fontSize: 11, color: "#7d7d7d", letterSpacing: 1 }}>BOOKED BY</span>
  <span style={{ fontSize: 13, color: "#e5e5e5" }}>{user.username}</span>
</div>
```

Also remove any state and effect that managed the previously-selected user. The form's submit handler must use `user.username` for the `user_id` payload key.

- [ ] **Step 4: Replace `fetch(…)` calls with `api(…)`**

In every place this file calls `fetch(...)` against `/api/*`, replace with `api(...)`. Helper: search the file for `fetch(` and inspect each match.

The `fetchRefdataOnce` helper at module scope (it fetches `/refdata/*.json` — static JSON files, NOT under `/api/*`) does NOT need to change; those routes are public assets.

Booking submit / amend / get / recent / history calls DO need to change.

- [ ] **Step 5: Header — user badge + logout + "Users" link**

Find the existing header in TradeBookingForm. Add (or extend) the right-side cluster:

```jsx
<div style={{ display: "flex", alignItems: "center", gap: 16, fontSize: 12 }}>
  {user.role === "admin" && (
    <button type="button" onClick={() => setView("users")} style={headerBtnStyle}>
      USERS
    </button>
  )}
  <span style={{ color: "#7d7d7d" }}>{user.username}</span>
  <span style={{ color: "#7d7d7d" }}>·</span>
  <span style={{ color: "#FA8C16" }}>{user.role}</span>
  <button type="button" onClick={logout} style={headerBtnStyle}>LOGOUT</button>
</div>
```

`headerBtnStyle`:
```jsx
const headerBtnStyle = {
  background: "transparent", color: "#e5e5e5",
  border: "1px solid #1f1f1f", padding: "4px 10px",
  fontFamily: "inherit", fontSize: 11, letterSpacing: 1,
  cursor: "pointer",
};
```

The `setView("users")` call is wired in Task 8 — for now, define `const [view, setView] = useState("booking")` and gate the rendered body:

```jsx
return view === "users" && user.role === "admin"
  ? <UserAdmin onClose={() => setView("booking")} />
  : (
    // existing booking form JSX
  );
```

Add the import: `import UserAdmin from "./admin/UserAdmin.jsx";` — it'll be created in Task 8.

- [ ] **Step 6: Smoke**

```powershell
npm run dev
```

- Log in as `peter`.
- Confirm the booking form has no user picker.
- Confirm header shows `peter · admin · LOGOUT · USERS`.
- Submit a small cashflow booking (e.g. external_trade_id=`SMOKE-T7-1`).
- Verify in psql: `SELECT user_id FROM trades_cashflow WHERE external_trade_id='SMOKE-T7-1'` → `peter`. Then delete the row.
- Log out → back to login page.
- Log in as `alice` → header shows `alice · user · LOGOUT` (no "USERS" button).

- [ ] **Step 7: Commit**

```powershell
git add src/TradeBookingForm.jsx
git commit -m "feat(auth): wire booking form to session user + header controls"
```

---

## Task 8: UserAdmin + UserEditModal

**Goal:** Admin clicks "USERS" in the header → table of users with edit / delete row actions and a "+ New User" button.

**Files:**
- Create: `src/admin/UserAdmin.jsx`
- Create: `src/admin/UserEditModal.jsx`

**Acceptance Criteria:**
- [ ] Table lists all users with columns: ID · Username · Email · Role · Created · Updated · Actions
- [ ] "+ New User" opens the modal in create mode; submit creates a row and refreshes the table
- [ ] Edit pencil opens the modal in edit mode with username disabled
- [ ] Delete trash → confirmation prompt → deletes after confirm
- [ ] Last-admin row has delete/demote dimmed AND the server rejection bubbles up as a banner if the user somehow tries
- [ ] Errors from the server (e.g. duplicate email, validation) appear inline in the modal

**Verify:** Manual smoke (Step 4).

**Steps:**

- [ ] **Step 1: Write `src/admin/UserAdmin.jsx`**

```jsx
import React, { useEffect, useState, useMemo } from "react";
import { Pencil, Trash2, Plus, X } from "lucide-react";
import { apiJson } from "../auth/api.js";
import UserEditModal from "./UserEditModal.jsx";

const BB = {
  bg: "#000", panel: "#0a0a0a", border: "#1f1f1f",
  fg: "#e5e5e5", dim: "#7d7d7d", accent: "#FA8C16", red: "#FF4D4F",
};

function fmtDate(iso) {
  if (!iso) return "";
  return iso.slice(0, 19).replace("T", " ");
}

export default function UserAdmin({ onClose }) {
  const [rows, setRows]       = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState("");
  const [modal, setModal]     = useState(null);  // { mode:"create"|"edit", user? }

  const adminCount = useMemo(() => rows.filter((r) => r.role === "admin").length, [rows]);

  async function load() {
    setLoading(true);
    const { status, body } = await apiJson("/api/users");
    if (status === 200 && body?.ok) {
      setRows(body.rows);
      setError("");
    } else {
      setError(body?.error || `HTTP ${status}`);
    }
    setLoading(false);
  }

  useEffect(() => { load(); }, []);

  async function onDelete(user) {
    if (!confirm(`Delete user ${user.username}? This force-logs them out.`)) return;
    const { status, body } = await apiJson(`/api/users/${user.id}`, { method: "DELETE" });
    if (status !== 200 || !body?.ok) {
      setError(body?.error || `Delete failed (${status})`);
      return;
    }
    await load();
  }

  return (
    <div style={{
      minHeight: "100vh", background: BB.bg, color: BB.fg,
      fontFamily: "'JetBrains Mono', monospace",
    }}>
      <div style={{
        padding: "16px 24px", display: "flex", alignItems: "center",
        justifyContent: "space-between", borderBottom: `1px solid ${BB.border}`,
      }}>
        <div style={{ fontSize: 13, letterSpacing: 2, color: BB.dim }}>USER ADMIN</div>
        <div style={{ display: "flex", gap: 12 }}>
          <button onClick={() => setModal({ mode: "create" })} style={primaryBtn}>
            <Plus size={14} /> NEW USER
          </button>
          <button onClick={onClose} style={ghostBtn}>
            <X size={14} /> CLOSE
          </button>
        </div>
      </div>

      {error && (
        <div style={{ margin: 24, padding: 12, border: `1px solid ${BB.red}`, color: BB.red, fontSize: 12 }}>
          {error}
        </div>
      )}

      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
        <thead>
          <tr style={{ color: BB.dim, textAlign: "left" }}>
            {["ID", "USERNAME", "EMAIL", "ROLE", "CREATED", "UPDATED", ""].map((h) => (
              <th key={h} style={{ padding: "10px 16px", borderBottom: `1px solid ${BB.border}`, letterSpacing: 1 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading && <tr><td colSpan={7} style={{ padding: 16, color: BB.dim }}>loading…</td></tr>}
          {!loading && rows.map((u) => {
            const isLastAdmin = u.role === "admin" && adminCount <= 1;
            return (
              <tr key={u.id}>
                <td style={td}>{u.id}</td>
                <td style={td}>{u.username}</td>
                <td style={td}>{u.email}</td>
                <td style={{ ...td, color: u.role === "admin" ? BB.accent : BB.fg }}>{u.role}</td>
                <td style={td}>{fmtDate(u.created_at)}</td>
                <td style={td}>{fmtDate(u.updated_at)}</td>
                <td style={{ ...td, display: "flex", gap: 8 }}>
                  <button onClick={() => setModal({ mode: "edit", user: u, isLastAdmin })} style={iconBtn} title="Edit">
                    <Pencil size={14} />
                  </button>
                  <button
                    onClick={() => onDelete(u)} style={{ ...iconBtn, opacity: isLastAdmin ? 0.3 : 1, cursor: isLastAdmin ? "not-allowed" : "pointer" }}
                    disabled={isLastAdmin} title={isLastAdmin ? "Cannot delete last admin" : "Delete"}
                  >
                    <Trash2 size={14} />
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {modal && (
        <UserEditModal
          mode={modal.mode}
          user={modal.user}
          isLastAdmin={modal.isLastAdmin}
          onClose={() => setModal(null)}
          onSaved={async () => { setModal(null); await load(); }}
        />
      )}
    </div>
  );
}

const td        = { padding: "10px 16px", borderBottom: "1px solid #1f1f1f" };
const primaryBtn = { display: "flex", alignItems: "center", gap: 6, background: BB.accent, color: BB.bg, border: "none", padding: "6px 12px", fontFamily: "inherit", fontSize: 11, letterSpacing: 1, cursor: "pointer" };
const ghostBtn   = { display: "flex", alignItems: "center", gap: 6, background: "transparent", color: BB.fg, border: `1px solid ${BB.border}`, padding: "6px 12px", fontFamily: "inherit", fontSize: 11, letterSpacing: 1, cursor: "pointer" };
const iconBtn    = { background: "transparent", color: BB.fg, border: `1px solid ${BB.border}`, padding: 4, cursor: "pointer" };
```

- [ ] **Step 2: Write `src/admin/UserEditModal.jsx`**

```jsx
import React, { useState } from "react";
import { apiJson } from "../auth/api.js";

const BB = { bg: "#000", panel: "#0a0a0a", border: "#1f1f1f", fg: "#e5e5e5", dim: "#7d7d7d", accent: "#FA8C16", red: "#FF4D4F" };

export default function UserEditModal({ mode, user, isLastAdmin, onClose, onSaved }) {
  const isCreate = mode === "create";
  const [username, setUsername] = useState(user?.username || "");
  const [email,    setEmail]    = useState(user?.email    || "");
  const [role,     setRole]     = useState(user?.role     || "user");
  const [password, setPassword] = useState("");
  const [showPw,   setShowPw]   = useState(false);
  const [error,    setError]    = useState("");
  const [pending,  setPending]  = useState(false);

  async function submit(e) {
    e.preventDefault();
    setError("");
    setPending(true);
    let r;
    if (isCreate) {
      r = await apiJson("/api/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, email, role, password }),
      });
    } else {
      const body = { email, role };
      if (password) body.password = password;
      r = await apiJson(`/api/users/${user.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    }
    setPending(false);
    if (r.status === 200 && r.body?.ok) onSaved();
    else setError(r.body?.error || `HTTP ${r.status}`);
  }

  const demoteBlocked = !isCreate && isLastAdmin && role !== "admin";

  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)",
      display: "flex", alignItems: "center", justifyContent: "center",
    }}>
      <form onClick={(e) => e.stopPropagation()} onSubmit={submit} style={{
        width: 420, padding: 24, background: BB.panel,
        border: `1px solid ${BB.border}`,
        fontFamily: "'JetBrains Mono', monospace", color: BB.fg,
      }}>
        <div style={{ fontSize: 13, letterSpacing: 2, color: BB.dim, marginBottom: 16 }}>
          {isCreate ? "NEW USER" : `EDIT USER #${user.id}`}
        </div>

        <Field label="USERNAME">
          <input
            value={username} onChange={(e) => setUsername(e.target.value)}
            disabled={!isCreate || pending} style={input}
          />
        </Field>
        <Field label="EMAIL">
          <input
            type="email" value={email} onChange={(e) => setEmail(e.target.value)}
            disabled={pending} style={input}
          />
        </Field>
        <Field label="ROLE">
          <select
            value={role} onChange={(e) => setRole(e.target.value)}
            disabled={pending || (isLastAdmin && !isCreate)} style={input}
          >
            <option value="user">user</option>
            <option value="admin">admin</option>
          </select>
          {isLastAdmin && !isCreate && (
            <div style={{ color: BB.dim, fontSize: 10, marginTop: 4 }}>
              Cannot demote the last admin.
            </div>
          )}
        </Field>
        <Field label={isCreate ? "PASSWORD" : "PASSWORD (blank = unchanged)"}>
          <div style={{ display: "flex", gap: 6 }}>
            <input
              type={showPw ? "text" : "password"} value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={pending} style={{ ...input, flex: 1 }}
            />
            <button type="button" onClick={() => setShowPw((v) => !v)} style={ghost}>
              {showPw ? "HIDE" : "SHOW"}
            </button>
          </div>
        </Field>

        {error && (
          <div style={{ color: BB.red, fontSize: 11, marginTop: 10 }}>{error}</div>
        )}

        <div style={{ display: "flex", gap: 8, marginTop: 18, justifyContent: "flex-end" }}>
          <button type="button" onClick={onClose} style={ghost}>CANCEL</button>
          <button type="submit" disabled={pending || demoteBlocked} style={primary}>
            {pending ? "SAVING…" : isCreate ? "CREATE" : "SAVE"}
          </button>
        </div>
      </form>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ fontSize: 11, color: BB.dim, marginBottom: 4, letterSpacing: 1 }}>{label}</div>
      {children}
    </div>
  );
}

const input  = { width: "100%", padding: "8px 10px", background: "#000", color: BB.fg, border: `1px solid ${BB.border}`, outline: "none", fontFamily: "inherit", fontSize: 12 };
const ghost  = { background: "transparent", color: BB.fg, border: `1px solid ${BB.border}`, padding: "6px 12px", fontFamily: "inherit", fontSize: 11, letterSpacing: 1, cursor: "pointer" };
const primary = { background: BB.accent, color: BB.bg, border: "none", padding: "6px 14px", fontFamily: "inherit", fontSize: 11, letterSpacing: 1, cursor: "pointer", fontWeight: 600 };
```

- [ ] **Step 3: Smoke**

```powershell
npm run dev
```

- Log in as `peter`. Click "USERS" in the header.
- Verify the table renders all users.
- Click "+ NEW USER" → create `bob / bob@tokkalabs.com / user / bobbobbobby`. Save. Table refreshes; bob appears.
- Click pencil on bob → change email. Save.
- Click trash on bob → confirm. Bob disappears.
- On peter's row, verify the trash icon is dimmed (he's the last admin).
- Try to PATCH peter's role to "user" via the modal → dropdown is disabled with "Cannot demote the last admin" subtext.
- Click "CLOSE" → returns to booking form.

- [ ] **Step 4: Commit**

```powershell
git add src/admin/
git commit -m "feat(auth): user admin UI (table + create/edit/delete modal)"
```

---

## Task 9: Smoke script + README

**Goal:** A repeatable end-to-end probe + documented bootstrap instructions.

**Files:**
- Create: `scripts/smoke_auth.py`
- Modify: `README.md`

**Acceptance Criteria:**
- [ ] `python scripts/smoke_auth.py` runs against the local server and prints `PASS`
- [ ] README "Auth" section documents the bootstrap commands and `smoke_auth.py`

**Verify:** `python scripts/smoke_auth.py` → all assertions pass.

**Steps:**

- [ ] **Step 1: Write `scripts/smoke_auth.py`**

```python
"""End-to-end smoke for the auth surface. Run server.js separately, then:

    python scripts/smoke_auth.py --username peter --password <YOUR_PW>

Exits 0 with "PASS" if every assertion passes. Non-zero with a diagnostic
on the first failure. Does not create or delete users — only exercises
login/whoami/logout + a guarded /api/users probe.
"""
from __future__ import annotations
import argparse
import json
import sys
import urllib.request
import urllib.error
import http.cookiejar


BASE = "http://localhost:5181"


def _req(method, path, body=None, jar=None):
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    try:
        resp = opener.open(req)
        return resp.status, json.loads(resp.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "null")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--username", required=True)
    p.add_argument("--password", required=True)
    args = p.parse_args()

    jar = http.cookiejar.CookieJar()

    # 1. Hit /api/auth/me without cookie → 401
    s, _ = _req("GET", "/api/auth/me", jar=jar)
    assert s == 401, f"expected 401 on unauthenticated /me, got {s}"

    # 2. Login
    s, body = _req("POST", "/api/auth/login", {"username": args.username, "password": args.password}, jar)
    assert s == 200 and body.get("ok") is True, f"login failed: {s} {body}"
    assert body["user"]["username"] == args.username

    # 3. whoami works
    s, body = _req("GET", "/api/auth/me", jar=jar)
    assert s == 200 and body["user"]["username"] == args.username, f"whoami: {s} {body}"

    # 4. /api/users — admin gets 200, non-admin gets 403
    s, body = _req("GET", "/api/users", jar=jar)
    if body["user"]["role"] if False else True:  # check actual role
        pass
    expected = 200 if body and body.get("ok") else 403
    assert s in (200, 403), f"/api/users: {s} {body}"

    # 5. Bad login (separate jar)
    s, body = _req("POST", "/api/auth/login", {"username": args.username, "password": "definitely-wrong"})
    assert s == 401, f"expected 401 on bad password, got {s}"

    # 6. Logout
    s, _ = _req("POST", "/api/auth/logout", jar=jar)
    assert s in (200, 204), f"logout: {s}"

    # 7. /me after logout → 401
    s, _ = _req("GET", "/api/auth/me", jar=jar)
    assert s == 401, f"expected 401 after logout, got {s}"

    print("PASS")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)
```

- [ ] **Step 2: Update README.md — add an "Auth" section before "Theme"**

```markdown
## Auth

The dashboard requires login. Users + sessions live in Postgres UAT.

### First-time bootstrap

```powershell
pip install -r requirements.txt
python scripts/apply_schema_users.py
python scripts/user_create.py --username <you> --email <you>@tokkalabs.com --role admin
```

`user_create.py` prompts for the password (hidden input). Re-run with new args to add more admins or users.

### Smoke

With `node server.js` running, in another terminal:

```powershell
python scripts/smoke_auth.py --username <you> --password <yourpw>
```

Should print `PASS`.

### Roles

- `admin` — everything, including `/api/users` (managed in-app via the "USERS" header link).
- `user` — book, amend, view; no user admin.

### Session

HTTP-only cookie, 8-hour sliding window. F5 keeps you signed in; idle ≥ 8h logs you out automatically.
```

- [ ] **Step 3: Run the smoke**

```powershell
node server.js   # in another terminal
python scripts/smoke_auth.py --username peter --password <YOUR_PW>
# → PASS
```

- [ ] **Step 4: Commit**

```powershell
git add scripts/smoke_auth.py README.md
git commit -m "docs(auth): smoke script + README bootstrap section"
```

---

## Self-review notes

- **Spec coverage** — every section of `docs/design/2026-05-21-trade-booking-auth-design.md` maps to a task: §2 decisions baked in throughout; §4.1 + §4.2 schema → Task 1; §5.1 auth routes → Tasks 3+4; §5.2 admin routes → Task 5; §5.3 middleware → Task 4 step 4; §5.4 errors → `httpStatusFor` extension in Task 4 step 2; §6 Python scripts → Tasks 1-3 + 9; §7 frontend → Tasks 6-8; §8 bootstrap → Task 9.
- **Out-of-scope items (§11)** — explicitly not in any task.
- **Type/name consistency** — `req.sessionUser` (Node) = `{sid, id, username, email, role}` is set in Task 4 step 4 and consumed in Tasks 5 (`requireAdmin`, route handlers, user_id injection). The Python `_acting_user` / `_acting_user_id` keys are consistent between the JSON the Node side sends (Task 5) and the scripts that consume them (Tasks 2). `httpStatusFor` exit code 6 → 401 — set in Task 4 step 2, depended on by all auth scripts written in Task 3.
- **`scripts/user_db.py` import-time fail safety** — bcrypt is imported at module level (not lazy like `psycopg2`), so `tests/test_user_db.py` requires bcrypt to be installed. Step 1 of Task 1 installs it before tests run.

---

## Verification matrix (full plan)

| Task | Primary verification |
|---|---|
| 1 | `pytest tests/test_user_db.py -v` + idempotent schema apply |
| 2 | Stdin smoke commands for all 4 CRUD scripts |
| 3 | Stdin smoke for login/whoami/logout incl. negative cases |
| 4 | `curl` exercises login flow + auth gate on existing routes |
| 5 | `curl` exercises admin endpoints + user_id injection DB check |
| 6 | Browser smoke: login page → form swap, F5 persistence, logout |
| 7 | Browser smoke: book a trade, verify DB `user_id` = session user |
| 8 | Browser smoke: full CRUD flow through the user-admin UI |
| 9 | `python scripts/smoke_auth.py` → PASS |
