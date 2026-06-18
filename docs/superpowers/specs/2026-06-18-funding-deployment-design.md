# Funding & Deployment — Dashboard section

**Date:** 2026-06-18
**Status:** approved, implemented

## Goal

Add a **Funding & Deployment** band to the existing `Dashboard()` view
(`src/TradeBookingForm.jsx`) showing how the book is funded and the running
balance after inception-to-date PnL.

## Breakdown (top → bottom)

| Row | Source | Editable |
|-----|--------|----------|
| Capital | manual, default **6,600,000** | yes |
| Internal Loan | live — Σ LIVE `loan_type=INTERNAL` **`direction=BORROW`** principal, USD-valued | no |
| VIP Loan | live — `vipLtv.summary.loan_principal_usd` from `/api/binance/vip-loan/ltv` | no |
| **= Total Funding** | computed: Capital + Internal Loan + VIP Loan | — |
| ITD PnL | manual | yes |
| **= Funding Balance** | computed: Total Funding + ITD PnL | — |

## Data sourcing

- **Internal Loan**: computed client-side from `/api/loan/recent?limit=2000`,
  filtering `status==="LIVE"` && `loan_type==="INTERNAL"` && `direction==="BORROW"`
  (funding the desk has *borrowed* internally; LEND rows are deployment, excluded),
  USD-valued via `/api/rates/latest`. NB: UAT test data has no such loan, so it
  reads ~0 on UAT; production shows the real figure (~24m) if booked as INTERNAL borrow.
- **VIP Loan**: `vipLtv.summary.loan_principal_usd` from the lightweight `/ltv` route.
- **Capital / ITD PnL**: persisted editable values (see backend).

## Backend — `funding_settings`

Shared key-value store, mirrors the `loan_schedule_comments` trio. Postgres UAT
(`loan_db.connect()` / `MO_DB_*`).

Table:
```
funding_settings (
  key         TEXT          NOT NULL PRIMARY KEY,   -- 'capital' | 'itd_pnl'
  value       NUMERIC       NOT NULL,
  updated_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
  updated_by  TEXT          NOT NULL
)
```

Files:
- `scripts/apply_schema_funding_settings.py` — DDL.
- `scripts/funding_settings_db.py` — `fetch_settings(cur)` (defaults capital 6_600_000,
  itd_pnl 0 for absent rows); `upsert_setting(cur, key, value, user_id)`. Allowlisted
  keys `{capital, itd_pnl}`; value coerced to a finite number (ITD PnL may be negative).
- `scripts/funding_settings_read.py` — stdin `{}`, stdout `{"ok":true,"settings":{...}}`.
- `scripts/funding_settings_upsert.py` — stdin `{key,value,user_id}`, stdout `{"ok":true,"row":{...}}`.

Routes (server.js):
- `GET  /api/funding/settings` → read script.
- `POST /api/funding/settings` → `stampUserId` (force `user_id` from session), upsert script.

## Frontend — Dashboard band

New band inside `Dashboard()`, styled with the existing card idiom / CSS vars
(`--ink`, `--rule`, `--paper`, `--signal-link`, `--signal-sell`, `--font-mono`,
`fmtUsdCell`). Capital + ITD PnL are click-to-edit number inputs (Enter/blur saves
via POST, Escape cancels, optimistic update). Computed rows get rule separators +
bolder weight; negative ITD PnL / Funding Balance render red.

## Edge cases

- VIP feed down → VIP row "—", treated as 0 in Total, with an inline note.
- Settings fetch fails → keep defaults, band stays usable.

## Deploy

- Edit BOTH copies of `TradeBookingForm.jsx` (middle-office-tools + trade-booking) for local-dev parity.
- Merge to `main` via worktree, version bump, push; user triggers pipeline deploy.
- Run `apply_schema_funding_settings.py` against each DB (UAT done; prod pending).

## Verification (done)

- Backend round-trip against UAT: schema applied; defaults; upsert (incl. negative);
  unknown-key + non-number rejected; reset to clean (capital 6,600,000 / itd_pnl 0).
- Frontend: esbuild transform parses clean; internal-borrow aggregation = 0 on UAT (correct).
- Pending: visual review of the rendered band on UAT after deploy.
