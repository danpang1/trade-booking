# Tokka MO · Manual Trade Booking

Standalone React/Vite module for booking manual trades (SPOT / FUTURE / CASHFLOW / LOAN). Built to ship independently from the main `dashboard/` and to eventually wire into the planned `/api/bookings` FastAPI + Postgres backend.

## Run

```bash
npm install
npm run dev      # http://localhost:5180
npm run build    # → dist/
npm run preview  # serve built dist/
```

## Auth

The dashboard is gated by a login page. Users + sessions live in Postgres UAT, independent of the MySQL `reference_data.user` mirror used by the dropdown sync.

### First-time bootstrap

```powershell
pip install -r requirements.txt
python scripts/apply_schema_users.py
python scripts/apply_schema_users_pending.py
python scripts/user_create.py --username <you> --email <you>@tokkalabs.com --role admin
```

`user_create.py` prompts for the password (hidden via `getpass`). Re-run with new args to add more admins or users.

### Self-registration & approval

Users without an account can request one from the login page:

1. Click `REQUEST ACCOUNT →` on the login form.
2. Enter username / email / password (twice).
3. Submit. The account lands in a pending queue — no login until approval.

Admins approve from `USER ADMIN`:

1. Click the `PENDING (N)` tab.
2. Pick `APPROVE AS USER` or `APPROVE AS ADMIN` per row (role is assigned at approval time, not requested by the user).
3. Or `REJECT` to delete the request (the user can re-register).

Pending users hitting the login form get `"Account pending admin approval"`. Wrong-password attempts return generic `"invalid credentials"` regardless of status — no account-existence oracle.

Admin bootstrap (above) is unchanged: `user_create.py --role admin` creates an immediately-active admin and skips the approval flow.

### Smoke test

With `node server.js` running on `:5181`, in another terminal:

```powershell
python scripts/smoke_auth.py --username <you> --password <yourpw>
```

Prints `PASS` if login, whoami, role gate (admin → 200 on /api/users, user → 403), bad-login (401), and logout all behave correctly.

Add `--register` to also exercise the registration + approval flow (register → pending-login fails → approve → login OK → register → reject → login fails):

```powershell
python scripts/smoke_auth.py --username <admin> --password <yourpw> --register
```

### Roles

- `admin` — everything, including the in-app `USERS` page (`/api/users` CRUD). Manage users via the header link.
- `user` — book, amend, view; the `USERS` link is hidden and `/api/users` returns 403.

### Session

HTTP-only cookie, 8-hour sliding window: every authenticated request extends `expires_at` by 8h. F5 keeps you signed in; idle ≥ 8h logs you out automatically. Logout (header button) deletes the session row immediately.

### user_id is unforgeable

Every booking POST has its `user_id` field overwritten by the session username server-side, so it doesn't matter what the form sends — the DB always records the actual signed-in user.

## API Tokens (Phase 0)

For programmatic access (Claude Code, CI runners, scripts), generate a personal token from the in-app `API Tokens` page (sidebar nav, available to all logged-in users).

```bash
# Authenticate any /api/* request with:
curl -H "Authorization: Bearer tkmo_..." http://localhost:5181/api/auth/me
```

Tokens carry your `user_id` and respect all the same auth gates as the cookie session. The `/api/tokens` management surface itself (and `/api/auth/logout`) requires cookie login — tokens cannot mint or revoke other tokens, preventing privilege chaining.

Defaults: 30/90/365-day expiry (your choice), sha256-hashed at rest, plaintext shown **once** at creation. Revoke is one click; effective immediately.

End-to-end smoke: `python scripts/smoke_tokens.py --username <you> --password <yourpw>`.

## Bookings Drafts (Phase 1a)

A draft-and-approve pipeline for CASHFLOW bookings, intended to back the
Claude Code plugin (Phase 1b, separate repo). Any Bearer-auth client can
submit a CASHFLOW as a draft; the human reviewer approves or rejects in
the in-app **Pending Drafts** sidebar page. Approval inserts into the
live `trades_cashflow` table via the exact same code path the booking
form uses — no schema divergence.

### Endpoints

All accept cookie session **OR** `Authorization: Bearer <token>`. Per-user
isolation enforced server-side: list/get/patch/approve/reject only see
drafts where `created_by = req.sessionUser.username`. Other users' drafts
return 404 (not 403 — avoids existence leak).

