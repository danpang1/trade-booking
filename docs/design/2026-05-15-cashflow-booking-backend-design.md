# Cashflow Booking Backend — Design

**Date:** 2026-05-15
**Module:** `trade-booking/`
**Status:** Draft for review

## 1. Purpose

The `trades_cashflow` table exists on UAT Postgres (bitemporal SCD2,
allocated `deal_ref` from `trade_seq_cashflow`). The Trade Booking
frontend can build a schema-aligned payload (`outputRecord` in
`TradeBookingForm.jsx`) but cannot yet write to the database.

This spec adds the missing backend: HTTP endpoints + Python workers that
INSERT new cashflows, AMEND existing ones, and provide a list/fetch API
for the Deal Enquiry view so the user can pick a booking to amend or
cancel from the UI.

## 2. Scope

**In scope (v1):**

- Insert new cashflow bookings (single record + mirror-leg pair).
- Amend existing cashflows via bitemporal SCD2 close-and-reinsert.
- Cancel = amend with `status='CANCELLED'` (no separate code path).
- Deal Enquiry page renders 20 most recent live cashflows; click a row
  to load it into the form for amendment.
- Backend re-validates everything the frontend validates.
- Optimistic concurrency safety against simultaneous amends.

**Out of scope (v1, deferred):**

- Authentication / authorization. `user_id` comes from the form's
  "Created by" dropdown; backend trusts it. UAT only.
- A `mo_users` reference table — `USER_PROFILES` stays hardcoded in
  JSX for now. The `trades_cashflow.user_id` column is
  forward-compatible (string FK-ready).
- Search/filter UI on the Deal Enquiry page beyond "recent 20". Filter
  by portfolio/counterparty/date is a follow-up.
- Amending the mirror-leg *pair* atomically. The two legs are
  independent `deal_ref`s; each can be amended on its own.
- SPOT / FUTURE / LOAN booking endpoints. This spec covers CASHFLOW
  only; the same pattern can be replicated for those when they're built.

## 3. Architecture

Mirrors the existing dashboard pattern (`dashboard/server.js`): a Node
HTTP server adds routes that spawn small, single-purpose Python scripts
which talk to Postgres via `psycopg2`. One DB driver, one creds loader,
one mental model across the codebase.

### 3.1 Endpoints (added to `trade-booking/server.js`, port 5181)

| Method | Route | Purpose | Spawns |
| ------ | ----- | ------- | ------ |
| POST | `/api/cashflow/insert` | Insert one or two (mirror-leg) fresh rows | `scripts/cashflow_insert.py` |
| POST | `/api/cashflow/amend` | Close current live row + insert new version | `scripts/cashflow_amend.py` |
| GET  | `/api/cashflow/recent?limit=20` | List N most recent live rows for Deal Enquiry | `scripts/cashflow_recent.py` |
| GET  | `/api/cashflow/:deal_ref` | Fetch the live row for one deal_ref | `scripts/cashflow_get.py` |

Each Node handler:

1. Reads the JSON body (POST) or query string (GET).
2. Spawns the corresponding Python script with the request payload
   piped to stdin.
3. Reads the Python stdout as JSON and forwards it to the HTTP client.
4. On non-zero Python exit, returns HTTP 500 with the trailing stderr.

### 3.2 Shared Python helper — `trade-booking/scripts/cashflow_db.py`

A small module reused by all four scripts:

- `load_creds()` — same `_load_creds()` pattern as
  `apply_schema_cashflow.py`; reads the `#MO DB UAT` block from
  `<repo>/.env`.
- `connect()` — returns a `psycopg2` connection with `autocommit=False`
  so scripts can explicitly manage transactions.
- `validate_payload(payload, *, mode)` — checks required fields, enum
  values, mirror-leg integrity. Raises `ValidationError` (caught at
  the entry point and printed as `{"ok": false, "error": ...}`).
- `row_to_payload(cur, row)` — converts a DB row tuple back into the
  JSON shape the form produces. Keeps the mapping
  (`trade-booking/docs/cashflow-schema-mapping.md`) as the single
  source of truth.
- `payload_to_columns(payload)` — inverse: form JSON → tuple of values
  in DDL column order. Computes server-set fields
  (`txn_type='CASHFLOW'`, `effective_start=NOW()` in SQL,
  `effective_end=NULL` in SQL).

### 3.3 Insert flow (data flow on a fresh booking)

```
TradeBookingForm.handleSubmit()
    POST /api/cashflow/insert  body=outputRecord
        → server.js spawns cashflow_insert.py
            BEGIN
            SELECT nextval('trade_seq_cashflow')           → 42
            INSERT INTO trades_cashflow (... 'MCF-42' ...,
              effective_start = NOW(), effective_end = NULL, ...)
              RETURNING *
            COMMIT
        ← Python prints {"ok": true, "rows": [<row JSON>]}
    ← server.js relays JSON
UI shows toast "Booked MCF-42"
```

