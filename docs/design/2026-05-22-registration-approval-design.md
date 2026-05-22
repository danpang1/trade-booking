# Trade Booking — Self-Registration with Admin Approval

**Date:** 2026-05-22
**Status:** Approved (brainstorming complete, ready for implementation plan)
**Scope:** Extend the auth system shipped on 2026-05-21 with (a) a show/hide password toggle on the login page and (b) public self-registration that queues new accounts for admin approval before they can log in.
**Builds on:** `2026-05-21-trade-booking-auth-design.md`

---

## 1. Motivation

Today the only way to add a user is for an admin to run `python scripts/user_create.py` on the server. That's fine for the handful of initial users but doesn't scale — every new team member requires a sysadmin round-trip. Self-registration with an approval gate lets users start the process themselves while keeping the role assignment and access decision in admin hands.

The show/hide password toggle is a small UX fix bundled into the same release because it touches the same component (`LoginPage.jsx`) and the same review.

---

## 2. Decisions taken during brainstorming

| Decision | Choice | Rationale |
|---|---|---|
| Admin queue location | Extend existing `UserAdmin.jsx` with an `ACTIVE / PENDING` tab strip | One management surface for all users; no new top-level page |
| Reject behavior | Hard delete the pending row | Simplest; user can re-register with the same username/email |
| Pending login message | Specific: `"Account pending admin approval"` | Registration is open anyway, so leaking pending status helps nobody |
| Notifications | None for v1 — polling only | No SMTP wired up; admins notice new rows when they next open USER ADMIN |
| Storage | Single `users` table with new `status` column, no separate registrations table | Single source of truth; no schema duplication |
| Role at registration | Not collected from the user; admin assigns at approval | Matches the stated requirement and avoids users gaming role choice |

Out of scope for v1 (worth revisiting if the app goes public-internet):
- Rate-limiting / CAPTCHA on `/api/auth/register`
- Email-domain allowlist
- Email notifications either direction
- Self-service password reset

---

## 3. Schema changes

Add two columns and relax one constraint on the existing `users` table. No new tables.

```sql
ALTER TABLE users ADD COLUMN status        VARCHAR(16) NOT NULL DEFAULT 'active'
                  CHECK (status IN ('pending','active'));
ALTER TABLE users ADD COLUMN approved_at   TIMESTAMPTZ NULL;
ALTER TABLE users ADD COLUMN approved_by   VARCHAR(64) NULL;
ALTER TABLE users ALTER COLUMN role DROP NOT NULL;
ALTER TABLE users ADD CONSTRAINT users_active_has_role
                  CHECK (status = 'pending' OR role IS NOT NULL);
```

**Why each piece:**
- `status='active'` default keeps every existing row and every future `user_create.py --role admin` bootstrap path working untouched.
- `approved_at` / `approved_by` give an audit trail of who let whom in. Stays `NULL` for bootstrap admins and other rows that didn't come through the approval flow.
- Making `role` nullable lets a pending row exist with no role yet. The new CHECK constraint enforces that **only** pending rows may have NULL role — once status flips to active, role must be set.

Migration script: `scripts/apply_schema_users_pending.py`. Idempotent (uses `ADD COLUMN IF NOT EXISTS` / `DROP NOT NULL` is itself idempotent / `ADD CONSTRAINT IF NOT EXISTS` via a `pg_catalog` lookup). Mirrors the existing `apply_schema_users.py` pattern.

`user_db.PUBLIC_COLUMNS` gains `status`, `approved_at`, `approved_by` so they flow through to `GET /api/users` responses.

---

## 4. Backend API + scripts

### New: `POST /api/auth/register` (public)