| Method | Path                                | Notes |
|--------|-------------------------------------|-------|
| POST   | `/api/bookings/draft`               | Create one draft. Idempotent on `client_request_id` |
| POST   | `/api/bookings/draft/batch`         | Create N drafts atomically (all-or-nothing). Max 50/batch. |
| GET    | `/api/bookings/drafts`              | List acting user's drafts. Filters: `?status=`, `?batch_id=` |
| GET    | `/api/bookings/drafts/:id`          | Fetch a single draft |
| PATCH  | `/api/bookings/drafts/:id`          | Edit payload — only when `PENDING_REVIEW` |
| POST   | `/api/bookings/drafts/:id/approve`  | Atomic claim + insert into `trades_cashflow` |
| POST   | `/api/bookings/drafts/:id/reject`   | Soft reject with optional `{reason}` |

### Provenance & audit

- Draft creation stamps `payload.user_id` with **`claude:<username>`** so
  every approved trade is attributable to the Claude Code path. The
  bare `<username>` is recorded separately on `bookings_draft.approved_by`
  (the human reviewer).
- The cashflow audit-trail UI (`HistoryModal`) joins `trades_cashflow`
  against `bookings_draft` on `approved_deal_ref` and surfaces
  `by claude:danny.pang · approved by danny.pang` on the initial version.
- Approval is a **single Postgres transaction**: the draft-status flip
  and the `cashflow_insert._insert_one(cur, payload)` call run on the
  same cursor. If the live insert fails for any reason, the draft stays
  `PENDING_REVIEW` — no orphan row possible.

### Validation (layered defense)

Three-tier validation so bad values can't slip into `trades_cashflow`:

1. **Plugin (Claude / future CLIs)** — validates every refdata-bound field
   (`cashflow_type`, `counterparty`, `portfolio_id`, `account`, `asset`,
   `network`, `account_type`) against the live dropdown/refdata before
   posting. See `claude/feedback_claude_plugin_validate_refdata`.
2. **Server (`cashflow_db.validate_payload`)** — same enums + refdata
   lookups, fail-open on refdata-sync outage. Returns HTTP 400 with the
   valid set enumerated when a client sends a non-standard value.
3. **Postgres** — CHECK constraints on `bookings_draft.{category, source,
   status}` + UNIQUE on `client_request_id` (idempotent retries).

The server enforces 14 required CASHFLOW fields (`cashflow_type`,
`direction`, `entity`, `portfolio_id`, `portfolio_name`, `counterparty`,
`account`, `account_type`, `asset`, `amount`, `trade_date`, `value_date`,
`user_id`, `status`). `trade_date`/`value_date` default to draft-creation
time (UTC) when omitted, so simple bookings can skip them.

### React UX

- **`PENDING DRAFTS`** sidebar row (with `(N)` badge polled every 60s
  when the tab is focused, paused when hidden).
- Per-row: `FORM` opens the full booking form as a modal overlay (same
  `ModalShell` used by Amend). `✓` / `✗` approve / reject inline.
- Per-batch: `APPROVE ALL N` button. Per-row errors surface inline.
- `?draft=<id>` URL deep-link opens the modal directly — works for
  sharing draft links.
- Modal opens optimistically (instant) with "Loading draft #N…" banner;
  fields populate when `getDraft` returns. Save / Approve buttons are
  disabled while loading.
- `APPROVED` / `REJECTED` sections collapsed by default; show
  `APPROVED BY` / `REJECTED BY` columns when expanded.

### End-to-end smoke

```powershell
node server.js   # in another terminal
python scripts/smoke_drafts.py --username <you> --password <yourpw>
```

Exercises login → POST single → dedupe → POST batch (3 rows) → GET list
filters → PATCH → approve (single + batch) → reject → re-reject 409.
Prints `PASS` and a cleanup `DELETE FROM trades_cashflow ...` line.

## Theme

Bloomberg-terminal aesthetic — black canvas, orange (`#FA8C16`) primary accent, cyan/amber/green/red data colors, sharp rectangular inputs, JetBrains Mono throughout. All theme tokens live in the `BB` constants block at the top of `src/TradeBookingForm.jsx` — nothing leaks to global CSS.

## Features

### Cashflow — Auto-fill from tx hash (EVM)

In the cashflow booking form, after picking a network and pasting a transaction
hash, click **Fetch** to pull the asset, amount, gas, and timestamps directly
from chain (via Goldrush/Covalent). Only EVM chains supported in v1 — Solana,
Tron, BTC etc. need to be filled manually. Requires `GOLDRUSH_API_KEY` in env.

## Wire-up status

Frontend-only at this point. The "Book Trade" button currently just flips `status → BOOKED` locally and updates the JSON preview. Planned backend:

- `POST /api/bookings` (multipart: record JSON + file attachments)
- Postgres `bookings` table (one row, JSONB `payload` per category)
- Google Drive service account → per-`trade_id` folder for term sheets / invoices / agreements
- Reference data from `tq_oms_data` Postgres (323 active accounts, ~90 venues, 724 instruments) — to populate dropdowns
