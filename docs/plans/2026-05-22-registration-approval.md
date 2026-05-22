# Trade Booking — Self-Registration with Admin Approval — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship two features on top of the 2026-05-21 auth system: (a) a show/hide password toggle on the login form, and (b) public self-registration with an admin approval queue that gates first login.

**Architecture:** One backward-compatible ALTER on the existing `users` table (new `status`/`approved_at`/`approved_by` columns, `role` made nullable for pending rows). Three new Python scripts (`auth_register.py`, `user_approve.py`, `user_reject.py`) follow the established stdin-JSON → stdout-JSON pattern. `server.js` gains one public route (`/api/auth/register`) and two admin routes (`/api/users/:id/approve`, `/api/users/:id/reject`). The React app gains a `RegisterPage`, an App-level `mode` toggle between login/register, a show/hide password toggle on `LoginPage`, and an `ACTIVE / PENDING` tab strip in `UserAdmin`.

**Tech Stack:** Python 3.11 (`bcrypt`, `psycopg2`), Node 22 (no new deps), React 19 (no new deps, `lucide-react` already in use), Postgres UAT.

**Spec:** `docs/design/2026-05-22-registration-approval-design.md` (committed at `290b39f`).

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `scripts/apply_schema_users_pending.py` | Create | Idempotent ALTER: add `status`/`approved_at`/`approved_by`, relax `role` NOT NULL, add CHECK constraint |
| `scripts/auth_register.py` | Create | stdin `{username,email,password}` → inserts pending row, returns `{ok,user}` or 409 conflict |
| `scripts/user_approve.py` | Create | stdin `{user_id,role,_acting_user}` → flips status=active + sets role + audit; 404/409 if not pending |
| `scripts/user_reject.py` | Create | stdin `{user_id}` → DELETE pending row; 404/409 if not pending |
| `scripts/auth_login.py` | Modify | Add post-password status check; pending → exit 6 with `"Account pending admin approval"` |
| `scripts/user_db.py` | Modify | Append `status`/`approved_at`/`approved_by` to `PUBLIC_COLUMNS` |
| `scripts/smoke_auth.py` | Modify | Add `--register` mode covering register → pending-login → approve → login → reject path |
| `server.js` | Modify | Add `/api/auth/register` (public-bypass), `/api/users/:id/approve` (admin), `/api/users/:id/reject` (admin) |
| `src/auth/LoginPage.jsx` | Modify | Eye/EyeOff toggle on password input; REQUEST ACCOUNT link; banner support |
| `src/auth/RegisterPage.jsx` | Create | Bloomberg-terminal styled register form (username/email/password/confirm) with show/hide toggles |
| `src/auth/api.js` | Modify | Add `register()` helper |
| `src/App.jsx` | Modify | Add `mode: "login" \| "register"` state when unauthenticated; route between LoginPage/RegisterPage |
| `src/admin/UserAdmin.jsx` | Modify | ACTIVE/PENDING tab strip; pending action buttons; APPROVED BY column; 30s polling |
| `tests/test_auth_register.py` | Create | Pure-logic + FakeCursor unit tests for the new script |
| `tests/test_user_approve.py` | Create | Same pattern |
| `tests/test_user_reject.py` | Create | Same pattern |
| `tests/test_auth_login.py` | Create | Extend (file doesn't exist today) — verify pending path returns new error, no session created |
| `helm/Chart.yaml`, `version.yml` | Modify | Patch bump via `scripts/update_version.py` |
| `README.md` | Modify | Document registration flow + admin approval workflow |

---

## Conventions inherited from this codebase

- **Script header:** docstring with manual smoke command, e.g. `echo '{…}' | python3 scripts/<name>.py`.
- **stdin/stdout contract:** scripts read JSON from stdin, write JSON to stdout. Exit code → HTTP via `server.js:httpStatusFor` (`0→200`, `3→400`, `4→404`, `5→500`, `6→401`; `code:"conflict"`→409).
- **DB connection inside `try` block:** wrap `user_db.connect()` inside try/except so creds/network failures surface as `{ok:false, error:"DB error", detail:…}` rather than empty stdout (pattern fixed across all `auth_*.py` on 2026-05-22).
- **Tests are pure-logic with FakeCursor.** No real DB in pytest; integration smoke lives in `scripts/smoke_auth.py` against UAT.
- **Commit style:** `type(scope): subject` lower-case (`feat(auth): …`, `fix(deps): …`, `docs(design): …`).
- **One bump per push to main.** Run `python scripts/update_version.py` and commit `chore: bump version X.Y.Z -> X.Y.(Z+1)` before `git push origin main`; ECR tag immutability gates the build.

---

## Task 1: Schema migration + PUBLIC_COLUMNS extension

**Goal:** Add the `status` / `approved_at` / `approved_by` columns to `users`, relax `role` NOT NULL, and surface the new columns in the `GET /api/users` response.

**Files:**
- Create: `scripts/apply_schema_users_pending.py`
- Modify: `scripts/user_db.py` (one line — extend `PUBLIC_COLUMNS`)

**Acceptance Criteria:**
- [ ] Running the script twice is a no-op the second time (idempotent).
- [ ] After running, `\d users` in psql shows the three new columns + the CHECK constraint + role nullable.
- [ ] Existing rows have `status='active'`, `approved_at=NULL`, `approved_by=NULL`.
- [ ] `user_db.PUBLIC_COLUMNS` includes `status`, `approved_at`, `approved_by`.

**Verify:**
```bash
python scripts/apply_schema_users_pending.py
python scripts/apply_schema_users_pending.py   # second run: still "ok"
python -c "import sys; sys.path.insert(0,'scripts'); import user_db; assert 'status' in user_db.PUBLIC_COLUMNS"
```
Expected: both runs print `ok: users table extended for registration flow`; assert passes silently.

**Steps:**

- [ ] **Step 1: Write the migration script**

Create `scripts/apply_schema_users_pending.py`:

```python
"""Extend `users` table with pending-registration columns. Idempotent.

Adds:
  - status         VARCHAR(16) NOT NULL DEFAULT 'active' CHECK ('pending'|'active')
  - approved_at    TIMESTAMPTZ NULL
  - approved_by    VARCHAR(64) NULL
  - relaxes role NOT NULL (pending rows have NULL role until approved)
  - CHECK: status='pending' OR role IS NOT NULL
"""
from __future__ import annotations
import cashflow_db


DDL = """
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS status      VARCHAR(16) NOT NULL DEFAULT 'active',
  ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS approved_by VARCHAR(64);

ALTER TABLE users
  DROP CONSTRAINT IF EXISTS users_status_check;
ALTER TABLE users
  ADD  CONSTRAINT users_status_check CHECK (status IN ('pending','active'));

ALTER TABLE users ALTER COLUMN role DROP NOT NULL;

ALTER TABLE users
  DROP CONSTRAINT IF EXISTS users_active_has_role;
ALTER TABLE users
  ADD  CONSTRAINT users_active_has_role CHECK (status = 'pending' OR role IS NOT NULL);
"""


def main() -> None:
    conn = cashflow_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(DDL)
        print("ok: users table extended for registration flow")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Extend `PUBLIC_COLUMNS` in `scripts/user_db.py`**

Find the line `PUBLIC_COLUMNS = ("id", "username", "email", "role", "created_at", "updated_at")` (around line 71) and replace with:

```python
PUBLIC_COLUMNS = (
    "id", "username", "email", "role",
    "status", "approved_at", "approved_by",
    "created_at", "updated_at",
)
```

- [ ] **Step 3: Run migration against UAT and verify**

```bash
python scripts/apply_schema_users_pending.py
python scripts/apply_schema_users_pending.py   # idempotency check
```
Expected output (both runs): `ok: users table extended for registration flow`

Verify in psql or via:
```bash
python -c "
import sys; sys.path.insert(0,'scripts')
import user_db
conn = user_db.connect()
with conn.cursor() as cur:
    cur.execute(\"SELECT column_name, is_nullable FROM information_schema.columns WHERE table_name='users' ORDER BY ordinal_position\")
    for r in cur.fetchall(): print(r)
conn.close()
"
```
Expected: rows include `('status','NO')`, `('approved_at','YES')`, `('approved_by','YES')`, `('role','YES')`.

- [ ] **Step 4: Commit**

```bash
git add scripts/apply_schema_users_pending.py scripts/user_db.py
git commit -m "feat(auth): schema migration for pending registrations

Adds users.status (pending|active, default active for backward compat),
users.approved_at, users.approved_by. Relaxes role NOT NULL with a
CHECK that only pending rows may have NULL role. Extends user_db
PUBLIC_COLUMNS so GET /api/users returns the new fields."
```

---

## Task 2: `auth_register.py` + tests + public route

**Goal:** Public POST `/api/auth/register` that inserts a pending user.

**Files:**
- Create: `scripts/auth_register.py`
- Create: `tests/test_auth_register.py`
- Modify: `server.js` (add public-bypass entry + new route)

**Acceptance Criteria:**
- [ ] Valid registration inserts a row with `status='pending'`, `role IS NULL`, `created_by IS NULL`, bcrypt-hashed password.
- [ ] Duplicate username OR email returns exit 5 with `code:"conflict"`, `error:"username or email already taken"`.
- [ ] Validation errors (short password, bad username chars, bad email) return exit 3.
- [ ] `/api/auth/register` is added to `isPublicApi` in `server.js` so no session is required.
- [ ] Pure-logic unit tests pass.

**Verify:**
```bash
pytest tests/test_auth_register.py -v
echo '{"username":"new_user","email":"x@y.z","password":"Secret-123"}' | python scripts/auth_register.py
echo '{"username":"new_user","email":"x@y.z","password":"Secret-123"}' | python scripts/auth_register.py   # duplicate
```
Expected: all tests pass; first run prints `{"ok":true,...}`; second prints `{"ok":false,"code":"conflict",...}`.

**Steps:**

- [ ] **Step 1: Write `tests/test_auth_register.py`**

```python
"""Pure-logic unit tests for auth_register validation helpers (delegated to user_db).
The script itself is exercised by smoke_auth.py against a real UAT DB.
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import pytest  # noqa: E402
import user_db  # noqa: E402


@pytest.mark.parametrize("pw", ["", "short", "1234567"])
def test_validate_password_rejects_too_short(pw):
    with pytest.raises(user_db.ValidationError):
        user_db.validate_password(pw)


def test_validate_password_accepts_ok():
    assert user_db.validate_password("Secret-123") == "Secret-123"


def test_registration_payload_path():
    """The registration script reuses user_db validators; sanity-check the chain."""
    user_db.validate_username("new_user")
    user_db.validate_email("new@example.com")
    user_db.validate_password("Secret-123")
```

Run: `pytest tests/test_auth_register.py -v`
Expected: 5 passing (3 parametrized + 2 single).

- [ ] **Step 2: Write `scripts/auth_register.py`**

```python
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
```

- [ ] **Step 3: Add server.js route**

In `server.js`, find the line:
```js
const isPublicApi = req.url === "/api/auth/login" || req.url === "/api/health";
```
Replace with:
```js
const isPublicApi = req.url === "/api/auth/login"
                 || req.url === "/api/auth/register"
                 || req.url === "/api/health";
```

Add the script constant near the other AUTH constants (around line 35):
```js
const AUTH_REGISTER_SCRIPT = resolve(__dirname, "scripts", "auth_register.py");
```

Add the route handler immediately after the `/api/auth/login` block (around line 380):
```js
// ── Auth: register ───────────────────────────────────────────────
if (req.url === "/api/auth/register" && req.method === "POST") {
  const body = await readBody(req);
  const result = await spawnPython(AUTH_REGISTER_SCRIPT, body);
  const status = httpStatusFor(result.code, result.json);
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json");
  res.end(JSON.stringify(result.json));
  return;
}
```

- [ ] **Step 4: Manual smoke against UAT**

```bash
echo '{"username":"smoke_reg_001","email":"smoke001@test.com","password":"Secret-123"}' | python scripts/auth_register.py
echo '{"username":"smoke_reg_001","email":"smoke001@test.com","password":"Secret-123"}' | python scripts/auth_register.py
```
Expected first call: `{"ok":true,"user":{"id":...,"status":"pending","role":null,...}}`
Expected second call: `{"ok":false,"code":"conflict","error":"username or email already taken",...}`

Clean up:
```bash
python -c "
import sys; sys.path.insert(0,'scripts')
import user_db
conn = user_db.connect()
with conn.cursor() as cur: cur.execute(\"DELETE FROM users WHERE username='smoke_reg_001'\")
conn.commit(); conn.close()
"
```

- [ ] **Step 5: Run tests + commit**

```bash
pytest tests/test_auth_register.py -v
```
Expected: 5 passing.

```bash
git add scripts/auth_register.py tests/test_auth_register.py server.js
git commit -m "feat(auth): POST /api/auth/register for self-registration

Public route (no session required). Validates via user_db helpers,
bcrypt-hashes password, inserts row with status='pending' and role=NULL.
Returns 409 on duplicate username/email."
```

---

## Task 3: `auth_login.py` pending-status check

**Goal:** Block pending accounts at login with a distinct, user-facing message.

**Files:**
- Modify: `scripts/auth_login.py`
- Create: `tests/test_auth_login.py`

**Acceptance Criteria:**
- [ ] Pending account + correct password → exit 6 with `{"ok":false,"error":"Account pending admin approval"}`. No `sessions` row created.
- [ ] Pending account + wrong password → exit 6 with existing `"invalid credentials"` message (no oracle).
- [ ] Active account behavior unchanged.

**Verify:**
```bash
pytest tests/test_auth_login.py -v
```
Expected: 3 passing.

**Steps:**

- [ ] **Step 1: Write `tests/test_auth_login.py` with FakeCursor**

```python
"""Behavioural tests for auth_login.py status branching.

Uses a FakeConnection that returns canned rows so we don't need real DB
or bcrypt round-trips. The actual password check is delegated to
user_db.verify_password, which is unit-tested separately.
"""
from __future__ import annotations
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import pytest  # noqa: E402
import user_db  # noqa: E402
import auth_login  # noqa: E402


class FakeCursor:
    def __init__(self, user_row=None):
        self._user_row = user_row
        self.calls = []
        self.description = None

    def execute(self, sql, params=None):
        self.calls.append((sql.strip().split()[0].upper(), params))

    def fetchone(self):
        return self._user_row

    def __enter__(self): return self
    def __exit__(self, *a): pass


class FakeConn:
    def __init__(self, cursor):
        self._cur = cursor
        self.closed = False
    def cursor(self): return self._cur
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def close(self): self.closed = True


def _run(stdin_payload, user_row):
    """Drive auth_login.main() with a fake connection + given user row."""
    cur = FakeCursor(user_row=user_row)
    conn = FakeConn(cur)
    fake_in = io.BytesIO(json.dumps(stdin_payload).encode("utf-8"))
    fake_in.buffer = fake_in  # match sys.stdin.buffer pattern
    out = io.StringIO()
    with patch.object(user_db, "connect", return_value=conn), \
         patch.object(sys, "stdin", fake_in), \
         patch.object(sys, "stdout", out):
        code = auth_login.main()
    return code, json.loads(out.getvalue() or "{}"), cur


def _pending_row():
    pw_hash = user_db.hash_password("CorrectHorse9!")
    # (id, username, email, role, password_hash, status)
    return (1, "pending_user", "p@x.z", None, pw_hash, "pending")


def _active_row():
    pw_hash = user_db.hash_password("CorrectHorse9!")
    return (2, "active_user", "a@x.z", "user", pw_hash, "active")


def test_pending_account_correct_password_returns_pending_message():
    code, body, cur = _run(
        {"username": "pending_user", "password": "CorrectHorse9!"},
        _pending_row(),
    )
    assert code == 6
    assert body == {"ok": False, "error": "Account pending admin approval"}
    # No INSERT INTO sessions should have run
    assert not any(verb == "INSERT" for verb, _ in cur.calls), cur.calls


def test_pending_account_wrong_password_returns_invalid_credentials():
    code, body, cur = _run(
        {"username": "pending_user", "password": "WRONG"},
        _pending_row(),
    )
    assert code == 6
    assert body == {"ok": False, "error": "invalid credentials"}


def test_active_account_correct_password_returns_session():
    # Active path needs INSERT INTO sessions to be observed; the fake
    # cursor doesn't simulate RETURNING, so we just assert the INSERT was
    # attempted (full happy-path is covered by smoke_auth.py).
    cur = FakeCursor(user_row=_active_row())
    # Patch fetchone to return user row first, then (uuid, expiry) for session insert
    fetches = [_active_row(), ("11111111-1111-1111-1111-111111111111", "2099-01-01T00:00:00+00:00")]
    cur.fetchone = lambda: fetches.pop(0)
    conn = FakeConn(cur)
    fake_in = io.BytesIO(json.dumps(
        {"username": "active_user", "password": "CorrectHorse9!"}
    ).encode("utf-8"))
    fake_in.buffer = fake_in
    out = io.StringIO()
    with patch.object(user_db, "connect", return_value=conn), \
         patch.object(sys, "stdin", fake_in), \
         patch.object(sys, "stdout", out):
        code = auth_login.main()
    assert code == 0
    assert any(verb == "INSERT" for verb, _ in cur.calls)
```

- [ ] **Step 2: Modify `scripts/auth_login.py`**

Find the SELECT block (around line 36-44) and update it to also pull `status`, then add a status check after `verify_password`:

```python
                cur.execute(
                    "SELECT id, username, email, role, password_hash, status "
                    "FROM users WHERE LOWER(username) = LOWER(%s)",
                    (username,),
                )
                row = cur.fetchone()
                if row is None or not user_db.verify_password(password, row[4]):
                    print(json.dumps({"ok": False, "error": "invalid credentials"}))
                    return 6
                user_id, u_name, u_email, u_role, _, u_status = row

                if u_status != "active":
                    print(json.dumps({"ok": False, "error": "Account pending admin approval"}))
                    return 6

                cur.execute(
                    "INSERT INTO sessions (user_id, expires_at) "
                    f"VALUES (%s, now() + interval '{SESSION_HOURS} hours') "
                    "RETURNING session_id, expires_at",
                    (user_id,),
                )
```

Order matters: password is checked before the status branch is taken, so a wrong password on a pending account still returns generic "invalid credentials".

- [ ] **Step 3: Run tests + commit**

```bash
pytest tests/test_auth_login.py -v
```
Expected: 3 passing.

```bash
git add scripts/auth_login.py tests/test_auth_login.py
git commit -m "feat(auth): block pending accounts at login with distinct message

After password verification, check users.status. If 'pending', return
exit 6 with 'Account pending admin approval' and never create a session.
Wrong password on a pending account still returns 'invalid credentials'
to avoid leaking account existence."
```

---

## Task 4: `user_approve.py` + tests + admin route

**Goal:** Admin endpoint that flips a pending row to active and assigns the role.

**Files:**
- Create: `scripts/user_approve.py`
- Create: `tests/test_user_approve.py`
- Modify: `server.js` (add admin-gated route)

**Acceptance Criteria:**
- [ ] Approving a pending row sets `status='active'`, `role=<provided>`, `approved_at=NOW()`, `approved_by=<admin username>`.
- [ ] Approving a non-existent ID returns exit 4 (404).
- [ ] Approving an already-active row returns exit 5 with `code:"conflict"`.
- [ ] Invalid role returns exit 3.
- [ ] Non-admin caller hits server.js gate (403) — never reaches Python.

**Verify:**
```bash
pytest tests/test_user_approve.py -v
```
Expected: 4 passing.

**Steps:**

- [ ] **Step 1: Write `tests/test_user_approve.py`**

```python
"""Pure-logic tests for user_approve using FakeCursor."""
from __future__ import annotations
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import pytest  # noqa: E402
import user_db  # noqa: E402
import user_approve  # noqa: E402


class FakeCursor:
    def __init__(self, rowcount=1):
        self.calls = []
        self.rowcount = rowcount
        self.description = None
    def execute(self, sql, params=None):
        self.calls.append((sql, params))
    def fetchone(self):
        return None
    def __enter__(self): return self
    def __exit__(self, *a): pass


class FakeConn:
    def __init__(self, cur): self._c = cur
    def cursor(self): return self._c
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def close(self): pass


def _run(payload, rowcount):
    cur = FakeCursor(rowcount=rowcount)
    conn = FakeConn(cur)
    # For non-zero rowcount path, the script then SELECTs the row — give it back something
    if rowcount > 0:
        cur.fetchone = lambda: (1, "u", "u@x.z", "user", "active", "2026-05-22T00:00:00+00:00", "admin1")
        cur.description = [type("D",(),{"name": n})() for n in
                           ("id","username","email","role","status","approved_at","approved_by")]
    fake_in = io.BytesIO(json.dumps(payload).encode("utf-8"))
    fake_in.buffer = fake_in
    out = io.StringIO()
    with patch.object(user_db, "connect", return_value=conn), \
         patch.object(sys, "stdin", fake_in), \
         patch.object(sys, "stdout", out):
        code = user_approve.main()
    return code, json.loads(out.getvalue() or "{}")


def test_approve_pending_user_returns_ok():
    code, body = _run({"user_id": 1, "role": "user", "_acting_user": "admin1"}, rowcount=1)
    assert code == 0
    assert body["ok"] is True
    assert body["user"]["status"] == "active"


def test_approve_nonexistent_returns_404():
    code, body = _run({"user_id": 999, "role": "user", "_acting_user": "admin1"}, rowcount=0)
    assert code == 4
    assert body["ok"] is False


def test_approve_invalid_role_returns_400():
    code, body = _run({"user_id": 1, "role": "root", "_acting_user": "admin1"}, rowcount=1)
    assert code == 3
    assert "role" in body["error"].lower()


def test_approve_missing_user_id_returns_400():
    code, body = _run({"role": "user", "_acting_user": "admin1"}, rowcount=0)
    assert code == 3
```

- [ ] **Step 2: Write `scripts/user_approve.py`**

```python
"""Admin-only: approve a pending registration and assign a role.

Stdin:  {"user_id": N, "role": "user"|"admin", "_acting_user": "<admin username>"}
Stdout: {"ok": true,  "user": {…}}                                       (exit 0)
        {"ok": false, "error": "..."}                                     (exit 3)
        {"ok": false, "error": "user not found"}                          (exit 4)
        {"ok": false, "code":"conflict", "error":"user already active"}  (exit 5)
Manual smoke:
  echo '{"user_id":1,"role":"user","_acting_user":"peter"}' | python3 scripts/user_approve.py
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

    user_id = payload.get("user_id")
    if not isinstance(user_id, int):
        print(json.dumps({"ok": False, "error": "user_id (int) required"}))
        return 3

    try:
        role = user_db.validate_role(payload.get("role", ""))
    except user_db.ValidationError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 3

    acting = payload.get("_acting_user") or "system"

    conn = None
    try:
        conn = user_db.connect()
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users "
                    "   SET status='active', role=%s, "
                    "       approved_at=now(), approved_by=%s, "
                    "       updated_at=now(), updated_by=%s "
                    " WHERE id=%s AND status='pending'",
                    (role, acting, acting, user_id),
                )
                if cur.rowcount == 0:
                    # Distinguish 404 vs 409: was the row absent, or already active?
                    cur.execute("SELECT status FROM users WHERE id=%s", (user_id,))
                    existing = cur.fetchone()
                    if existing is None:
                        print(json.dumps({"ok": False, "error": "user not found"}))
                        return 4
                    print(json.dumps({
                        "ok": False, "code": "conflict",
                        "error": "user already active",
                    }))
                    return 5
                cur.execute("SELECT * FROM users WHERE id=%s", (user_id,))
                row = user_db.row_to_public(cur, cur.fetchone())
        print(json.dumps({"ok": True, "user": row}))
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Add server.js route**

Add the constant near other USER_* constants (around line 39):
```js
const USER_APPROVE_SCRIPT = resolve(__dirname, "scripts", "user_approve.py");
```

Add the route handler in the admin-section of server.js (near where `/api/users/:id` PATCH/DELETE live — search for `/api/users/` to find the cluster). The route is `POST /api/users/:id/approve`. Match the existing pattern:

```js
// ── Admin: approve pending user ─────────────────────────────────
const approveMatch = req.url && req.url.match(/^\/api\/users\/(\d+)\/approve$/);
if (approveMatch && req.method === "POST") {
  if (!requireAdmin(req, res)) return;
  const userId = parseInt(approveMatch[1], 10);
  const body = await readBody(req);
  let parsed; try { parsed = JSON.parse(body || "{}"); } catch { parsed = {}; }
  parsed.user_id = userId;
  parsed._acting_user = req.sessionUser.username;
  const result = await spawnPython(USER_APPROVE_SCRIPT, JSON.stringify(parsed));
  const status = httpStatusFor(result.code, result.json);
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json");
  res.end(JSON.stringify(result.json));
  return;
}
```

- [ ] **Step 4: Run tests + commit**

```bash
pytest tests/test_user_approve.py -v
```
Expected: 4 passing.

```bash
git add scripts/user_approve.py tests/test_user_approve.py server.js
git commit -m "feat(auth): POST /api/users/:id/approve for admin approval

Admin-only (server.js requireAdmin gate). Flips status pending->active,
assigns role from request body, stamps approved_at/approved_by from
session. Returns 404 if not found, 409 if already active."
```

---

## Task 5: `user_reject.py` + tests + admin route

**Goal:** Admin endpoint that hard-deletes a pending registration.

**Files:**
- Create: `scripts/user_reject.py`
- Create: `tests/test_user_reject.py`
- Modify: `server.js` (add admin-gated route)

**Acceptance Criteria:**
- [ ] Rejecting a pending row deletes it; subsequent SELECT by id returns nothing.
- [ ] Rejecting an active row returns exit 5 with `code:"conflict"`.
- [ ] Rejecting a non-existent ID returns exit 4.

**Verify:**
```bash
pytest tests/test_user_reject.py -v
```
Expected: 3 passing.

**Steps:**

- [ ] **Step 1: Write `tests/test_user_reject.py`**

```python
"""Pure-logic tests for user_reject."""
from __future__ import annotations
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import pytest  # noqa: E402
import user_db  # noqa: E402
import user_reject  # noqa: E402


class FakeCursor:
    def __init__(self, delete_rowcount=1, existing_status=None):
        self.calls = []
        self.rowcount = delete_rowcount
        self._existing_status = existing_status
    def execute(self, sql, params=None):
        self.calls.append((sql, params))
    def fetchone(self):
        return (self._existing_status,) if self._existing_status else None
    def __enter__(self): return self
    def __exit__(self, *a): pass


class FakeConn:
    def __init__(self, cur): self._c = cur
    def cursor(self): return self._c
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def close(self): pass


def _run(payload, delete_rowcount, existing_status=None):
    cur = FakeCursor(delete_rowcount=delete_rowcount, existing_status=existing_status)
    conn = FakeConn(cur)
    fake_in = io.BytesIO(json.dumps(payload).encode("utf-8"))
    fake_in.buffer = fake_in
    out = io.StringIO()
    with patch.object(user_db, "connect", return_value=conn), \
         patch.object(sys, "stdin", fake_in), \
         patch.object(sys, "stdout", out):
        code = user_reject.main()
    return code, json.loads(out.getvalue() or "{}")


def test_reject_pending_deletes_row():
    code, body = _run({"user_id": 1}, delete_rowcount=1)
    assert code == 0
    assert body == {"ok": True}


def test_reject_active_returns_conflict():
    code, body = _run({"user_id": 1}, delete_rowcount=0, existing_status="active")
    assert code == 5
    assert body.get("code") == "conflict"


def test_reject_nonexistent_returns_404():
    code, body = _run({"user_id": 999}, delete_rowcount=0, existing_status=None)
    assert code == 4
```

- [ ] **Step 2: Write `scripts/user_reject.py`**

```python
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
        print(json.dumps({"ok": False, "error": "invalid JSON on stdin", "detail": str(e)}))
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
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Add server.js route**

Constant:
```js
const USER_REJECT_SCRIPT = resolve(__dirname, "scripts", "user_reject.py");
```

Route (adjacent to the approve route):
```js
// ── Admin: reject pending user ──────────────────────────────────
const rejectMatch = req.url && req.url.match(/^\/api\/users\/(\d+)\/reject$/);
if (rejectMatch && req.method === "POST") {
  if (!requireAdmin(req, res)) return;
  const userId = parseInt(rejectMatch[1], 10);
  const result = await spawnPython(USER_REJECT_SCRIPT, JSON.stringify({ user_id: userId }));
  const status = httpStatusFor(result.code, result.json);
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json");
  res.end(JSON.stringify(result.json));
  return;
}
```

- [ ] **Step 4: Run tests + commit**

```bash
pytest tests/test_user_reject.py -v
```
Expected: 3 passing.

```bash
git add scripts/user_reject.py tests/test_user_reject.py server.js
git commit -m "feat(auth): POST /api/users/:id/reject for admin rejection

Admin-only. Hard-deletes a pending row. Refuses to touch active users
(use the existing DELETE endpoint for those)."
```

---

## Task 6: LoginPage show/hide password toggle

**Goal:** Eye icon button inside the password input toggles `type="password"` ↔ `type="text"`.

**Files:**
- Modify: `src/auth/LoginPage.jsx`

**Acceptance Criteria:**
- [ ] Eye icon button appears at the right edge of the password input.
- [ ] Click toggles password visibility; icon switches between Eye and EyeOff.
- [ ] Button has `tabIndex={-1}` so keyboard tab order stays input → SIGN IN button.
- [ ] Visually consistent with existing Bloomberg-terminal styling (no jarring color, sits inside the input border).

**Verify:** Visual inspection in browser. Run `npm run dev`, open login page, click the eye → password shows as plain text.

**Steps:**

- [ ] **Step 1: Update `src/auth/LoginPage.jsx`**

Add `Eye`, `EyeOff` to the imports:
```jsx
import React, { useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import tokkaLogo from "../assets/tokka-labs-logo.png";
import { useAuth } from "./AuthContext.jsx";
```

Add state alongside the existing useState calls:
```jsx
const [showPw, setShowPw] = useState(false);
```

Replace the password `<input>` block (currently a single input) with a wrapper that includes the toggle button:
```jsx
<div style={{ position: "relative" }}>
  <input
    type={showPw ? "text" : "password"}
    value={password}
    onChange={(e) => setPassword(e.target.value)}
    style={{ ...inputStyle, paddingRight: 36 }}
    disabled={pending}
  />
  <button
    type="button"
    tabIndex={-1}
    onClick={() => setShowPw((v) => !v)}
    title={showPw ? "Hide password" : "Show password"}
    style={{
      position: "absolute", right: 6, top: "50%", transform: "translateY(-50%)",
      background: "transparent", border: "none", color: BB.dim, cursor: "pointer",
      padding: 4, display: "flex", alignItems: "center",
    }}
  >
    {showPw ? <EyeOff size={14} /> : <Eye size={14} />}
  </button>
</div>
```

- [ ] **Step 2: Manual smoke**

```bash
npm run dev
```
Open `http://localhost:5173`, click the eye icon next to password — verify text becomes visible, click again — verify it's masked again. Tab through the form: focus should go username → password → SIGN IN button (eye button skipped).

- [ ] **Step 3: Commit**

```bash
git add src/auth/LoginPage.jsx
git commit -m "feat(auth): show/hide password toggle on login form

Adds Eye/EyeOff icon button inside the password input. tabIndex=-1 so
keyboard tab order stays input -> SIGN IN button. Matches Bloomberg-
terminal styling (transparent button, dim color)."
```

---

## Task 7: `RegisterPage.jsx` + `App.jsx` mode toggle + `api.js` register helper

**Goal:** Self-registration form reachable from the login page.

**Files:**
- Create: `src/auth/RegisterPage.jsx`
- Modify: `src/auth/api.js` (add `register()` helper)
- Modify: `src/auth/LoginPage.jsx` (add REQUEST ACCOUNT link, accept `onSwitchToRegister` prop)
- Modify: `src/App.jsx` (mode state when unauthenticated)

**Acceptance Criteria:**
- [ ] Login page shows `REQUEST ACCOUNT →` link below the SIGN IN button. Click switches to RegisterPage.
- [ ] RegisterPage has 4 inputs (USERNAME, EMAIL, PASSWORD, CONFIRM PASSWORD) plus REGISTER button and BACK TO SIGN IN link.
- [ ] Each password field has its own show/hide toggle (independent state).
- [ ] Client-side: REGISTER button disabled when fields empty or passwords don't match.
- [ ] Successful registration → returns to login with banner: `"Account submitted. You'll be notified when an admin approves it."`
- [ ] Server error → inline red message under the form.

**Verify:** `npm run dev`, click REQUEST ACCOUNT, submit a fresh registration → land back on login with banner. Try logging in with the new account → see "Account pending admin approval".

**Steps:**

- [ ] **Step 1: Add `register()` to `src/auth/api.js`**

Append:
```js
export async function register({ username, email, password }) {
  const res = await fetch("/api/auth/register", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, email, password }),
  });
  const body = await res.json().catch(() => ({ ok: false, error: "non-JSON server response" }));
  return { status: res.status, body };
}
```

- [ ] **Step 2: Create `src/auth/RegisterPage.jsx`**

```jsx
import React, { useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import tokkaLogo from "../assets/tokka-labs-logo.png";
import { register } from "./api.js";

const BB = {
  bg: "#000000", fg: "#e5e5e5", dim: "#7d7d7d",
  panel: "#0a0a0a", border: "#1f1f1f",
  accent: "#1f63ea", red: "#FF4D4F",
};

const inputStyle = {
  width: "100%", padding: "8px 10px", background: "#000",
  color: "#e5e5e5", border: "1px solid #1f1f1f", outline: "none",
  fontFamily: "inherit", fontSize: 13,
};

function PasswordInput({ value, onChange, disabled }) {
  const [show, setShow] = useState(false);
  return (
    <div style={{ position: "relative" }}>
      <input
        type={show ? "text" : "password"} value={value} onChange={onChange}
        style={{ ...inputStyle, paddingRight: 36 }} disabled={disabled}
      />
      <button
        type="button" tabIndex={-1} onClick={() => setShow((v) => !v)}
        title={show ? "Hide password" : "Show password"}
        style={{
          position: "absolute", right: 6, top: "50%", transform: "translateY(-50%)",
          background: "transparent", border: "none", color: BB.dim, cursor: "pointer",
          padding: 4, display: "flex", alignItems: "center",
        }}
      >
        {show ? <EyeOff size={14} /> : <Eye size={14} />}
      </button>
    </div>
  );
}

export default function RegisterPage({ onRegistered, onBackToLogin }) {
  const [username, setUsername] = useState("");
  const [email, setEmail]       = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm]   = useState("");
  const [error, setError]       = useState("");
  const [pending, setPending]   = useState(false);

  const passwordsMismatch = confirm.length > 0 && password !== confirm;
  const canSubmit = username && email && password && confirm && !passwordsMismatch && !pending;

  async function submit(e) {
    e.preventDefault();
    setError("");
    if (passwordsMismatch) { setError("passwords do not match"); return; }
    setPending(true);
    const { status, body } = await register({ username: username.trim(), email: email.trim(), password });
    setPending(false);
    if (status === 200 && body?.ok) {
      onRegistered("Account submitted. You'll be notified when an admin approves it.");
      return;
    }
    setError(body?.error || `HTTP ${status}`);
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
          <div style={{ fontSize: 13, color: BB.dim, letterSpacing: 1.2 }}>REQUEST ACCOUNT</div>
        </div>

        <label style={{ display: "block", fontSize: 11, color: BB.dim, marginBottom: 4 }}>USERNAME</label>
        <input autoFocus value={username} onChange={(e) => setUsername(e.target.value)}
               style={inputStyle} disabled={pending} />

        <label style={{ display: "block", fontSize: 11, color: BB.dim, marginBottom: 4, marginTop: 16 }}>EMAIL</label>
        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
               style={inputStyle} disabled={pending} />

        <label style={{ display: "block", fontSize: 11, color: BB.dim, marginBottom: 4, marginTop: 16 }}>PASSWORD</label>
        <PasswordInput value={password} onChange={(e) => setPassword(e.target.value)} disabled={pending} />

        <label style={{ display: "block", fontSize: 11, color: BB.dim, marginBottom: 4, marginTop: 16 }}>CONFIRM PASSWORD</label>
        <PasswordInput value={confirm} onChange={(e) => setConfirm(e.target.value)} disabled={pending} />

        {passwordsMismatch && (
          <div style={{ marginTop: 8, color: BB.red, fontSize: 11 }}>passwords do not match</div>
        )}
        {error && (
          <div style={{ marginTop: 14, color: BB.red, fontSize: 12 }}>{error}</div>
        )}

        <button type="submit" disabled={!canSubmit} style={{
          width: "100%", marginTop: 20, padding: "10px 16px",
          background: BB.accent, color: BB.bg, border: "none",
          fontFamily: "inherit", fontSize: 13, fontWeight: 600, letterSpacing: 1,
          cursor: canSubmit ? "pointer" : "not-allowed", opacity: canSubmit ? 1 : 0.5,
        }}>
          {pending ? "SUBMITTING…" : "REQUEST ACCOUNT"}
        </button>

        <button type="button" onClick={onBackToLogin} disabled={pending} style={{
          width: "100%", marginTop: 10, padding: "8px 16px",
          background: "transparent", color: BB.dim, border: "none",
          fontFamily: "inherit", fontSize: 11, letterSpacing: 1.5, cursor: "pointer",
        }}>
          ← BACK TO SIGN IN
        </button>
      </form>
    </div>
  );
}
```

- [ ] **Step 3: Add `REQUEST ACCOUNT` link to `LoginPage.jsx`**

After the SIGN IN button, add:
```jsx
{onSwitchToRegister && (
  <button type="button" onClick={onSwitchToRegister} disabled={pending} style={{
    width: "100%", marginTop: 10, padding: "8px 16px",
    background: "transparent", color: BB.dim, border: "none",
    fontFamily: "inherit", fontSize: 11, letterSpacing: 1.5, cursor: "pointer",
  }}>
    REQUEST ACCOUNT →
  </button>
)}
```

Update the component signature to accept the prop:
```jsx
export default function LoginPage({ banner, onSwitchToRegister }) {
```

- [ ] **Step 4: Wire up mode toggle in `src/App.jsx`**

Find the existing unauthenticated branch (returns `<LoginPage ...>`) and wrap with mode state. Likely shape (adapt to actual file):

```jsx
import RegisterPage from "./auth/RegisterPage.jsx";

// ... inside App component, when not authenticated:
const [mode, setMode]     = useState("login");
const [banner, setBanner] = useState("");

if (!user) {
  if (mode === "register") {
    return (
      <RegisterPage
        onBackToLogin={() => setMode("login")}
        onRegistered={(msg) => { setBanner(msg); setMode("login"); }}
      />
    );
  }
  return (
    <LoginPage
      banner={banner}
      onSwitchToRegister={() => { setBanner(""); setMode("register"); }}
    />
  );
}
```

(Read the existing App.jsx first; merge into whatever shape it already uses for the unauthenticated branch.)

- [ ] **Step 5: Manual smoke**

```bash
npm run dev
```
1. Open `http://localhost:5173`.
2. Click REQUEST ACCOUNT.
3. Submit: `register_smoke_001` / `smoke001@x.z` / `Secret-123` (twice).
4. Land back on login with the success banner.
5. Try logging in with the new account → see "Account pending admin approval".

Clean up:
```bash
python -c "
import sys; sys.path.insert(0,'scripts')
import user_db
conn = user_db.connect()
with conn.cursor() as cur: cur.execute(\"DELETE FROM users WHERE username='register_smoke_001'\")
conn.commit(); conn.close()
"
```

- [ ] **Step 6: Commit**

```bash
git add src/auth/RegisterPage.jsx src/auth/api.js src/auth/LoginPage.jsx src/App.jsx
git commit -m "feat(auth): RegisterPage with show/hide password toggles

Adds public registration UI reachable via REQUEST ACCOUNT link on the
login form. Independent show/hide toggles on PASSWORD and CONFIRM
PASSWORD. On success, returns to LoginPage with a banner message.
App.jsx gains a mode state to switch between the two when unauthenticated."
```

---

## Task 8: UserAdmin ACTIVE/PENDING tabs + actions + APPROVED BY column + polling

**Goal:** Single management surface where admin can see pending rows and approve/reject them.

**Files:**
- Modify: `src/admin/UserAdmin.jsx`

**Acceptance Criteria:**
- [ ] Tab strip at top: `ACTIVE (N)` | `PENDING (N)`. Active tab has an underline. Pending count badge in tokka orange when N > 0.
- [ ] ACTIVE tab shows existing table with a new APPROVED BY column (blank for `approved_by IS NULL` rows).
- [ ] PENDING tab shows: username, email, submitted at, three buttons per row — `APPROVE AS USER`, `APPROVE AS ADMIN`, `REJECT` (red).
- [ ] Clicking any action POSTs the right endpoint and refreshes the list optimistically.
- [ ] 30-second polling of `GET /api/users` while the component is mounted.

**Verify:** With a pending row in the DB, open USER ADMIN → see PENDING tab badge "1" → click APPROVE AS USER → row moves to ACTIVE tab with APPROVED BY=<your username>.

**Steps:**

- [ ] **Step 1: Update `src/admin/UserAdmin.jsx`**

Read the current file to find the right insertion points. Then:

Add state at top of component:
```jsx
const [tab, setTab] = useState("active");  // "active" | "pending"
```

Replace the table-data line `setRows(body.rows)` so polling still works. Then add polling effect alongside the existing `useEffect(() => { load(); }, []);`:
```jsx
useEffect(() => {
  const id = setInterval(load, 30000);
  return () => clearInterval(id);
}, []);
```

Compute partitions and counts in render:
```jsx
const active  = useMemo(() => rows.filter((r) => r.status === "active"),  [rows]);
const pending = useMemo(() => rows.filter((r) => r.status === "pending"), [rows]);
const visible = tab === "pending" ? pending : active;
```

Insert tab strip below the header bar, above the `error` block:
```jsx
<div style={{ display: "flex", gap: 24, padding: "12px 24px", borderBottom: `1px solid ${BB.border}` }}>
  {[["active", "ACTIVE", active.length], ["pending", "PENDING", pending.length]].map(([key, label, count]) => {
    const isActive = tab === key;
    return (
      <button key={key} onClick={() => setTab(key)} style={{
        background: "transparent", border: "none", color: isActive ? BB.fg : BB.dim,
        fontFamily: "inherit", fontSize: 11, letterSpacing: 1.5, padding: "4px 0",
        borderBottom: isActive ? `2px solid ${BB.accent}` : "2px solid transparent",
        cursor: "pointer", display: "flex", alignItems: "center", gap: 8,
      }}>
        {label}
        {count > 0 && (
          <span style={{
            background: key === "pending" ? BB.accent : BB.border,
            color: key === "pending" ? BB.bg : BB.fg,
            padding: "1px 6px", fontSize: 10, fontWeight: 600,
          }}>{count}</span>
        )}
      </button>
    );
  })}
</div>
```

Change the table body to render the active OR pending shape:
```jsx
{tab === "pending" ? (
  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
    <thead>
      <tr style={{ textAlign: "left", color: BB.dim, fontSize: 11, letterSpacing: 1 }}>
        <th style={td}>USERNAME</th>
        <th style={td}>EMAIL</th>
        <th style={td}>SUBMITTED AT</th>
        <th style={td}>ACTIONS</th>
      </tr>
    </thead>
    <tbody>
      {visible.map((u) => (
        <tr key={u.id}>
          <td style={td}>{u.username}</td>
          <td style={td}>{u.email}</td>
          <td style={td}>{fmtDate(u.created_at)}</td>
          <td style={td}>
            <div style={{ display: "flex", gap: 8 }}>
              <button style={ghostBtn} onClick={() => onApprove(u, "user")}>APPROVE AS USER</button>
              <button style={primaryBtn} onClick={() => onApprove(u, "admin")}>APPROVE AS ADMIN</button>
              <button style={{ ...ghostBtn, color: BB.red, borderColor: BB.red }}
                      onClick={() => onReject(u)}>REJECT</button>
            </div>
          </td>
        </tr>
      ))}
      {visible.length === 0 && (
        <tr><td style={td} colSpan={4}><div style={{ color: BB.dim, fontStyle: "italic" }}>No pending registrations.</div></td></tr>
      )}
    </tbody>
  </table>
) : (
  // existing active-users table — add an APPROVED BY column between role and created_at
  // ...
)}
```

Add the two action handlers:
```jsx
async function onApprove(user, role) {
  if (!confirm(`Approve ${user.username} as ${role.toUpperCase()}?`)) return;
  const { status, body } = await apiJson(`/api/users/${user.id}/approve`, {
    method: "POST", body: JSON.stringify({ role }),
  });
  if (status !== 200 || !body?.ok) {
    setError(body?.error || `Approve failed (${status})`);
    return;
  }
  await load();
}

async function onReject(user) {
  if (!confirm(`Reject ${user.username}? This deletes their request.`)) return;
  const { status, body } = await apiJson(`/api/users/${user.id}/reject`, { method: "POST" });
  if (status !== 200 || !body?.ok) {
    setError(body?.error || `Reject failed (${status})`);
    return;
  }
  await load();
}
```

Add APPROVED BY column to the existing active-users `<thead>` and `<tbody>` (find the existing column list — insert between ROLE and CREATED AT):
```jsx
<th style={td}>APPROVED BY</th>
// ...
<td style={td}>{u.approved_by || ""}</td>
```

- [ ] **Step 2: Manual smoke**

```bash
npm run dev
```
1. Log in as admin.
2. Open USER ADMIN. Tab strip visible.
3. Trigger a registration via the React register flow (or `echo … | python scripts/auth_register.py`).
4. Wait ≤30s OR click ACTIVE→PENDING. Pending tab badge shows `1`.
5. Click `APPROVE AS USER` → confirm → row vanishes from PENDING, appears in ACTIVE with APPROVED BY=<your username>.
6. Trigger another registration → click REJECT → row vanishes.
7. Active tab APPROVED BY column populated for newly approved users; blank for bootstrap admins.

- [ ] **Step 3: Commit**

```bash
git add src/admin/UserAdmin.jsx
git commit -m "feat(auth): pending-registration tab + inline approve/reject in UserAdmin

Adds ACTIVE/PENDING tab strip with counts (orange badge on PENDING when
non-zero). PENDING table has three per-row actions: APPROVE AS USER,
APPROVE AS ADMIN, REJECT. ACTIVE table gains APPROVED BY column. The
component now polls GET /api/users every 30s so the badge stays fresh."
```

---

## Task 9: `smoke_auth.py --register` E2E mode

**Goal:** One command that exercises register → pending-login → approve → login → reject against UAT.

**Files:**
- Modify: `scripts/smoke_auth.py`

**Acceptance Criteria:**
- [ ] `python scripts/smoke_auth.py --register --admin-username X --admin-password Y` prints `PASS` after exercising the full flow.
- [ ] On failure, prints which step failed and the response body.
- [ ] Uses a randomized username so it's safe to re-run.

**Verify:**
```bash
python scripts/smoke_auth.py --register --admin-username peter --admin-password '<…>'
```
Expected: ends with `PASS`.

**Steps:**

- [ ] **Step 1: Read existing `scripts/smoke_auth.py`**

```bash
cat scripts/smoke_auth.py
```
Identify the existing argparse setup + the HTTP helper functions used. Match their style.

- [ ] **Step 2: Add `--register` mode**

Add to argparse:
```python
p.add_argument("--register", action="store_true",
               help="Exercise register -> pending-login -> approve -> login -> reject flow")
p.add_argument("--admin-username", help="(register mode) admin used to approve/reject")
p.add_argument("--admin-password", help="(register mode) admin password for approval session")
```

Add the flow at the bottom of `main()` after the existing `--username/--password` smoke (or as a separate branch — whatever shape the script uses today):

```python
if args.register:
    import random, string
    uname = "smoke_reg_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    email = f"{uname}@smoke.test"
    pw    = "Secret-12345"

    def post(path, body=None, cookies=None):
        import urllib.request, urllib.error
        data = json.dumps(body or {}).encode("utf-8")
        req = urllib.request.Request(
            f"{args.base_url}{path}", data=data, method="POST",
            headers={"Content-Type": "application/json",
                     **({"Cookie": cookies} if cookies else {})},
        )
        try:
            resp = urllib.request.urlopen(req)
            return resp.getcode(), json.loads(resp.read() or b"{}"), resp.headers.get("Set-Cookie", "")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}"), ""

    def fail(msg, *extra):
        print(f"FAIL: {msg}", *extra)
        sys.exit(1)

    print(f"[1/6] register {uname}")
    code, body, _ = post("/api/auth/register",
                         {"username": uname, "email": email, "password": pw})
    if code != 200 or not body.get("ok"):
        fail("register did not return 200/ok", code, body)
    user_id = body["user"]["id"]

    print("[2/6] login while pending (expect 401)")
    code, body, _ = post("/api/auth/login", {"username": uname, "password": pw})
    if code != 401 or "pending" not in body.get("error", "").lower():
        fail("expected 401 'Account pending admin approval'", code, body)

    print("[3/6] admin login")
    code, body, set_cookie = post("/api/auth/login",
                                  {"username": args.admin_username,
                                   "password": args.admin_password})
    if code != 200 or not set_cookie:
        fail("admin login failed", code, body)
    admin_cookie = set_cookie.split(";", 1)[0]

    print(f"[4/6] approve user_id={user_id} as 'user'")
    code, body, _ = post(f"/api/users/{user_id}/approve",
                         {"role": "user"}, cookies=admin_cookie)
    if code != 200 or not body.get("ok"):
        fail("approve failed", code, body)

    print("[5/6] login after approval (expect 200)")
    code, body, _ = post("/api/auth/login", {"username": uname, "password": pw})
    if code != 200 or not body.get("ok"):
        fail("post-approval login failed", code, body)

    print(f"[6/6] reject path — register fresh, then reject")
    uname2 = uname + "_b"
    code, body, _ = post("/api/auth/register",
                         {"username": uname2, "email": f"{uname2}@smoke.test", "password": pw})
    if code != 200: fail("second register failed", code, body)
    uid2 = body["user"]["id"]
    code, body, _ = post(f"/api/users/{uid2}/reject", cookies=admin_cookie)
    if code != 200 or not body.get("ok"):
        fail("reject failed", code, body)
    code, body, _ = post("/api/auth/login", {"username": uname2, "password": pw})
    if code != 401 or "invalid" not in body.get("error", "").lower():
        fail("post-reject login should be 'invalid credentials'", code, body)

    print("PASS")
    return 0
```

- [ ] **Step 3: Run against local server**

```bash
node server.js &   # in another shell
sleep 2
python scripts/smoke_auth.py --register \
  --admin-username peter --admin-password '<your local admin pw>' \
  --base-url http://localhost:5181
```
Expected: ends with `PASS`. Manually clean up the approved-then-orphaned user if needed (`DELETE FROM users WHERE username LIKE 'smoke_reg_%'`).

- [ ] **Step 4: Commit**

```bash
git add scripts/smoke_auth.py
git commit -m "test(auth): add --register E2E mode to smoke_auth.py

Exercises the full flow: register -> pending-login (expect 401) ->
admin login -> approve -> login (expect 200) -> register second ->
reject -> login (expect 401 invalid credentials). Used in CI / pre-push."
```

---

## Task 10: README + version bump + deploy

**Goal:** Document the new flow and ship the image.

**Files:**
- Modify: `README.md`
- Modify: `helm/Chart.yaml`, `version.yml` (via `update_version.py`)

**Acceptance Criteria:**
- [ ] README has a "Self-registration" subsection under the existing "Auth" section.
- [ ] Version bumped via the documented script.
- [ ] CI build succeeds; new image rolls out; UAT login + register flow works.

**Verify:**
```bash
python scripts/update_version.py
git log -1 --stat   # confirm bump
git push origin main
# wait for Bitbucket Pipelines green
kubectl rollout status deployment trade-booking-server-uat -n <ns>
# then on UAT: open login page, click REQUEST ACCOUNT, register, log in
```

**Steps:**

- [ ] **Step 1: Update README**

Find the existing "Auth" section and append:

```markdown
### Self-registration & approval

Users without an account can request one from the login page:

1. Click `REQUEST ACCOUNT →` on the login form.
2. Enter username / email / password (twice).
3. Submit. The account lands in a pending queue — no login until approval.

Admins approve from `USER ADMIN`:

1. Click the `PENDING (N)` tab.
2. Pick `APPROVE AS USER` or `APPROVE AS ADMIN` per row (assigns the role at approval time).
3. Or `REJECT` to delete the request (user can re-register).

Pending users hitting the login form get `"Account pending admin approval"`. Wrong-password attempts return generic `"invalid credentials"` regardless of status — no account-existence oracle.

Admin bootstrap (unchanged): `python scripts/user_create.py --username X --email Y --role admin` creates an immediately-active admin and skips the approval flow.
```

- [ ] **Step 2: Bump version**

```bash
python scripts/update_version.py
git diff helm/Chart.yaml version.yml
```
Expected: `version` and `appVersion` in `helm/Chart.yaml` each go up one patch; `version.yml` ticks too.

- [ ] **Step 3: Commit the docs + bump (separately)**

```bash
git add README.md
git commit -m "docs(auth): document self-registration and admin approval flow"

git add helm/Chart.yaml version.yml
# substitute the current numbers
git commit -m "chore: bump version 0.0.X -> 0.0.Y"
```

- [ ] **Step 4: Push and verify deploy**

```bash
git push origin main
```

Wait for CI green, then check rollout:
```bash
kubectl rollout status deployment trade-booking-server-uat -n <ns>
kubectl get pods -l app=trade-booking-server-uat -o jsonpath='{.items[*].spec.containers[*].image}'
```

Run the schema migration once against UAT:
```bash
# inside the pod, OR from a local shell with UAT creds:
python scripts/apply_schema_users_pending.py
```

- [ ] **Step 5: Final UAT smoke**

```bash
python scripts/smoke_auth.py --register \
  --admin-username <your admin> --admin-password '<…>' \
  --base-url https://<uat host>
```
Expected: `PASS`.

Verify in browser: open login page, REQUEST ACCOUNT works end-to-end, approval reflected in USER ADMIN, pending message correct.

---

## Self-review

**Spec coverage:**
- §3 Schema → Task 1 ✓
- §4 Backend (register/approve/reject + login mod + GET /api/users) → Tasks 2, 3, 4, 5 + Task 1 ✓
- §5 Frontend (LoginPage toggle, RegisterPage, UserAdmin tabs + APPROVED BY + polling) → Tasks 6, 7, 8 ✓
- §6 Error handling → covered in each task's acceptance criteria + script exit-code branches
- §7 Security → public-bypass list (Task 2), admin gate (Tasks 4, 5), password-before-status check (Task 3), bcrypt at register (Task 2)
- §8 Testing → pytest per script (Tasks 2, 3, 4, 5), E2E smoke (Task 9)
- §9 Migration + rollout → Tasks 1, 10
- §10 Files changed → all covered

**Placeholder scan:** No `TBD` / `TODO` / "appropriate error handling" patterns. Every step has either an exact code block, an exact command, or an exact file-path edit.

**Type / name consistency:**
- `_acting_user` (not `acting_user`) used consistently — matches existing `user_create.py` pattern.
- `user_db.PUBLIC_COLUMNS` extended in Task 1; consumed in Tasks 4, 5 via `row_to_public()` (no rename).
- Exit codes 0/3/4/5/6 match `httpStatusFor` in `server.js` — cross-checked Tasks 2, 3, 4, 5.
- `requireAdmin(req, res)` — existing helper used in Tasks 4, 5; signature matches `server.js:285`.
- `apiJson(path, options)` — existing helper used in Task 8; signature matches `UserAdmin.jsx` existing calls.

No issues found.
