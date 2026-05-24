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

## Theme

Bloomberg-terminal aesthetic — black canvas, orange (`#FA8C16`) primary accent, cyan/amber/green/red data colors, sharp rectangular inputs, JetBrains Mono throughout. All theme tokens live in the `BB` constants block at the top of `src/TradeBookingForm.jsx` — nothing leaks to global CSS.

## Wire-up status

Frontend-only at this point. The "Book Trade" button currently just flips `status → BOOKED` locally and updates the JSON preview. Planned backend:

- `POST /api/bookings` (multipart: record JSON + file attachments)
- Postgres `bookings` table (one row, JSONB `payload` per category)
- Google Drive service account → per-`trade_id` folder for term sheets / invoices / agreements
- Reference data from `tq_oms_data` Postgres (323 active accounts, ~90 venues, 724 instruments) — to populate dropdowns
