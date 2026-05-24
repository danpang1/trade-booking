# Claude Code Trade Booking — Phase 0: Tokens & Bearer Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a personal-token system to the trade booking app so external clients (e.g. Claude Code) can authenticate via `Authorization: Bearer <token>`. The system ships standalone — even before any Claude Code work — because it's useful for any future automation.

**Architecture:** New `api_tokens` table; six new Python scripts (`token_db.py`, `token_create.py`, `token_list.py`, `token_revoke.py`, `auth_whoami_bearer.py`, plus a schema migration); `server.js` auth middleware extended to accept either the existing `sid` cookie OR a `Bearer` header; three new endpoints (`POST /api/tokens`, `GET /api/tokens`, `DELETE /api/tokens/:id`); two new React components (`<ApiTokens>` page + `<TokenGenerateModal>`); user-menu link from the header into the new page; end-to-end smoke script.

**Tech Stack:** Postgres (`MO_DB_UAT`), Python 3.10+ with `psycopg2`, Node.js HTTP server (no framework), React 19 + Vite, `bcrypt` (existing), `secrets`/`hashlib` (stdlib).

**Reference:** [Design doc](../design/2026-05-23-claude-code-trade-booking-design.md). This plan implements **Section 4.2 (api_tokens table)**, **Section 5.1 (auth middleware)**, **Section 5.2 (token endpoints)**, and **Section 6.2 (Tokens settings page)** of the spec.

---

## File Structure

**Created (8):**
- `scripts/apply_schema_api_tokens.py` — idempotent DDL applier, parallels `apply_schema_users.py`
- `scripts/token_db.py` — pure logic (token gen/hash/validation) + connect helper
- `scripts/token_create.py` — POST handler; returns plaintext **once**
- `scripts/token_list.py` — GET handler; returns user's tokens (never plaintext)
- `scripts/token_revoke.py` — DELETE handler; soft-revoke by setting `revoked_at`
- `scripts/auth_whoami_bearer.py` — resolves Bearer plaintext → user (mirrors `auth_whoami.py` for `sid`)
- `scripts/smoke_tokens.py` — end-to-end smoke (create → list → use → revoke → 401)
- `tests/test_token_db.py` — pytest unit tests for `token_db.py` pure-logic functions

**Created (2 React):**
- `src/settings/ApiTokens.jsx` — token list page, mirrors `UserAdmin.jsx` style
- `src/settings/TokenGenerateModal.jsx` — the two-step modal (form → one-shot plaintext reveal)

**Modified (3):**
- `server.js` — extend `resolveSession` to fall through to Bearer; add `/api/tokens` route handlers; add an `AUTH_WHOAMI_BEARER_SCRIPT` constant
- `src/auth/api.js` — add `listTokens`, `createToken`, `revokeToken` helpers
- `src/TradeBookingForm.jsx` — add import, new `appView === "tokens"` mount, and `API Tokens` sidebar nav link (all-users, outside the admin gate)

**Untouched (explicitly):**
- `src/TradeBookingForm.jsx` body (only the header area might gain a menu link; the form itself is unchanged)
- `trades_spot`, `trades_cashflow`, `users`, `sessions` tables — zero changes
- Existing `spot_*.py`, `cashflow_*.py`, `loan_*.py`, `auth_*.py` scripts — zero changes (we add `auth_whoami_bearer.py` as a new sibling of `auth_whoami.py`)

---

## Task 1: Schema migration for `api_tokens`

**Files:**
- Create: `scripts/apply_schema_api_tokens.py`

- [ ] **Step 1: Create the schema applier**

Pattern lifted from `scripts/apply_schema_users.py` — reuse `cashflow_db.connect()`, run DDL with `CREATE TABLE IF NOT EXISTS` so it's idempotent.

Write `scripts/apply_schema_api_tokens.py`:

```python
"""Create `api_tokens` table. Idempotent."""
from __future__ import annotations
import cashflow_db

DDL = """
CREATE TABLE IF NOT EXISTS api_tokens (
  id            SERIAL          PRIMARY KEY,
  user_id       INTEGER         NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash    VARCHAR(64)     NOT NULL UNIQUE,
  token_prefix  VARCHAR(16)     NOT NULL,
  name          VARCHAR(64)     NOT NULL,
  created_at    TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
  last_used_at  TIMESTAMPTZ,
  expires_at    TIMESTAMPTZ     NOT NULL,
  revoked_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS api_tokens_user_idx
  ON api_tokens (user_id) WHERE revoked_at IS NULL;

CREATE INDEX IF NOT EXISTS api_tokens_lookup_idx
  ON api_tokens (token_hash) WHERE revoked_at IS NULL;
"""


def main() -> None:
    conn = cashflow_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(DDL)
        print("ok: api_tokens table ready")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
```

Note: the lookup index excludes `expires_at` from the WHERE clause because `NOW()` isn't immutable in partial-index predicates. Expiry filtering happens at SELECT time (cheap; the partial index already filters out revoked rows).

- [ ] **Step 2: Apply against UAT**

Run: `python scripts/apply_schema_api_tokens.py`
Expected output: `ok: api_tokens table ready`

- [ ] **Step 3: Verify the table exists**

Run:
```bash
python -c "
import sys; sys.path.insert(0, 'scripts')
import cashflow_db
conn = cashflow_db.connect()
with conn.cursor() as cur:
    cur.execute(\"SELECT column_name FROM information_schema.columns WHERE table_name='api_tokens' ORDER BY ordinal_position\")
    print([r[0] for r in cur.fetchall()])
"
```
Expected: `['id', 'user_id', 'token_hash', 'token_prefix', 'name', 'created_at', 'last_used_at', 'expires_at', 'revoked_at']`

- [ ] **Step 4: Commit**

```bash
git add scripts/apply_schema_api_tokens.py
git commit -m "feat(tokens): add api_tokens schema for Bearer auth"
```

---

## Task 2: `token_db.py` — pure logic + helpers (TDD)

**Files:**
- Create: `scripts/token_db.py`
- Test: `tests/test_token_db.py`

`token_db.py` contains the pure-logic functions (token generation, hashing, validation) and DB-touching helpers. Tests cover only the pure logic, no DB.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_token_db.py`:

```python
"""Pure-logic unit tests for token_db. No DB connection required."""
import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import pytest  # noqa: E402  (must follow sys.path.insert above)
import token_db  # noqa: E402


# ── Token generation ──────────────────────────────────────────────