- Added to the public-bypass list in `server.js` alongside `/api/auth/login` and `/api/health`. No session cookie required.
- Spawns new `scripts/auth_register.py` with stdin `{username, email, password}`.
- Inserts a row with `status='pending'`, `role=NULL`, `created_by=NULL`, `approved_at=NULL`, `approved_by=NULL`.
- Validates via existing `user_db.validate_username` / `validate_email` / `validate_password`.
- Hashes the password with the existing bcrypt cost-12 helper — plain-text password is never stored even for unapproved accounts.
- Success → 200 `{ok:true, message:"Account submitted for approval"}`.
- Username/email collision → 409 `{ok:false, code:"conflict", error:"username or email already taken"}` (matches `user_create.py`'s existing UniqueViolation handler).
- Validation failure → 400 `{ok:false, error:"<which field>"}` (exit 3).

### Modified: `auth_login.py`

After successful password verification, check the row's `status`. If `pending`:

```python
print(json.dumps({"ok": False, "error": "Account pending admin approval"}))
return 6  # server.js maps exit 6 → HTTP 401
```

No `INSERT INTO sessions` runs for a pending row, so a pending user can never hold a valid session cookie.

The order matters: password is verified **before** the status check is revealed, so an attacker cannot use the new error message as an oracle for "this username exists." A wrong password against a pending account still returns `invalid credentials`.

### New: `POST /api/users/:id/approve` (admin only)

- Server.js checks `req.sessionUser.role === "admin"` (same pattern as existing `/api/users` CRUD).
- Spawns new `scripts/user_approve.py` with stdin `{user_id, role, _acting_user}`.
- SQL: `UPDATE users SET status='active', role=%s, approved_at=NOW(), approved_by=%s WHERE id=%s AND status='pending'`.
- 0 rows updated → 404 if no such row, 409 `{code:"conflict", error:"user already active"}` if status was already active.
- Body: `{role: "user" | "admin"}`. Validated via existing `user_db.validate_role`.

### New: `POST /api/users/:id/reject` (admin only)

- Same admin gate.
- Spawns `scripts/user_reject.py` with stdin `{user_id}`.
- SQL: `DELETE FROM users WHERE id=%s AND status='pending' RETURNING id`.
- 0 rows deleted → 404 if no such row, 409 `{code:"conflict", error:"can only reject pending users"}` if the row was active. (Active users are deleted via the existing DELETE endpoint, not this one.)

### Unchanged: `GET /api/users`

Already returns all users via `SELECT *`. After `PUBLIC_COLUMNS` is extended, responses include `status`, `approved_at`, `approved_by` automatically — the frontend filters by status into its two tabs.

### Exit-code → HTTP map (unchanged)

All new scripts follow the existing `httpStatusFor` mapping in `server.js`: `0→200`, `3→400`, `4→404`, `5→500`, `6→401`, with `code:"conflict"`→409 and `code:"not_found"`→404 overrides.

### Defensive try/except

All three new scripts (`auth_register.py`, `user_approve.py`, `user_reject.py`) wrap `user_db.connect()` **inside** the try/except — the same pattern we fixed in `auth_login.py` on 2026-05-22 so DB/creds failures surface as JSON rather than an empty stdout.

---

## 5. Frontend changes

### `LoginPage.jsx`

1. **Show/hide password toggle.** Add `lucide-react`'s `Eye` / `EyeOff` icon as an inline button on the right edge of the password input. Click toggles `type` between `"password"` and `"text"`. State held in component: `const [showPw, setShowPw] = useState(false)`. The button is `tabIndex={-1}` so keyboard tab order still goes input → SIGN IN button.
2. **REQUEST ACCOUNT link.** Below the SIGN IN button, a single-line text link. Click swaps the form into register mode (parent `App.jsx`-level state, no router change needed — `App.jsx` already conditionally renders `<LoginPage>` based on auth state, and we just add a `mode: "login" | "register"` toggle alongside).

### New: `src/auth/RegisterPage.jsx`

- Same Bloomberg-terminal styling as `LoginPage.jsx` — copy the existing constants (`BB`, `inputStyle`).
- Four inputs: `USERNAME`, `EMAIL`, `PASSWORD` (with show/hide toggle, reused), `CONFIRM PASSWORD` (with its own toggle).
- Client-side check: passwords must match before enabling the submit button. Server-side validation is authoritative.
- Submit calls `POST /api/auth/register`.
- Success → switches back to login mode with a one-time banner: `"Account submitted. You'll be notified when an admin approves it."` (Uses the existing `banner` prop on `LoginPage`.)
- Failure → inline red error message under the form (same pattern as the existing login error).
- "BACK TO SIGN IN" link below the REGISTER button for users who hit the wrong link.

### `UserAdmin.jsx`

1. **Tab strip at the top:** `ACTIVE (N)` | `PENDING (N)` rendered as text buttons with an underline on the active tab. Pending count badge in tokka orange when N > 0.
2. **PENDING tab table:** columns `USERNAME · EMAIL · SUBMITTED AT · ACTIONS`. Three inline action buttons per row:
   - `APPROVE AS USER` (default style — ghost button with blue text on hover)
   - `APPROVE AS ADMIN` (accent button — orange, matches the existing primary button style)
   - `REJECT` (red text, ghost style with red border)
   No modal — one click per decision. Optimistic UI: row is removed from the pending list immediately; a failure rolls it back and shows an error toast.
3. **ACTIVE tab:** existing table unchanged except for one new optional column `APPROVED BY` rendered between ROLE and CREATED AT. Blank for rows where `approved_by IS NULL` (bootstrap admins, pre-2026-05-22 users).
4. **Polling:** `GET /api/users` runs on mount + every 30 seconds while the component is mounted, so pending counts stay fresh without manual refresh. Tab badges update from the same fetch — no separate count endpoint.

---

## 6. Error handling

| Condition | Response |
|---|---|
| Registration: duplicate username/email | 409 `{ok:false, code:"conflict", error:"username or email already taken"}` |
| Registration: weak password (<8 chars) | 400 `{ok:false, error:"password must be >= 8 chars"}` (existing validator message) |
| Registration: invalid username chars | 400 `{ok:false, error:"username must be 3-64 chars [a-zA-Z0-9._-]"}` |
| Registration: invalid email format | 400 `{ok:false, error:"invalid email"}` |
| Login: pending account, correct password | 401 `{ok:false, error:"Account pending admin approval"}` |
| Login: pending account, wrong password | 401 `{ok:false, error:"invalid credentials"}` (no oracle) |
| Approve: not found | 404 `{ok:false, error:"user not found"}` |
| Approve: already active | 409 `{ok:false, code:"conflict", error:"user already active"}` |
| Approve: invalid role | 400 `{ok:false, error:"role must be one of ('admin','user')"}` |
| Reject: not found | 404 |
| Reject: already active | 409 `{ok:false, code:"conflict", error:"can only reject pending users"}` |
| Approve/reject as non-admin | 403 `{ok:false, error:"admin only"}` (server.js gate, never reaches Python) |
| Any DB connect failure | 500 `{ok:false, error:"DB error", detail:"<psycopg2 message>"}` (via the try/except wrap in every script) |

The new `msg:"python"` structured log line added on 2026-05-22 will also capture script stderr for any non-zero exit, so failures show up in Grafana automatically.

---

## 7. Security

- **Public-bypass scope unchanged in spirit.** Only `/api/auth/login`, `/api/auth/register`, and `/api/health` skip the session check. Everything else stays behind the auth gate.
- **Admin gate is server-side.** `req.sessionUser.role === "admin"` is checked on the server for `/approve` and `/reject` — the frontend doesn't get to decide.
- **Pending accounts cannot create sessions.** Status check runs in `auth_login.py` before `INSERT INTO sessions`, so no session row exists for a pending user. Even if a pending user somehow obtains a `sid` cookie (e.g. an admin tested with their account), `auth_whoami.py` only resolves sessions to active user rows — no privilege escalation path.
- **Passwords always hashed.** Registration runs `user_db.hash_password` (bcrypt cost 12) before INSERT. No plain-text password ever lives in the DB.
- **No oracle for "username exists."** Login returns `"invalid credentials"` for any wrong-password scenario regardless of status. Only correct-password-but-pending shows the distinct pending message. Registration with a duplicate username does leak existence ("already taken") — that's intentional and matches every register flow on the internet; the alternative ("we sent you an email" silently) requires SMTP.
- **Self-rejection of own admin status not blocked.** An admin could in theory `REJECT` their own pending registration — except admins by definition come through the bootstrap CLI (`user_create.py --role admin`), so no admin has a pending row in the first place. Not worth a guard.
- **Out of scope (worth revisiting if internet-exposed):** rate limiting, CAPTCHA, email-domain allowlist, email verification.

---

## 8. Testing

### Pytest

- `tests/test_auth_register.py` — happy path; duplicate username; duplicate email; weak password; invalid username chars; invalid email; verifies inserted row has `status='pending'`, `role IS NULL`, `created_by IS NULL`, `approved_at IS NULL`.
- `tests/test_user_approve.py` — approve as user (verifies status / role / approved_at / approved_by); approve as admin; approve non-existent (404); approve already-active (409); approve with invalid role string (400).
- `tests/test_user_reject.py` — reject pending (verifies row gone); reject active (409); reject non-existent (404).
- `tests/test_auth_login.py` (extend existing) — pending account + correct password returns `"Account pending admin approval"` + exit 6; pending account + wrong password returns `"invalid credentials"` + exit 6 (no oracle); verifies no `sessions` row is created for a pending login attempt regardless of outcome.

All Python tests use the existing per-test DB rollback fixture (whatever the current `tests/conftest.py` pattern is — to be confirmed in the implementation plan).

### E2E smoke

Extend `scripts/smoke_auth.py` with a new `--register` mode:

1. Register a fresh user with a random username.
2. Attempt login → expect 401 `"Account pending admin approval"`.
3. Approve via `POST /api/users/<id>/approve` as a known admin.
4. Login again → expect 200 with cookie.
5. Reject path: register, then reject, then verify login returns `invalid credentials` (row gone).

---

## 9. Migration / rollout plan

1. Apply schema migration in UAT: `python scripts/apply_schema_users_pending.py`. Existing users keep `status='active'`, `approved_at=NULL`, `approved_by=NULL` — no data backfill needed.
2. Ship the new code via the standard CI flow (`scripts/update_version.py` bump → commit → push → ECR → helm rollout). Both backend (server.js + new scripts) and frontend (RegisterPage + UserAdmin tabs) ship in the same image.
3. Smoke-test on UAT with `python scripts/smoke_auth.py --register`.
4. No coordinated downtime; the schema migration is backward-compatible — old code reading the table still works since the new columns have defaults / are nullable.

---

## 10. Files changed / added

| File | Change |
|---|---|
| `scripts/apply_schema_users_pending.py` | **NEW** — idempotent migration |
| `scripts/auth_register.py` | **NEW** — public registration script |
| `scripts/user_approve.py` | **NEW** — admin approve + role assignment |
| `scripts/user_reject.py` | **NEW** — admin reject (hard delete) |
| `scripts/user_db.py` | Add `status`/`approved_at`/`approved_by` to `PUBLIC_COLUMNS` |
| `scripts/auth_login.py` | Add post-password status check; pending → exit 6 with new message |
| `scripts/smoke_auth.py` | Add `--register` mode covering the full flow |
| `server.js` | New routes: `/api/auth/register` (public), `/api/users/:id/approve`, `/api/users/:id/reject`. Admin-only middleware factored if not already |
| `src/App.jsx` | Add login/register mode toggle alongside existing auth state |
| `src/auth/LoginPage.jsx` | Show/hide password toggle; REQUEST ACCOUNT link; accept post-register banner prop (already exists) |
| `src/auth/RegisterPage.jsx` | **NEW** — registration form |
| `src/auth/api.js` | Add `register()` helper alongside existing `login()` |
| `src/admin/UserAdmin.jsx` | Tab strip; PENDING table with three action buttons; APPROVED BY column; 30s polling |
| `tests/test_auth_register.py` | **NEW** |
| `tests/test_user_approve.py` | **NEW** |
| `tests/test_user_reject.py` | **NEW** |
| `tests/test_auth_login.py` | Extend with pending-status cases |

---

## 11. Open questions

None at design time. Two items to confirm during implementation:

- Existing `tests/conftest.py` pattern for DB rollback fixture — verify name and re-use rather than introducing a new fixture.
- Whether `App.jsx` currently has any router-like indirection or just inline conditional rendering — affects how the login/register mode toggle is plumbed. Spot-check in the implementation plan's first task.
