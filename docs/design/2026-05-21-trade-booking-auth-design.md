# Trade Booking — Authentication & User Management

**Date:** 2026-05-21
**Status:** Approved (brainstorming complete, ready for implementation plan)
**Scope:** Add login + role-based access + admin user-management to the standalone `trade-booking/` repo.

---

## 1. Motivation

The dashboard currently has no authentication. Anyone on the network can submit, amend, or view trade bookings, and the `user_id` field on the form is free-text — the booker can self-identify as anyone. The existing `sync_users.py` mirrors `reference_data.user` from the corporate MySQL but is purely a dropdown source, not an auth check.

This design adds a real login gate, a Postgres-backed user store, and an admin UI to manage users.

---

## 2. Decisions taken during brainstorming

| Decision | Choice | Rationale |
|---|---|---|
| Auth source of truth | New local `users` table in Postgres UAT (same DB as `trades_cashflow`), independent of MySQL mirror | Simplest mental model; MySQL `reference_data.user` is upstream-owned and can't have passwords added |
| Gating scope | Hard gate — everything requires login | `user_id` becomes unforgeable; cleanest model |
| Roles | Two: `admin` and `user` | Minimal and fits the stated request; easy to add more later |
| Bootstrap | CLI script (`user_create.py`) run once after schema migration | No default credentials in code/config; same script doubles as recovery tool |
| Session mechanism | HTTP-only cookie + Postgres `sessions` table, 8-hour sliding window | Revocable, XSS-safe, standard pattern; cheap per-request lookup |
| Bitemporal? | No | Users aren't trades; SCD Type 2 is overkill |

---

## 3. Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│  Browser (React)                                                   │
│                                                                    │
│   <App>  ← new top-level wrapper, holds auth state                 │
│     ├── <LoginPage>           (shown when not authenticated)       │
│     └── <Authenticated>                                            │
│           ├── header { user badge · logout · "Users" (admin only) }│
│           ├── <TradeBookingForm>    (existing — minor edits)       │
│           └── <UserAdmin>           (only mounted for role=admin)  │
└─────────────────────────────────┬──────────────────────────────────┘
                                  │  fetch() with credentials:'include'
                                  ▼
┌────────────────────────────────────────────────────────────────────┐
│  server.js (Node) — new middleware + new routes                    │
└─────────────────────────────────┬──────────────────────────────────┘
                                  ▼
┌────────────────────────────────────────────────────────────────────┐
│  Python scripts (new) — same spawnPython pattern                   │
└─────────────────────────────────┬──────────────────────────────────┘
                                  ▼
                          Postgres UAT
                          (new tables: users, sessions)