def test_generate_token_format():
    """Plaintext is 'tkmo_' + url-safe random; total length matches spec."""
    t = token_db.generate_token()
    assert t.startswith("tkmo_")
    # url-safe base64 of 32 bytes is 43 chars (no padding). + 5 char prefix = 48.
    assert len(t) == 48
    # url-safe: only [A-Za-z0-9_-]
    assert re.match(r"^tkmo_[A-Za-z0-9_-]+$", t)


def test_generate_token_uniqueness():
    """Two consecutive generations differ (sanity check on randomness)."""
    a = token_db.generate_token()
    b = token_db.generate_token()
    assert a != b


def test_hash_token_is_sha256_hex():
    """Hash is lowercase hex sha256 of the plaintext (64 chars)."""
    t = "tkmo_test_fixed_value_for_hashing_xxxxxxxxxxxxxxx"
    h = token_db.hash_token(t)
    assert len(h) == 64
    assert re.match(r"^[0-9a-f]{64}$", h)
    # Deterministic
    assert token_db.hash_token(t) == h


def test_token_prefix_first_16_chars():
    """The stored 'prefix' is the first 16 chars of plaintext (5 of prefix + 11 random)."""
    t = "tkmo_abcdefghijk_unused_tail"
    assert token_db.token_prefix(t) == "tkmo_abcdefghijk"
    assert len(token_db.token_prefix(t)) == 16


# ── Validators ────────────────────────────────────────────────────

@pytest.mark.parametrize("s", ["My Laptop", "alice's-iPad", "ci_runner_01"])
def test_validate_name_accepts(s):
    assert token_db.validate_name(s) == s


@pytest.mark.parametrize("s", ["", " ", "x" * 65, None])
def test_validate_name_rejects(s):
    with pytest.raises(token_db.ValidationError):
        token_db.validate_name(s)


@pytest.mark.parametrize("d", [30, 90, 365])
def test_validate_expires_in_days_accepts_allowed(d):
    assert token_db.validate_expires_in_days(d) == d


@pytest.mark.parametrize("d", [0, -1, 7, 31, 366, "90", None])
def test_validate_expires_in_days_rejects_others(d):
    with pytest.raises(token_db.ValidationError):
        token_db.validate_expires_in_days(d)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_token_db.py -v`
Expected: All tests FAIL with `ModuleNotFoundError: No module named 'token_db'`

- [ ] **Step 3: Implement `token_db.py`**

Create `scripts/token_db.py`:

```python
"""Shared helper for token_*/auth_whoami_bearer scripts.

Pure-logic functions (generate_token, hash_token, validators) live here
and are exercised by tests/test_token_db.py without touching the DB.
DB-touching functions reuse cashflow_db.connect.
"""
from __future__ import annotations
import hashlib
import secrets

import cashflow_db  # reuse Postgres creds + connect


# ── Pure logic ────────────────────────────────────────────────────

TOKEN_PREFIX_STR = "tkmo_"
TOKEN_RANDOM_BYTES = 32      # → 43-char url-safe base64 string
TOKEN_TOTAL_LEN = 5 + 43     # "tkmo_" + 43 random chars
TOKEN_PREFIX_LEN = 16        # what we store/display
MAX_NAME_LEN = 64
ALLOWED_EXPIRES_DAYS = (30, 90, 365)


class ValidationError(ValueError):
    """Raised by validate_* helpers; caught in main() and rendered as JSON."""


def generate_token() -> str:
    """Generate a new plaintext token: 'tkmo_' + 43 url-safe random chars."""
    return TOKEN_PREFIX_STR + secrets.token_urlsafe(TOKEN_RANDOM_BYTES)


def hash_token(plaintext: str) -> str:
    """sha256 hex of the plaintext. 64 chars."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def token_prefix(plaintext: str) -> str:
    """First 16 chars of plaintext — displayed to users to identify the token."""
    return plaintext[:TOKEN_PREFIX_LEN]


def validate_name(s) -> str:
    if not isinstance(s, str):
        raise ValidationError("name must be a string")
    s2 = s.strip()
    if not s2:
        raise ValidationError("name must be non-empty")
    if len(s2) > MAX_NAME_LEN:
        raise ValidationError(f"name must be <= {MAX_NAME_LEN} chars")
    return s2


def validate_expires_in_days(d) -> int:
    if not isinstance(d, int) or isinstance(d, bool):
        raise ValidationError(f"expires_in_days must be int in {ALLOWED_EXPIRES_DAYS}")
    if d not in ALLOWED_EXPIRES_DAYS:
        raise ValidationError(f"expires_in_days must be one of {ALLOWED_EXPIRES_DAYS}")
    return d


# ── DB-touching ───────────────────────────────────────────────────

def connect():
    """Reuse the MO_DB_UAT connection used by cashflow scripts."""
    return cashflow_db.connect()


# Columns returned to the API consumer. token_hash NEVER appears here.
PUBLIC_COLUMNS = (
    "id", "token_prefix", "name",
    "created_at", "last_used_at", "expires_at", "revoked_at",
)


def row_to_public(cur, row) -> dict:
    """Map a SELECT-* row to the public payload (omits token_hash)."""
    cols = [d.name for d in cur.description]
    out = {c: v for c, v in zip(cols, row) if c in PUBLIC_COLUMNS}
    for k in ("created_at", "last_used_at", "expires_at", "revoked_at"):
        if out.get(k) is not None:
            out[k] = out[k].isoformat()
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_token_db.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Lint**

Run: `flake8 --max-line-length=88 --ignore=E203,W503,E501,F841,F401,E722,F541,F811,E262,C901 scripts/token_db.py tests/test_token_db.py`
Expected: no output (clean).

- [ ] **Step 6: Commit**

```bash
git add scripts/token_db.py tests/test_token_db.py
git commit -m "feat(tokens): add token_db pure-logic + tests"
```

---

## Task 3: `token_create.py` — create a token

**Files:**
- Create: `scripts/token_create.py`

This script handles `POST /api/tokens`. Stdin contains `{name, expires_in_days, _acting_user}` where `_acting_user` is stamped by the server from `req.sessionUser.username`. The plaintext token is returned in the response payload **once** — never stored.

- [ ] **Step 1: Write the script**

Create `scripts/token_create.py`:

```python
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
```

- [ ] **Step 2: Smoke test manually**

```bash
echo '{"name":"smoke-test","expires_in_days":30,"_acting_user":"<your_username>"}' \
  | python scripts/token_create.py
```
Expected: JSON with `"ok": true`, a `"token"` starting with `tkmo_`, and a `"row"` containing `id`, `token_prefix`, `name`, `created_at`, etc. **Copy the token** — you'll need it for later smoke tests.

Verify in DB:
```bash
python -c "
import sys; sys.path.insert(0, 'scripts')
import token_db
conn = token_db.connect()
with conn.cursor() as cur:
    cur.execute('SELECT token_prefix, name, expires_at FROM api_tokens ORDER BY id DESC LIMIT 1')
    print(cur.fetchone())
"
```

- [ ] **Step 3: Test validation paths**

```bash
echo '{"name":"","expires_in_days":90,"_acting_user":"alice"}' \
  | python scripts/token_create.py
```
Expected: `{"ok": false, "error": "name must be non-empty"}` and exit code 3.

```bash
echo '{"name":"x","expires_in_days":7,"_acting_user":"alice"}' \
  | python scripts/token_create.py
```
Expected: `{"ok": false, "error": "expires_in_days must be one of (30, 90, 365)"}` and exit code 3.

- [ ] **Step 4: Commit**

```bash
git add scripts/token_create.py
git commit -m "feat(tokens): add token_create endpoint script"
```

---

## Task 4: `token_list.py` — list user's tokens

**Files:**
- Create: `scripts/token_list.py`

- [ ] **Step 1: Write the script**

Create `scripts/token_list.py`:

```python
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
        print(json.dumps({"ok": False, "error": "invalid JSON on stdin", "detail": str(e)}))
        return 2

    acting = payload.get("_acting_user")
    if not isinstance(acting, str) or not acting:
        print(json.dumps({"ok": False, "error": "missing _acting_user (server bug)"}))
        return 3

    try:
        tokens = _list(acting)
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5

    print(json.dumps({"ok": True, "tokens": tokens}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke test**

```bash
echo '{"_acting_user":"<your_username>"}' | python scripts/token_list.py
```
Expected: `{"ok": true, "tokens": [{...}]}` showing the token created in Task 3.

- [ ] **Step 3: Commit**

```bash
git add scripts/token_list.py
git commit -m "feat(tokens): add token_list endpoint script"
```

---

## Task 5: `token_revoke.py` — soft-revoke a token

**Files:**
- Create: `scripts/token_revoke.py`

- [ ] **Step 1: Write the script**

Create `scripts/token_revoke.py`:

```python
"""Revoke a single api_tokens row (soft-delete: sets revoked_at).