**Mirror-leg case** (cf_type = INTER PTF FUNDING + Mirror Trade): the
payload arrives as a 2-element array. The script calls `nextval` twice,
INSERTs both rows, COMMITs once. Atomic — both lands or neither.

## 4. SCD2 mechanics — the close-and-reinsert

This is where "do it proper" matters most. Naive `SELECT current →
UPDATE → INSERT` has a TOCTOU race.

### 4.1 Amend transaction (single deal_ref)

```sql
BEGIN;

-- Atomically close the current live row. If another txn already closed
-- it, this affects 0 rows and the script returns 409 conflict.
UPDATE trades_cashflow
   SET effective_end = NOW()
 WHERE deal_ref = $1
   AND effective_end IS NULL
RETURNING deal_ref;
-- 0 rows → ROLLBACK, return {"ok": false, "error": "no live row for $1"}

-- Insert the new version: same deal_ref, new field values, new effective window.
INSERT INTO trades_cashflow (
  deal_ref, external_trade_id, txn_type, cashflow_type, direction,
  entity, portfolio_id, portfolio_name, counterparty, account,
  account_type, asset, amount, fee_asset, fee_amount,
  trade_date, value_date, network, txid_reference,
  effective_start, effective_end, user_id, status, comment
) VALUES (
  $1, $2, 'CASHFLOW', $3, $4,
  $5, $6, $7, $8, $9,
  $10, $11, $12, $13, $14,
  $15, $16, $17, $18,
  NOW(), NULL, $19, $20, $21
)
RETURNING *;

COMMIT;
```

Rules:

- `deal_ref` is preserved across the amendment chain (the sequence is
  NOT bumped on amend).
- The new row is a **full snapshot**, not a diff: every column is set
  from the payload, including unchanged ones. The frontend round-trips
  the loaded row through the form and back, so all columns are
  populated.
- `txn_type` is always `'CASHFLOW'` for this table.
- `user_id` is overwritten with whoever performed the amend (form's
  "Created by"), not preserved from the original.
- **Cancel** is identical to amend with `status='CANCELLED'`. No
  separate code path.

### 4.2 Concurrency safety

If two users hit "Update MCF-42" within milliseconds:

- Both transactions issue the `UPDATE ... WHERE effective_end IS NULL`.
- Postgres row-locks the matching row: one txn waits.
- The winner: 1 row returned → INSERT new version → COMMIT.
- The loser: when its UPDATE runs, `effective_end` is no longer NULL →
  0 rows returned → script ROLLBACKs and returns
  `{"ok": false, "error": "MCF-42 was amended by another session"}`
  with HTTP 409.
- UI handles 409 with a modal: "This booking was just amended. Reload
  to fetch the latest version."

No `SELECT-then-UPDATE` window, so no race.

## 5. API contract

### 5.1 Common envelope

All responses:

```json
{ "ok": true,  "rows": [ <full row JSON, mapping-doc shape> ] }
{ "ok": false, "error": "<short user-facing>", "detail": "<optional>" }
```

HTTP status codes:

- 200 — success
- 400 — validation failure
- 404 — `deal_ref` not found (GET) or no live row (amend)
- 409 — concurrent-amend conflict (amend)
- 500 — Python crash / DB error

### 5.2 POST /api/cashflow/insert

**Body:** the form's `outputRecord` — either an object (single record)
or a 2-element array (mirror-leg pair). Shape follows the mapping doc
exactly.

**Response (success):** `rows` contains 1 element for single, 2 for
mirror-leg, each row populated with the server-allocated `deal_ref`
and `effective_start`.

### 5.3 POST /api/cashflow/amend

**Body:** the form's `outputRecord`, with `deal_ref` populated (it's
the row being amended). Single record only — no mirror-leg amend in
v1.

**Response (success):** `rows[0]` is the newly inserted live row.

### 5.4 GET /api/cashflow/recent?limit=20

**Response (success):**

```json
{
  "ok": true,
  "rows": [
    { "deal_ref": "MCF-42", "trade_date": "...", "portfolio_id": 8006,
      "counterparty": "Galaxy", "asset": "USDC", "amount": "1000000",
      "direction": "RECEIVE", "status": "CONFIRMED", ... },
    ...
  ]
}
```

Query: `SELECT * FROM trades_cashflow WHERE effective_end IS NULL
ORDER BY trade_date DESC, deal_ref DESC LIMIT $1`.

### 5.5 GET /api/cashflow/:deal_ref

**Response (success):** `rows[0]` is the live row for that deal_ref;
404 if none exists.

## 6. Frontend wiring

### 6.1 `handleSubmit` rewrite (TradeBookingForm.jsx:2233)