```

**Key invariants:**

- Existing booking endpoints lose their dependency on form-supplied `user_id`. The new middleware overwrites/sets `payload.user_id = req.user.username` before spawning the Python script. Old client code keeps working; new bookings are unforgeable.
- No router introduced. Auth state is the router: `<App>` renders either `<LoginPage>` or `<Authenticated>`.
- Cookie survives reload — the dashboard does not log you out on F5. Logout requires explicit click or session expiry.

---

## 4. Data model

Postgres UAT, same DB as `trades_cashflow`. **Not bitemporal.**

### 4.1 `users`

```sql
CREATE TABLE users (
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

CREATE INDEX users_username_lower_idx ON users (LOWER(username));
```

Column order is locked. `created_by`/`updated_by` are nullable to allow bootstrap rows where there is no acting user yet.

Login lookup is case-insensitive on username; `email` is also unique.

`password_hash` is bcrypt with cost 12 — always exactly 60 chars.

### 4.2 `sessions`

```sql
CREATE TABLE sessions (
  session_id      UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         INTEGER         NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
  expires_at      TIMESTAMPTZ     NOT NULL,
  last_seen_at    TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX sessions_user_id_idx     ON sessions (user_id);
CREATE INDEX sessions_expires_at_idx  ON sessions (expires_at);
```

`gen_random_uuid()` requires `pgcrypto`; `apply_schema_users.py` runs `CREATE EXTENSION IF NOT EXISTS pgcrypto` defensively.

Expired rows are swept on each login attempt (`DELETE FROM sessions WHERE expires_at < now()`). No background cron.

`ON DELETE CASCADE` ensures deleting a user force-logs-out their open sessions.

---

## 5. API surface

All routes added to `server.js`. Auth scripts reuse the existing stdin-JSON / stdout-JSON pattern (same as `cashflow_insert.py`).

### 5.1 Auth lifecycle

| Method · Path | Auth | Body | Behavior |
|---|---|---|---|
| `POST /api/auth/login` | none | `{username, password}` | `auth_login.py`. Success → `Set-Cookie: sid=<uuid>; HttpOnly; SameSite=Lax; Path=/; Max-Age=28800` and `{ok:true, user:{username,role,email}}`. Failure → `401 {ok:false, error:"invalid credentials"}` (same message for "user not found" and "wrong password" — no user enumeration). No throttling in v1. |
| `POST /api/auth/logout` | logged-in | — | `auth_logout.py` deletes the session row, clears the cookie. `204`. |
| `GET /api/auth/me` | logged-in | — | Returns `{username, role, email}` from the middleware-attached request user (no extra DB roundtrip). |

### 5.2 User administration (role=admin only)

| Method · Path | Body | Behavior |
|---|---|---|
| `GET /api/users` | — | `user_list.py` → `{ok, rows:[{id,username,email,role,created_at,updated_at}]}`. Never returns `password_hash`. |
| `POST /api/users` | `{username, email, role, password}` | `user_create.py`. Validates: role ∈ {admin,user}; username ≥3 chars, regex `[a-zA-Z0-9._-]+`; email basic regex; password ≥8 chars. `409` on unique violation. |
| `PATCH /api/users/:id` | `{email?, role?, password?}` | `user_update.py`. Any subset of fields. Password re-hashed if present. **Username is not editable** (login key + stamped into trade rows). Last-admin guard: cannot demote or delete the last remaining admin. |
| `DELETE /api/users/:id` | — | `user_delete.py`. Cascade wipes their sessions. Last-admin guard applies. Cannot delete yourself. |

### 5.3 Middleware (added in front of route dispatch)

```
1.  /api/auth/login                  → skip auth
2.  Static asset (no /api prefix)    → skip auth
3.  Otherwise:
     a. parse `sid` cookie
     b. spawn auth_whoami.py with {sid}: in one SQL it
          SELECT … FROM sessions JOIN users …
          WHERE session_id=$1 AND expires_at > now()
          → if row, UPDATE sessions SET expires_at = now()+interval '8 hours', last_seen_at = now()
          → return {user_id, username, role, email}
     c. null/expired → 401 {ok:false, error:"not authenticated"}
     d. attach req.user
4.  /api/users/* → also require req.user.role==='admin'; 403 otherwise
5.  /api/cashflow|loan|spot/* → BEFORE spawning, set payload.user_id = req.user.username
```

### 5.4 Error envelope

All endpoints use the existing `{ok:false, error, detail?}` shape. HTTP statuses: `400` validation, `401` not authenticated, `403` not admin, `404` not found, `409` conflict, `500` other.

---

## 6. Python scripts (new)

```
scripts/
  apply_schema_users.py     # CREATE EXTENSION pgcrypto; CREATE TABLE users, sessions; idempotent
  user_db.py                # shared: creds, bcrypt helpers, validators, row mapper
  user_create.py            # CLI (TTY = getpass prompt) OR stdin-JSON mode (server)
  user_list.py              # stdin: {} → stdout: {ok, rows:[…]}
  user_update.py            # stdin: {id, email?, role?, password?}
  user_delete.py            # stdin: {id, acting_user_id}  (for self-delete guard)
  auth_login.py             # stdin: {username, password} → {ok, sid, user} or 401
  auth_logout.py            # stdin: {sid} → {ok:true}
  auth_whoami.py            # stdin: {sid} → {ok, user} (also extends expiry)
```

Mode detection (CLI vs stdin) follows the pattern already used by `apply_schema_*.py`: `sys.stdin.isatty()` → interactive; else read JSON from stdin and emit JSON on stdout.

---

## 7. Frontend changes

### 7.1 File map

```
src/
  main.jsx                 (1-line change — render <App/>)
  App.jsx                  NEW — auth state machine
  auth/
    AuthContext.jsx        NEW — { user, login, logout, refresh }
    LoginPage.jsx          NEW — Bloomberg-terminal login form
    api.js                 NEW — fetch wrapper (credentials:'include', 401-bounce)
  admin/
    UserAdmin.jsx          NEW — user-management table
    UserEditModal.jsx      NEW — create/edit modal
  TradeBookingForm.jsx     edits:
                             - delete SUPERADMIN_USERS picker
                             - user_id becomes read-only (from useAuth())
                             - header gains user badge · logout · "Users" link
                             - all fetch(…) → api(…)
```

### 7.2 `<App>` state machine

```
mount → GET /api/auth/me
   ├── 200 {user}    → set user, render <Authenticated/>
   ├── 401           → render <LoginPage onSuccess={refresh}/>
   └── network error → render <LoginPage> with banner
```

`<Authenticated>` holds a single state `view ∈ {"booking","users"}`. Header link flips it. No URL changes.

### 7.3 Login page

Centered card on black canvas — JetBrains Mono, orange accent, sharp rectangles. Two inputs (username, password), one button, error banner. Enter submits. On 401: red banner "Invalid credentials". No "remember me", no "forgot password" in v1.

### 7.4 `<UserAdmin>`

Bloomberg-style table. Columns: `ID · Username · Email · Role · Created · Updated · ⋯`. Header has `+ New User`. Row actions: edit · delete.

`<UserEditModal>`:
- **Create** mode: username, email, role (dropdown), password (visible with show/hide toggle).
- **Edit** mode: email, role, password (blank = unchanged). Username shown but disabled.

UI also dims delete/demote on the last-admin row; server enforces.

### 7.5 `auth/api.js`

```js
export async function api(path, opts = {}) {
  const r = await fetch(path, { credentials: "include", ...opts });
  if (r.status === 401 && !path.endsWith("/api/auth/login")) {
    window.dispatchEvent(new CustomEvent("auth:expired"));
  }
  return r;
}
```

`<App>` listens for `auth:expired` and re-mounts `<LoginPage>` with banner "Session expired — please sign in again".

---

## 8. Bootstrapping & dev workflow

```powershell
pip install bcrypt psycopg2-binary
python scripts/apply_schema_users.py
python scripts/user_create.py --username peter --email peter@tokkalabs.com --role admin
# → prompts for password (getpass), confirms, inserts
npm run dev
```

The dashboard opens to the login page. `peter / <yourpw>` lets you in as admin and the "Users" header link is now visible.

---

## 9. Dependencies

| Layer | Package | Notes |
|---|---|---|
| Python | `bcrypt` (≥4.0) | New. Add to `requirements.txt`. |
| Python | `psycopg2-binary` | Already in use. |
| Node | _none_ | Cookie parsing is ~10 lines; UUID from Postgres. |
| React | _none_ | No router, no state lib — `useContext` is enough. |

No new env vars in v1.

---

## 10. Tests

- `tests/test_user_db.py` — pure-logic unit tests (password hashing round-trip, validator regexes, last-admin-guard). No DB.
- `scripts/smoke_auth.py` — manual smoke against UAT: create user → login → whoami → logout → bad-login → 401. Documented in README; not wired into CI in v1.

---

## 11. Out of scope (v1)

- Password complexity beyond min-8-chars
- Account lockout / rate-limiting on failed login
- Password reset by email
- "Change my own password" endpoint for non-admin users (admin resets it)
- 2FA / SSO / OAuth
- Audit log of admin actions

Each can be added incrementally without schema changes.