Stdin: {"id": 42, "_acting_user": "alice"}
Stdout success: {"ok": true}
Stdout failure: {"ok": false, "error": "...", "code": "not_found"}  (404)

Only the token owner can revoke. Returns 404 (not 403) for tokens owned
by others — avoids leaking existence to unauthorized callers.
"""
from __future__ import annotations
import json
import sys

import token_db


def _revoke(token_id: int, acting: str) -> bool:
    conn = token_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE api_tokens t "
                    "   SET revoked_at = now() "
                    "  FROM users u "
                    " WHERE t.id = %s "
                    "   AND t.user_id = u.id "
                    "   AND LOWER(u.username) = LOWER(%s) "
                    "   AND t.revoked_at IS NULL "
                    "RETURNING t.id",
                    (token_id, acting),
                )
                return cur.fetchone() is not None
    finally:
        conn.close()


def main() -> int:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig").strip() or "{}"
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": "invalid JSON on stdin", "detail": str(e)}))
        return 2

    token_id = payload.get("id")
    acting = payload.get("_acting_user")
    if not isinstance(token_id, int) or token_id <= 0:
        print(json.dumps({"ok": False, "error": "id must be positive integer"}))
        return 3
    if not isinstance(acting, str) or not acting:
        print(json.dumps({"ok": False, "error": "missing _acting_user (server bug)"}))
        return 3

    try:
        ok = _revoke(token_id, acting)
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5

    if not ok:
        print(json.dumps({"ok": False, "code": "not_found", "error": "token not found"}))
        return 4

    print(json.dumps({"ok": True}))
    return 0
```

- [ ] **Step 2: Smoke test** (use a token id from Task 4 output)

```bash
echo '{"id":<TOKEN_ID>,"_acting_user":"<your_username>"}' | python scripts/token_revoke.py
```
Expected: `{"ok": true}` and exit 0.

Re-run with the same id:
Expected: `{"ok": false, "code": "not_found", "error": "token not found"}` and exit 4.

- [ ] **Step 3: Commit**

```bash
git add scripts/token_revoke.py
git commit -m "feat(tokens): add token_revoke endpoint script"
```

---

## Task 6: `auth_whoami_bearer.py` — resolve a Bearer token

**Files:**
- Create: `scripts/auth_whoami_bearer.py`

Mirrors `auth_whoami.py` for cookies but for Bearer tokens. Side effect: updates `last_used_at`.

- [ ] **Step 1: Write the script**

Create `scripts/auth_whoami_bearer.py`:

```python
"""Resolve a Bearer plaintext token to its user, AND update last_used_at.

Stdin:  {"token": "tkmo_..."}
Stdout success: {"ok": true, "user": {id, username, email, role}}
Stdout failure: {"ok": false}     (caller maps to 401)

A token is valid iff:
  - hash matches a row in api_tokens
  - revoked_at IS NULL
  - expires_at > NOW()