```js
const handleSubmit = async () => {
  if (!canSubmit) return;
  const endpoint = amendingDealRef
    ? "/api/cashflow/amend"
    : "/api/cashflow/insert";
  const res = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(outputRecord),
  });
  const result = await res.json();
  if (result.ok) {
    setSubmittedRecord(Array.isArray(result.rows) && result.rows.length === 1
      ? result.rows[0]
      : result.rows);
    const verb = amendingDealRef ? "Updated" : "Booked";
    setAmendingDealRef(null);
    setFeedback({ kind: "success", message: `${verb} ${result.rows[0].deal_ref}` });
  } else if (res.status === 409) {
    setConflictModal({ dealRef: amendingDealRef, message: result.error });
  } else {
    setFeedback({ kind: "error", message: result.error, detail: result.detail });
  }
};
```

### 6.2 Deal Enquiry component

Replaces the `PlaceholderView` at TradeBookingForm.jsx:2651.

- On mount: `fetch('/api/cashflow/recent?limit=20')`.
- Renders a table: `deal_ref`, `trade_date`, `portfolio_id`,
  `counterparty`, `cashflow_type`, `direction`, `asset`, `amount`,
  `status`.
- A `[↻]` refresh button re-fetches.
- Row click → `loadIntoForm(deal_ref)`:
    1. `fetch('/api/cashflow/' + deal_ref)`.
    2. `payloadToFormState(row)` — inverse of `outputRecord`. Derives
       `form.portfolio` from `portfolio_id`, etc.
    3. `setForm(...)`, `setAmendingDealRef(deal_ref)`,
       `setView("TRADE_INPUT")`.

### 6.3 Amend-mode UI affordances

- Submit button label switches from `"Book Trade"` to `"Update <MCF-X>"`.
- Internal Trade Id field shows the loaded `deal_ref`, stays read-only.
- A small `× cancel amend` link near the submit clears
  `amendingDealRef` and resets the form.
- Reset clears `amendingDealRef` too.

## 7. Validation — defense in depth

| Layer | Catches | Where |
| ----- | ------- | ----- |
| Frontend (`canSubmit`, `e.push(...)`) | Missing required fields, format errors. Instant UX. | TradeBookingForm.jsx:2192 |
| Python (`validate_payload`) | Re-validates everything + cross-field rules (mirror-leg integrity, enum values, numeric parseability). Returns 400 before opening a txn. | `cashflow_db.py` |
| DB CHECK constraints | Final guarantee (`direction`, `status`, `NOT NULL`s). | Postgres DDL |

Frontend is never trusted on its own — any curl client bypasses it.

## 8. Error UX

No toast/banner primitive exists in `TradeBookingForm.jsx` today. v1
adds two minimal local helpers (no third-party lib):

- A `<SubmitFeedback />` block rendered just above the submit button,
  driven by a `feedback` state slice (`{ kind: "error" | "success" |
  "conflict", message: string, detail?: string } | null`). Auto-clears
  on success after ~4s; sticks on error until the user edits a field
  or dismisses.
- A `ConflictModal` for the 409 case only — overlay with a Reload
  button that re-fetches the live row and re-populates the form.

Mapping:

- **Validation (400)** — `feedback = { kind: "error", message: result.error }`. Form stays filled.
- **Conflict (409)** — opens the `ConflictModal` with the deal_ref;
  Reload button calls `loadIntoForm(deal_ref)`.
- **Server / DB (500)** — `feedback = { kind: "error", message: result.error, detail: result.detail }` with an "expand detail" disclosure.
- **Success** — `feedback = { kind: "success", message: "Booked MCF-42" }` (or "Updated"); auto-clears after 4s.

## 9. Logging

Every spawn logs to the existing `server.log`:

```
[cashflow] insert MCF-42 by adam @ 2026-05-15T14:23:01Z
[cashflow] amend  MCF-42 by adam @ 2026-05-15T15:01:44Z (was version effective 14:23:01)
[cashflow] FAIL   amend MCF-42: concurrent-amend (409)
```

Payload is logged with secrets redacted (no fields in this schema are
sensitive, but the helper enforces the policy generally). stderr from
Python is captured and surfaces in the log + the HTTP response detail.

## 10. Files touched / added

**New files:**

- `trade-booking/scripts/cashflow_db.py` — shared helper.
- `trade-booking/scripts/cashflow_insert.py` — INSERT script.
- `trade-booking/scripts/cashflow_amend.py` — AMEND script (used by
  cancel too).
- `trade-booking/scripts/cashflow_recent.py` — list endpoint script.
- `trade-booking/scripts/cashflow_get.py` — single-row GET script.

**Modified files:**

- `trade-booking/server.js` — four new routes wired to spawn the
  scripts.
- `trade-booking/src/TradeBookingForm.jsx` — replace `handleSubmit`,
  add `DealEnquiry` component, add `amendingDealRef` state +
  `payloadToFormState` helper, swap the `PlaceholderView` at
  line 2651.

**Updated docs:**

- `trade-booking/docs/cashflow-schema-mapping.md` — append a brief
  "API contract" section referencing this spec.

## 11. Out-of-scope explicitly

- Auth / RBAC.
- Filtering on the enquiry page.
- Backfilling existing data (none exists).
- Booking history view (showing all versions for a deal_ref).
- Atomic mirror-leg amend.
- SPOT / FUTURE / LOAN endpoints.