The corresponding user must exist (the FK + ON DELETE CASCADE guarantees
this at write time, but we still SELECT to load the user payload).
"""
from __future__ import annotations
import json
import sys

import token_db


def main() -> int:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig").strip() or "{}"
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = {}

    plaintext = payload.get("token")
    if not isinstance(plaintext, str) or not plaintext:
        print(json.dumps({"ok": False}))
        return 6

    t_hash = token_db.hash_token(plaintext)

    conn = None
    try:
        conn = token_db.connect()
        with conn:
            with conn.cursor() as cur:
                # Lookup + last_used bump in one round-trip
                cur.execute(
                    "UPDATE api_tokens "
                    "   SET last_used_at = now() "
                    " WHERE token_hash = %s "
                    "   AND revoked_at IS NULL "
                    "   AND expires_at > now() "
                    "RETURNING user_id",
                    (t_hash,),
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
        print(json.dumps({
            "ok": True,
            "user": {"id": u[0], "username": u[1], "email": u[2], "role": u[3]},
        }))
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

- [ ] **Step 2: Smoke test**

First, generate a fresh token (the one from Task 3 may have been revoked in Task 5):
```bash
echo '{"name":"smoke-bearer","expires_in_days":30,"_acting_user":"<your_username>"}' \
  | python scripts/token_create.py
```
Copy the `token` value from output.

```bash
echo '{"token":"<paste-token-here>"}' | python scripts/auth_whoami_bearer.py
```
Expected: `{"ok": true, "user": {"id": ..., "username": "...", "email": "...", "role": "..."}}`

```bash
echo '{"token":"tkmo_definitely_not_a_real_token_x_x_x_x_x_x_x"}' | python scripts/auth_whoami_bearer.py
```
Expected: `{"ok": false}` and exit code 6.

- [ ] **Step 3: Commit**

```bash
git add scripts/auth_whoami_bearer.py
git commit -m "feat(tokens): add auth_whoami_bearer for Bearer auth"
```

---

## Task 7: `server.js` — Bearer auth middleware + `/api/tokens` routes

**Files:**
- Modify: `server.js`

Three changes:
1. Add `AUTH_WHOAMI_BEARER_SCRIPT` constant.
2. Extend `resolveSession` to fall through to Bearer header when no cookie session resolves.
3. Add `/api/tokens` route handlers (POST, GET, DELETE) — **cookie auth only** (return 403 if the request authenticated via Bearer; otherwise tokens could mint more tokens).

- [ ] **Step 1: Add the script constant**

In `server.js`, near the other `*_SCRIPT` constants (search for `AUTH_WHOAMI_SCRIPT`), add the new constant:

Find this block:
```js
const AUTH_LOGIN_SCRIPT    = resolve(__dirname, "scripts", "auth_login.py");
const AUTH_LOGOUT_SCRIPT   = resolve(__dirname, "scripts", "auth_logout.py");
const AUTH_WHOAMI_SCRIPT   = resolve(__dirname, "scripts", "auth_whoami.py");
const AUTH_REGISTER_SCRIPT = resolve(__dirname, "scripts", "auth_register.py");
```

Add immediately after:
```js
const AUTH_WHOAMI_BEARER_SCRIPT = resolve(__dirname, "scripts", "auth_whoami_bearer.py");

const TOKEN_CREATE_SCRIPT = resolve(__dirname, "scripts", "token_create.py");
const TOKEN_LIST_SCRIPT   = resolve(__dirname, "scripts", "token_list.py");
const TOKEN_REVOKE_SCRIPT = resolve(__dirname, "scripts", "token_revoke.py");
```

- [ ] **Step 2: Extend `resolveSession`**

Find the existing `resolveSession` function (search for `async function resolveSession`). Replace its body with:

```js
async function resolveSession(req) {
  // Path A: existing cookie auth
  const sid = parseCookies(req)[SESSION_COOKIE];
  if (sid) {
    const result = await spawnPython(AUTH_WHOAMI_SCRIPT, JSON.stringify({ sid }));
    if (result.code === 0 && result.json && result.json.ok === true) {
      return { authMode: "cookie", sid, ...result.json.user };
    }
  }

  // Path B: Bearer token (added in Phase 0)
  const authHeader = req.headers.authorization || "";
  if (authHeader.startsWith("Bearer ")) {
    const token = authHeader.slice(7).trim();
    if (token) {
      const result = await spawnPython(AUTH_WHOAMI_BEARER_SCRIPT, JSON.stringify({ token }));
      if (result.code === 0 && result.json && result.json.ok === true) {
        return { authMode: "bearer", ...result.json.user };
      }
    }
  }

  return null;
}
```

Note the new `authMode` field — used below to gate `/api/tokens` to cookie auth only.

- [ ] **Step 3: Add the `/api/tokens` route block**

Locate a logical place to insert this — alongside other resource routes (after the user-admin routes, search for `/api/users` to find the cluster). Insert:

```js
  // ── API Tokens (cookie-auth ONLY; Bearer can't mint more Bearer) ──
  if ((req.url || "").startsWith("/api/tokens")) {
    if (req.sessionUser.authMode !== "cookie") {
      res.statusCode = 403;
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify({
        ok: false,
        error: "tokens API requires session login (cookie), not Bearer",
      }));
      return;
    }

    // POST /api/tokens — create
    if (req.url === "/api/tokens" && req.method === "POST") {
      const body = await readBody(req);
      let parsed;
      try { parsed = JSON.parse(body || "{}"); } catch { parsed = {}; }
      parsed._acting_user = req.sessionUser.username;
      const result = await spawnPython(TOKEN_CREATE_SCRIPT, JSON.stringify(parsed));
      res.statusCode = httpStatusFor(result.code, result.json);
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(result.json));
      return;
    }

    // GET /api/tokens — list
    if (req.url === "/api/tokens" && req.method === "GET") {
      const stdin = JSON.stringify({ _acting_user: req.sessionUser.username });
      const result = await spawnPython(TOKEN_LIST_SCRIPT, stdin);
      res.statusCode = httpStatusFor(result.code, result.json);
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(result.json));
      return;
    }

    // DELETE /api/tokens/:id — revoke
    const m = (req.url || "").match(/^\/api\/tokens\/(\d+)$/);
    if (m && req.method === "DELETE") {
      const id = parseInt(m[1], 10);
      const stdin = JSON.stringify({ id, _acting_user: req.sessionUser.username });
      const result = await spawnPython(TOKEN_REVOKE_SCRIPT, stdin);
      res.statusCode = httpStatusFor(result.code, result.json);
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(result.json));
      return;
    }

    // unknown method/path under /api/tokens
    res.statusCode = 404;
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify({ ok: false, error: "not found" }));
    return;
  }
```

- [ ] **Step 4: Restart server and verify cookie path still works**

Run: `node server.js` (in one terminal)

In another terminal:
```bash
python scripts/smoke_auth.py --username <you> --password <yourpw>
```
Expected: `PASS`. Confirms the auth middleware refactor didn't break cookie auth.

- [ ] **Step 5: Manually exercise the new endpoints**

Get a session cookie:
```bash
COOKIE=$(curl -i -X POST http://localhost:5181/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"<you>","password":"<pw>"}' 2>&1 \
  | grep -i 'set-cookie:' | head -1 | sed 's/.*sid=\([^;]*\).*/\1/')
echo "sid=$COOKIE"
```

Create a token:
```bash
curl -X POST http://localhost:5181/api/tokens \
  -H "Content-Type: application/json" \
  -H "Cookie: sid=$COOKIE" \
  -d '{"name":"curl-test","expires_in_days":30}'
```
Expected: `{"ok":true,"token":"tkmo_...","row":{...}}`. Copy the token.

List tokens:
```bash
curl -H "Cookie: sid=$COOKIE" http://localhost:5181/api/tokens
```
Expected: an array including the newly-created row (no `token_hash` field).

Use the Bearer token against `/api/auth/me` (or any authed endpoint):
```bash
TOKEN="<paste>"
curl -H "Authorization: Bearer $TOKEN" http://localhost:5181/api/auth/me
```
Expected: 200 with the user payload — proves Bearer auth works.

Confirm Bearer **can't** mint another token:
```bash
curl -X POST http://localhost:5181/api/tokens \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"should-fail","expires_in_days":30}'
```
Expected: 403 with `"tokens API requires session login (cookie), not Bearer"`.

Revoke the token:
```bash
ID="<id from list>"
curl -X DELETE -H "Cookie: sid=$COOKIE" http://localhost:5181/api/tokens/$ID
```
Expected: `{"ok":true}`.

Verify revoked token no longer works:
```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:5181/api/auth/me
```
Expected: 401.

- [ ] **Step 6: Commit**

```bash
git add server.js
git commit -m "feat(tokens): extend auth middleware for Bearer; add /api/tokens routes"
```

---

## Task 8: React — extend `src/auth/api.js` with token helpers

**Files:**
- Modify: `src/auth/api.js`

- [ ] **Step 1: Append token helpers**

Add at the bottom of `src/auth/api.js`:

```js
// ── API Tokens (Phase 0) ─────────────────────────────────────────

export async function listTokens() {
  const { status, body } = await apiJson("/api/tokens");
  return { status, body };
}

export async function createToken({ name, expires_in_days }) {
  const { status, body } = await apiJson("/api/tokens", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, expires_in_days }),
  });
  return { status, body };
}

export async function revokeToken(id) {
  const { status, body } = await apiJson(`/api/tokens/${id}`, { method: "DELETE" });
  return { status, body };
}
```

- [ ] **Step 2: Commit**

```bash
git add src/auth/api.js
git commit -m "feat(tokens): add listTokens/createToken/revokeToken client helpers"
```

---

## Task 9: React — `<TokenGenerateModal>` (two-step: form → one-shot reveal)

**Files:**
- Create: `src/settings/TokenGenerateModal.jsx`

- [ ] **Step 1: Create the component**

Style mirrors `UserEditModal.jsx`. Two-step pattern:
1. Form: name + expires_in_days radio buttons → Generate
2. Reveal: show plaintext token with Copy button + "I've saved it" close button

Create `src/settings/TokenGenerateModal.jsx`:

```jsx
import React, { useState } from "react";
import { Copy, X } from "lucide-react";
import { createToken } from "../auth/api.js";

const BB = {
  bg: "#000", panel: "#0a0a0a", border: "#1f1f1f",
  fg: "#e5e5e5", dim: "#7d7d7d", accent: "#FA8C16", red: "#FF4D4F",
};

const overlay = {
  position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)",
  display: "flex", alignItems: "center", justifyContent: "center", zIndex: 50,
};

const panel = {
  background: BB.panel, border: `1px solid ${BB.border}`,
  width: 460, padding: 20,
  fontFamily: "'IBM Plex Mono', ui-monospace, monospace", color: BB.fg, fontSize: 12,
};

const label = { display: "block", color: BB.dim, fontSize: 10, letterSpacing: 1.5, marginBottom: 6 };
const inputStyle = {
  background: BB.bg, color: BB.fg, border: `1px solid ${BB.border}`,
  padding: "8px 10px", width: "100%", fontFamily: "inherit", fontSize: 12, boxSizing: "border-box",
};
const primaryBtn = { background: BB.accent, color: BB.bg, border: "none", padding: "8px 16px", fontFamily: "inherit", fontSize: 11, letterSpacing: 1, cursor: "pointer" };
const ghostBtn   = { background: "transparent", color: BB.fg, border: `1px solid ${BB.border}`, padding: "8px 16px", fontFamily: "inherit", fontSize: 11, letterSpacing: 1, cursor: "pointer" };

export default function TokenGenerateModal({ onClose, onGenerated }) {
  const [name, setName] = useState("");
  const [days, setDays] = useState(90);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [plaintext, setPlaintext] = useState("");  // set after success → switches to reveal step
  const [copied, setCopied] = useState(false);

  async function onGenerate() {
    setError("");
    setBusy(true);
    const { status, body } = await createToken({ name: name.trim(), expires_in_days: days });
    setBusy(false);
    if (status !== 200 || !body?.ok) {
      setError(body?.error || `HTTP ${status}`);
      return;
    }
    setPlaintext(body.token);
    onGenerated?.();  // tell parent to refresh list in background
  }

  function onCopy() {
    navigator.clipboard.writeText(plaintext).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }

  // ── Step 2: reveal ─────────────────────────────────────────────
  if (plaintext) {
    return (
      <div style={overlay}>
        <div style={panel}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
            <div style={{ letterSpacing: 2, color: BB.dim, fontSize: 11 }}>TOKEN GENERATED — COPY NOW</div>
          </div>

          <div style={{
            background: BB.bg, border: `1px solid ${BB.border}`,
            padding: 12, wordBreak: "break-all", fontSize: 11, lineHeight: 1.6,
          }}>
            {plaintext}
          </div>

          <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
            <button style={ghostBtn} onClick={onCopy}>
              <Copy size={12} style={{ display: "inline", marginRight: 6, verticalAlign: -2 }} />
              {copied ? "COPIED" : "COPY"}
            </button>
          </div>

          <div style={{ color: BB.accent, fontSize: 11, marginTop: 16, lineHeight: 1.5 }}>
            ⚠ This token will NOT be shown again. Store it now (password manager, etc.).
          </div>

          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 16 }}>
            <button style={primaryBtn} onClick={onClose}>I'VE SAVED IT</button>
          </div>
        </div>
      </div>
    );
  }

  // ── Step 1: form ───────────────────────────────────────────────
  return (
    <div style={overlay}>
      <div style={panel}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <div style={{ letterSpacing: 2, color: BB.dim, fontSize: 11 }}>NEW API TOKEN</div>
          <button style={{ ...ghostBtn, padding: 4 }} onClick={onClose}><X size={12} /></button>
        </div>

        <div style={{ marginBottom: 14 }}>
          <span style={label}>NAME</span>
          <input
            style={inputStyle}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Alice's MacBook"
            autoFocus
            maxLength={64}
          />
        </div>

        <div style={{ marginBottom: 18 }}>
          <span style={label}>EXPIRES IN</span>
          <div style={{ display: "flex", gap: 12 }}>
            {[30, 90, 365].map((d) => (
              <label key={d} style={{ display: "flex", gap: 6, alignItems: "center", cursor: "pointer" }}>
                <input
                  type="radio"
                  name="days"
                  checked={days === d}
                  onChange={() => setDays(d)}
                />
                <span>{d === 365 ? "1 YEAR" : `${d} DAYS`}</span>
              </label>
            ))}
          </div>
        </div>

        {error && (
          <div style={{ color: BB.red, fontSize: 11, marginBottom: 12 }}>{error}</div>
        )}

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button style={ghostBtn} onClick={onClose} disabled={busy}>CANCEL</button>
          <button
            style={primaryBtn}
            onClick={onGenerate}
            disabled={busy || !name.trim()}
          >
            {busy ? "GENERATING..." : "GENERATE"}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit** (no manual UI test yet — needs the page to mount it; we'll test in Task 11)

```bash
git add src/settings/TokenGenerateModal.jsx
git commit -m "feat(tokens): add TokenGenerateModal with one-shot plaintext reveal"
```

---

## Task 10: React — `<ApiTokens>` page

**Files:**
- Create: `src/settings/ApiTokens.jsx`

- [ ] **Step 1: Create the page**

Style mirrors `UserAdmin.jsx`. Table of tokens + "+ GENERATE NEW TOKEN" button. Each row has a `[×]` revoke button.

Create `src/settings/ApiTokens.jsx`:

```jsx
import React, { useEffect, useState } from "react";
import { Plus, X } from "lucide-react";
import { listTokens, revokeToken } from "../auth/api.js";
import TokenGenerateModal from "./TokenGenerateModal.jsx";

const BB = {
  bg: "#000", panel: "#0a0a0a", border: "#1f1f1f",
  fg: "#e5e5e5", dim: "#7d7d7d", accent: "#FA8C16", red: "#FF4D4F",
};

function fmtDate(iso) {
  if (!iso) return "—";
  return iso.slice(0, 19).replace("T", " ");
}

const th = { padding: "10px 16px", textAlign: "left", color: BB.dim, fontSize: 10, letterSpacing: 1.5, borderBottom: `1px solid ${BB.border}` };
const td = { padding: "10px 16px", borderBottom: `1px solid ${BB.border}`, fontSize: 12 };
const primaryBtn = { display: "flex", alignItems: "center", gap: 6, background: BB.accent, color: BB.bg, border: "none", padding: "6px 12px", fontFamily: "inherit", fontSize: 11, letterSpacing: 1, cursor: "pointer" };
const ghostBtn   = { display: "flex", alignItems: "center", gap: 6, background: "transparent", color: BB.fg, border: `1px solid ${BB.border}`, padding: "6px 12px", fontFamily: "inherit", fontSize: 11, letterSpacing: 1, cursor: "pointer" };
const iconBtn    = { background: "transparent", color: BB.fg, border: `1px solid ${BB.border}`, padding: 4, cursor: "pointer" };

export default function ApiTokens({ onClose }) {
  const [rows, setRows]       = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState("");
  const [showModal, setShow]  = useState(false);

  async function load() {
    setLoading(true);
    const { status, body } = await listTokens();
    if (status === 200 && body?.ok) {
      setRows(body.tokens || []);
      setError("");
    } else {
      setError(body?.error || `HTTP ${status}`);
    }
    setLoading(false);
  }

  useEffect(() => { load(); }, []);

  async function onRevoke(t) {
    if (!confirm(`Revoke token "${t.name}"? Effective immediately.`)) return;
    const { status, body } = await revokeToken(t.id);
    if (status !== 200 || !body?.ok) {
      setError(body?.error || `Revoke failed (${status})`);
      return;
    }
    await load();
  }

  function status(t) {
    if (t.revoked_at) return { label: "REVOKED", color: BB.red };
    if (new Date(t.expires_at) <= new Date()) return { label: "EXPIRED", color: BB.dim };
    return { label: "ACTIVE", color: BB.accent };
  }

  return (
    <div style={{
      minHeight: "100vh", background: BB.bg, color: BB.fg,
      fontFamily: "'IBM Plex Mono', ui-monospace, monospace",
    }}>
      <div style={{
        padding: "16px 24px", display: "flex", alignItems: "center",
        justifyContent: "space-between", borderBottom: `1px solid ${BB.border}`,
      }}>
        <div style={{ fontSize: 13, letterSpacing: 2, color: BB.dim }}>MY API TOKENS</div>
        <div style={{ display: "flex", gap: 12 }}>
          <button onClick={() => setShow(true)} style={primaryBtn}>
            <Plus size={14} /> NEW TOKEN
          </button>
          <button onClick={onClose} style={ghostBtn}>
            <X size={14} /> CLOSE
          </button>
        </div>
      </div>

      {error && (
        <div style={{ padding: "10px 24px", color: BB.red, fontSize: 11 }}>
          {error}
        </div>
      )}

      <div style={{ padding: 24 }}>
        {loading ? (
          <div style={{ color: BB.dim, fontSize: 11 }}>LOADING...</div>
        ) : rows.length === 0 ? (
          <div style={{ color: BB.dim, fontSize: 11, padding: "20px 0" }}>
            No tokens yet. Click NEW TOKEN above to generate one for Claude Code or other clients.
          </div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", background: BB.panel }}>
            <thead>
              <tr>
                <th style={th}>NAME</th>
                <th style={th}>PREFIX</th>
                <th style={th}>STATUS</th>
                <th style={th}>LAST USED</th>
                <th style={th}>EXPIRES</th>
                <th style={th}></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => {
                const s = status(t);
                return (
                  <tr key={t.id}>
                    <td style={td}>{t.name}</td>
                    <td style={{ ...td, color: BB.dim }}>{t.token_prefix}...</td>
                    <td style={{ ...td, color: s.color }}>{s.label}</td>
                    <td style={{ ...td, color: BB.dim }}>{fmtDate(t.last_used_at)}</td>
                    <td style={{ ...td, color: BB.dim }}>{fmtDate(t.expires_at)}</td>
                    <td style={td}>
                      {!t.revoked_at && (
                        <button
                          onClick={() => onRevoke(t)}
                          style={{ ...iconBtn, color: BB.red, borderColor: BB.red }}
                          title="Revoke"
                        >
                          <X size={12} />
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {showModal && (
        <TokenGenerateModal
          onClose={() => { setShow(false); load(); }}
          onGenerated={() => { /* list reload happens on close */ }}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add src/settings/ApiTokens.jsx
git commit -m "feat(tokens): add ApiTokens page (list, revoke, generate modal)"
```

---

## Task 11: React — wire `<ApiTokens>` into the sidebar nav

**Files:**
- Modify: `src/TradeBookingForm.jsx` — adds import, mount condition, and sidebar nav link

The existing pattern uses `appView` state (line ~5489, values `"booking" | "users"`) with `<NavTabRow>` for sidebar links. We extend it to a third value `"tokens"`. The tokens link is **available to all logged-in users** (unlike `Users`, which is admin-only).

- [ ] **Step 1: Add the import**

Find the import block near line 23 of `src/TradeBookingForm.jsx`:

```jsx
import UserAdmin from "./admin/UserAdmin.jsx";
```

Add immediately below:

```jsx
import ApiTokens from "./settings/ApiTokens.jsx";
```

- [ ] **Step 2: Extend the `appView` state values**

Find around line 5489:

```jsx
const [appView, setAppView] = useState("booking"); // "booking" | "users"
```

Replace with:

```jsx
const [appView, setAppView] = useState("booking"); // "booking" | "users" | "tokens"
```

- [ ] **Step 3: Add the mount conditional**

Find the existing mount block around line 7018:

```jsx
  if (appView === "users" && user?.role === "admin") {
    return <UserAdmin onClose={() => setAppView("booking")} />;
  }
```

Add immediately above (so tokens is checked first; either order works, but this keeps admin-only mounts together):

```jsx
  if (appView === "tokens") {
    return <ApiTokens onClose={() => setAppView("booking")} />;
  }
```

- [ ] **Step 4: Add the sidebar nav link**

Find the existing nav block around lines 7195–7212. The current code:

```jsx
              onClick={() => setView("PENDING_BOOKINGS")}
            />

            {user?.role === "admin" && (
              <>
                {/* Separator before the admin-only section */}
                <div
                  className="mx-5 my-2"
                  style={{ borderTop: `1px dashed #d9d4c7` }}
                />
                <NavTabRow
                  label="Users"
                  active={appView === "users"}
                  onClick={() => setAppView("users")}
                />
              </>
            )}
          </div>
```

Replace with (adds a "Tokens" link **outside** the admin gate, just before it, since it's for all users):

```jsx
              onClick={() => setView("PENDING_BOOKINGS")}
            />

            <NavTabRow
              label="API Tokens"
              active={appView === "tokens"}
              onClick={() => setAppView("tokens")}
            />

            {user?.role === "admin" && (
              <>
                {/* Separator before the admin-only section */}
                <div
                  className="mx-5 my-2"
                  style={{ borderTop: `1px dashed #d9d4c7` }}
                />
                <NavTabRow
                  label="Users"
                  active={appView === "users"}
                  onClick={() => setAppView("users")}
                />
              </>
            )}
          </div>
```

- [ ] **Step 5: Manual UI smoke test**

Run: `npm run dev` (Vite, frontend on port 5180)
And in another terminal: `node server.js` (backend on 5181)

In a browser at `http://localhost:5180`:
1. Log in as your normal user.
2. Click `API Tokens` in the sidebar.
3. The page loads — shows "No tokens yet" (or any tokens you created via curl earlier).
4. Click `NEW TOKEN`. Modal opens.
5. Enter a name like "browser test". Pick 90 days. Click `GENERATE`.
6. Reveal step shows the plaintext token. Click `COPY`. Confirm button reads `COPIED`.
7. Click `I'VE SAVED IT`. Modal closes; list now shows the new token with status `ACTIVE`.
8. Click `×` (revoke) on a row. Confirm. Status flips to `REVOKED` (or the row vanishes and reappears on next refresh — depending on how `load()` orders).
9. Click `CLOSE` in the page header. Returns to the trade booking form.

- [ ] **Step 6: Test that the token actually works**

In a terminal:
```bash
TOKEN="<paste from step 5.6 above>"
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:5181/api/auth/me | python -m json.tool
```
Expected: `{"ok": true, "user": {"id": ..., "username": "...", ...}}`

- [ ] **Step 7: Commit**

```bash
git add src/TradeBookingForm.jsx
git commit -m "feat(tokens): wire API Tokens link + page into sidebar nav"
```

---

## Task 12: End-to-end smoke script

**Files:**
- Create: `scripts/smoke_tokens.py`

Mirrors `scripts/smoke_auth.py`. Exercises the full lifecycle: log in (cookie) → create token → list → use Bearer against `/api/auth/me` → Bearer-can't-mint-token → revoke → Bearer fails 401.

- [ ] **Step 1: Write the smoke**

Create `scripts/smoke_tokens.py`:

```python
"""End-to-end smoke for the API tokens surface.

Run server.js separately first:

    node server.js

Then in another terminal:

    python scripts/smoke_tokens.py --username <you> --password <yourpw>

Exits 0 with "PASS" if every assertion passes; non-zero on first failure.
Creates a token (random name, safe to re-run), then revokes it.
"""
from __future__ import annotations
import argparse
import http.cookiejar
import json
import sys
import urllib.error
import urllib.request
import uuid


BASE = "http://localhost:5181"


def _req(method, path, body=None, jar=None, bearer=None):
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if bearer is not None:
        headers["Authorization"] = f"Bearer {bearer}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar or http.cookiejar.CookieJar())
    )
    try:
        resp = opener.open(req)
        raw = resp.read().decode("utf-8") or "null"
        return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8") or "null"
        return e.code, json.loads(raw) if raw else None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--username", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--base-url", default=BASE)
    args = p.parse_args()

    global BASE
    BASE = args.base_url

    jar = http.cookiejar.CookieJar()
    test_name = f"smoke-{uuid.uuid4().hex[:8]}"

    # 1. Log in to get a session cookie
    status, body = _req("POST", "/api/auth/login",
                        {"username": args.username, "password": args.password}, jar=jar)
    assert status == 200 and body and body.get("user"), f"login failed: {status} {body}"
    print("✓ login (cookie)")

    # 2. Create a token via cookie
    status, body = _req("POST", "/api/tokens",
                        {"name": test_name, "expires_in_days": 30}, jar=jar)
    assert status == 200 and body and body.get("ok"), f"create failed: {status} {body}"
    token = body["token"]
    token_id = body["row"]["id"]
    assert token.startswith("tkmo_") and len(token) == 48, f"bad token format: {token}"
    print(f"✓ create token (id={token_id}, prefix={body['row']['token_prefix']})")

    # 3. List tokens — should include the new one
    status, body = _req("GET", "/api/tokens", jar=jar)
    assert status == 200 and body and body.get("ok"), f"list failed: {status} {body}"
    found = [t for t in body["tokens"] if t["id"] == token_id]
    assert found, f"created token not in list: {body['tokens']}"
    assert "token_hash" not in found[0], "token_hash must NEVER appear in list output"
    print(f"✓ list tokens ({len(body['tokens'])} total)")

    # 4. Use the Bearer token (no cookie this time)
    status, body = _req("GET", "/api/auth/me", bearer=token)
    assert status == 200 and body and body.get("user"), f"bearer whoami failed: {status} {body}"
    assert body["user"]["username"].lower() == args.username.lower(), \
        f"bearer resolved to wrong user: {body}"
    print("✓ bearer auth against /api/auth/me")

    # 5. Bearer CANNOT mint another token (must be cookie)
    status, body = _req("POST", "/api/tokens",
                        {"name": "should-fail", "expires_in_days": 30}, bearer=token)
    assert status == 403, f"expected 403 when minting via Bearer, got {status} {body}"
    print("✓ bearer blocked from /api/tokens (403)")

    # 6. Revoke (via cookie)
    status, body = _req("DELETE", f"/api/tokens/{token_id}", jar=jar)
    assert status == 200 and body and body.get("ok"), f"revoke failed: {status} {body}"
    print(f"✓ revoke token (id={token_id})")

    # 7. Bearer now fails 401
    status, body = _req("GET", "/api/auth/me", bearer=token)
    assert status == 401, f"expected 401 after revoke, got {status} {body}"
    print("✓ revoked token returns 401")

    print("\nPASS")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as e:
        print(f"\nFAIL: {e}", file=sys.stderr)
        sys.exit(1)
```

- [ ] **Step 2: Run the smoke**

Start the server (in another terminal): `node server.js`

Then:
```bash
python scripts/smoke_tokens.py --username <you> --password <yourpw>
```
Expected output:
```
✓ login (cookie)
✓ create token (id=N, prefix=tkmo_...)
✓ list tokens (M total)
✓ bearer auth against /api/auth/me
✓ bearer blocked from /api/tokens (403)
✓ revoke token (id=N)
✓ revoked token returns 401

PASS
```
Exit code: 0

- [ ] **Step 3: Run the existing auth smoke too** (regression check)

```bash
python scripts/smoke_auth.py --username <you> --password <yourpw>
```
Expected: `PASS`. Confirms Phase 0 didn't break existing auth.

- [ ] **Step 4: Commit**

```bash
git add scripts/smoke_tokens.py
git commit -m "test(tokens): add end-to-end smoke for Phase 0"
```

---

## Task 13: README update + Helm chart bump

**Files:**
- Modify: `README.md`
- Modify: `version.yml` (and/or `helm/Chart.yaml` depending on existing pattern)

- [ ] **Step 1: Add an "API Tokens" section to README**

Append a new section under the existing `## Auth` section (or just below it):

```markdown
## API Tokens (Phase 0)

For programmatic access (Claude Code, CI runners, scripts), generate a personal
token from the in-app `API TOKENS` page (top right of the header when logged in).

```bash
# Authenticate any /api/* request with:
curl -H "Authorization: Bearer tkmo_..." http://localhost:5181/api/auth/me
```

Tokens carry your `user_id` and respect all the same auth gates as the cookie
session. The `/api/tokens` management surface itself requires cookie login —
tokens cannot mint or revoke other tokens (prevents privilege chaining).

Defaults: 90-day expiry, sha256-hashed at rest, plaintext shown **once** at creation.
```

- [ ] **Step 2: Bump the Helm chart version**

Read `version.yml` first, then bump the patch version (`0.0.24` → `0.0.25` if that's the existing pattern). Look at recent commits like `chore(release): bump chart to 0.0.24` to match the format.

- [ ] **Step 3: Commit**

```bash
git add README.md version.yml
git commit -m "docs(tokens): document Phase 0 token system + bump chart"
```

---

## Task 14: Apply to PROD + manual verification

Phase 0 ships as a deployable unit. After all prior tasks pass on UAT and merged to main, run the same schema migration against PROD and verify via the prod Helm-deployed app.

- [ ] **Step 1: Apply schema to PROD**

This step requires PROD DB credentials. Run the migration with the env vars switched to MO_DB_PROD (the existing convention from `apply_schema_*.py` scripts). If your shell setup uses a different `.env` block, follow whatever the team uses for PROD migrations.

```bash
# Example — substitute with the actual PROD env-var pattern used by the team
MO_DB_HOST=<prod-host> MO_DB_PORT=5432 MO_DB_DATABASE=<prod-db> \
MO_DB_USERNAME=<prod-user> MO_DB_PASSWORD=<prod-pw> \
  python scripts/apply_schema_api_tokens.py
```
Expected: `ok: api_tokens table ready`

- [ ] **Step 2: Deploy the new Helm chart**

Follow the existing deploy pattern (likely `scripts/deploy_k8s-prod.sh` based on the repo). Confirm the chart picks up the bumped version.

- [ ] **Step 3: Smoke against PROD**

Once the new pod is rolled out:
```bash
python scripts/smoke_tokens.py \
  --username <you> --password <yourpw> \
  --base-url https://mo-tools.tokkalabs.com
```
Expected: `PASS`. (If the URL differs, substitute.)

- [ ] **Step 4: Verify in-app**

In a browser at the PROD URL, log in, click `API TOKENS`, generate a test token, confirm reveal works, revoke it. Confirms the React build picked up the new page.

- [ ] **Step 5: Tag the release**

```bash
git tag phase-0-tokens
git push origin phase-0-tokens
```

Phase 0 is done. Phase 1 (CASHFLOW draft + batch + plugin) is planned in a separate document once Phase 0 has been used by you for at least a few days and any rough edges are filed.

---

## Verification checklist (run before marking phase complete)

- [ ] `python -m pytest tests/test_token_db.py -v` — all pass
- [ ] `flake8 --max-line-length=88 --ignore=E203,W503,E501,F841,F401,E722,F541,F811,E262,C901 scripts/token_db.py scripts/token_create.py scripts/token_list.py scripts/token_revoke.py scripts/auth_whoami_bearer.py tests/test_token_db.py scripts/smoke_tokens.py` — clean
- [ ] `python scripts/smoke_auth.py --username <you> --password <pw>` — PASS (regression)
- [ ] `python scripts/smoke_tokens.py --username <you> --password <pw>` — PASS
- [ ] Browser smoke: log in → API TOKENS → generate → copy → revoke (UAT)
- [ ] `curl -H "Authorization: Bearer <token>" /api/auth/me` returns 200 with user payload
- [ ] `curl -H "Authorization: Bearer <token>" -X POST /api/tokens` returns 403 (Bearer can't mint)
- [ ] PROD schema applied + smoke against PROD URL — PASS
- [ ] Helm chart version bumped + deployed
- [ ] README has API Tokens section
- [ ] All commits follow the `prefix(scope): message` style and reference Phase 0
