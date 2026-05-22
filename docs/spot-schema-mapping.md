# SPOT Form → Live JSON / `trades_spot` Schema Mapping

Last verified: 2026-05-19.

This is the canonical mapping between the SPOT form's React state
(`form.*` fields in `src/TradeBookingForm.jsx`) and the live JSON
payload built by `outputRecord` for the SPOT category. Used when:

- Building the submit payload (`outputRecord` SPOT branch in
  `src/TradeBookingForm.jsx:5625`).
- Designing the `trades_spot` Postgres table (not yet built — DDL
  pending). The key order below is the proposed column order; the
  future `scripts/apply_schema_spot.py` should mirror it.
- Adding new fields to the SPOT section — keep this table, the
  `outputRecord` builder, and (once it exists) the DDL in sync.

SPOT records are now **flat and schema-aligned** with the same
conventions used by `trades_cashflow` and `trades_loan`:

- Top-level keys map 1:1 to (future) column names — no nested
  `payload` block.
- DB column names: `deal_ref`, `txn_type`, `user_id`, `comment`,
  `txid_reference`, `account`, `account_type`, `portfolio_id`,
  `portfolio_name`, `counterparty_id`.
- Server-set columns (`effective_start`, `effective_end`) emitted as
  `null` placeholders so the wire JSON shape lines up 1:1 with the
  table for backend mapping.
- UI-only metadata (`attachments`) sits under `_meta` so the backend
  can strip it cleanly.

## Mapping table

Order matches the proposed DDL declaration order and the form's JSON
payload key sequence. Backend will be able to round-trip cleanly
without renaming or reordering.

| #  | Schema column / JSON key | Form field                  | UI label / location                                                                       |
| -- | ------------------------ | --------------------------- | ----------------------------------------------------------------------------------------- |
| 1  | `deal_ref`               | `form.trade_id`             | "Internal Trade Id" (Summary) — `MFX-` placeholder; numeric portion allocated server-side |
| 2  | `external_trade_id`      | `form.external_trade_id`    | "External Trade Id (optional)" (Summary) — `null` if blank                                |
| 3  | `txn_type`               | *(derived from category)*   | Always `'SPOT'` for this table                                                            |
| 4  | `direction`              | `form.spot_direction`       | LONG / SHORT toggle (Spot Details)                                                        |
| 5  | `entity`                 | *(derived from portfolio)*  | "Entity (auto from portfolio)" readonly (Summary) — pulled from `PORTFOLIOS[].entity`     |
| 6  | `portfolio_id`           | `form.portfolio`            | "Portfolio" picker (Summary) — emitted as string                                          |
| 7  | `portfolio_name`         | *(derived from portfolio)*  | Auto-read from `PORTFOLIOS` lookup                                                        |
| 8  | `counterparty`           | `form.counterparty`         | "Counterparty" picker (Summary) — `null` if blank                                         |
| 9  | `counterparty_id`        | *(derived)*                 | Immutable refdata id (`CID000001`…) via `formatCID(COUNTERPARTY_IDS[counterparty])`       |
| 10 | `account`                | `form.account_name`         | "Account Name" picker (Spot Details) — `null` if blank                                    |
| 11 | `account_type`           | `form.account_venue_type`   | "Account Type" dropdown (Spot Details) — `EXCHANGE / WALLET / BROKER`                     |
| 12 | `base_asset`             | `form.base_asset`           | "Base Asset" picker (Spot Details)                                                        |
| 13 | `base_amount`            | `form.base_amount`          | "Base Amount" (Spot Details) — `parseFloat`, defaults to `0`                              |
| 14 | `quote_asset`            | `form.quote_asset`          | "Quote Asset" picker (Spot Details)                                                       |
| 15 | `quote_amount`           | `form.quote_amount`         | "Quote Amount" (Spot Details) — `parseFloat`, defaults to `0`                             |
| 16 | `price`                  | `form.price`                | "Price" (Spot Details) — `parseFloat`, defaults to `0`; auto-linked to base/quote (below) |
| 17 | `fee_asset`              | `form.fee_asset`            | "Fee Asset" picker (Spot Details)                                                         |
| 18 | `fee_amount`             | `form.fee_amount`           | "Fee Amount" (Spot Details) — `parseFloat`, defaults to `0`                               |
| 19 | `trade_date`             | `form.trade_date`           | "Trade Date · UTC" (Summary)                                                              |
| 20 | `value_date`             | `form.value_date`           | "Value Date · UTC" (Summary)                                                              |
| 21 | `txid_reference`         | `form.tx_hash`              | "Tx Hash (optional)" (Spot Details) — `null` if blank                                     |
| 22 | `effective_start`        | *(server-set)*              | `NOW()` on insert; amendment time on new versions                                         |
| 23 | `effective_end`          | *(server-set)*              | `NULL` on insert; stamped on prior row at amendment                                       |
| 24 | `user_id`                | `form.created_by`           | "Created by" dropdown (Summary)                                                           |
| 25 | `status`                 | `form.status`               | "Status" dropdown (Summary)                                                               |
| 26 | `comment`                | `form.notes`                | "Free-form notes / comments" (Comments & Attachments)                                     |

Plus a non-schema `_meta` block carrying UI-only state:

| JSON key            | Form field          | Notes                                                            |
| ------------------- | ------------------- | ---------------------------------------------------------------- |
| `_meta.attachments` | `form.attachments`  | Drop-zone in Comments & Attachments — `_file` blob ref stripped  |

## Behaviours that affect the mapping

### Direction (LONG / SHORT)

SPOT uses a two-state directional toggle
(`src/TradeBookingForm.jsx:6900–6924`). There's no second leg or
mirror behaviour — a single record represents one side of the trade.
The `direction` value affects downstream interpretation (`base_asset`
is what you receive on LONG and what you deliver on SHORT) but the
JSON shape is identical either way.

### Base / quote / price auto-compute

`base_amount`, `quote_amount`, and `price` are linked via
`setSpotField` (`src/TradeBookingForm.jsx:5264`). The rule is
`base × price = quote`. Editing any one of the three derives the
remaining field; all three end up in the record regardless of which
one the user entered. Validation requires all three to be `> 0` and
`base_asset !== quote_asset` (`src/TradeBookingForm.jsx:5711–5718`).

### Account venue type

`account_type` selects which reference table `AccountPicker` filters
against. Valid keys are defined by the `ACCOUNT_VENUE_TYPES` constant
in `src/TradeBookingForm.jsx` (account data fetched at runtime from
`/refdata/accounts.json`, populated by `scripts/sync_accounts.py`):

| Key        | UI label   |
| ---------- | ---------- |
| `EXCHANGE` | Exchange   |
| `WALLET`   | Wallet     |
| `BROKER`   | Brokerage  |

Switching the venue type clears `account_name` to avoid a stale value
from another venue lingering (`src/TradeBookingForm.jsx:6970`).

### Deal-ref placeholder

`form.trade_id` is seeded by `genTradeId("SPOT")` which returns the
bare prefix `"MFX-"` (`src/TradeBookingForm.jsx:244–252`). The numeric
portion is allocated server-side from `trade_seq_spot` when the trade
is booked, so `deal_ref` is only meaningful in submitted records.

## Live JSON sample

```json
{
  "deal_ref": "MFX-",
  "external_trade_id": null,
  "txn_type": "SPOT",
  "direction": "LONG",
  "entity": "Tokka Labs",
  "portfolio_id": "8041",
  "portfolio_name": "Tokka Alpha",
  "counterparty": null,
  "counterparty_id": null,
  "account": "Binance · spot · tk006",
  "account_type": "EXCHANGE",
  "base_asset": "BTC",
  "base_amount": 0.5,
  "quote_asset": "USDT",
  "quote_amount": 35000,
  "price": 70000,
  "fee_asset": "USDT",
  "fee_amount": 17.5,
  "trade_date": "2026-05-19T08:42",
  "value_date": "2026-05-19T08:42",
  "txid_reference": null,
  "effective_start": null,
  "effective_end": null,
  "user_id": "peter",
  "status": "CONFIRMED",
  "comment": null,
  "_meta": { "attachments": [] }
}
```

## Schema source of truth

There is no `trades_spot` DDL yet — when written it should live at
`trade-booking/scripts/apply_schema_spot.py`, mirroring
`apply_schema_cashflow.py` for SCD2 conventions:

- `PRIMARY KEY (deal_ref, effective_start)`
- Amendments INSERT a new row with new `effective_start`; the prior
  row's `effective_end` is stamped to the amendment time
- "Live" = `effective_end IS NULL`
- `status` CHECK enforces `PENDING / CONFIRMED / PROCESSED / SETTLED / CANCELLED`
- `direction` CHECK enforces `LONG / SHORT`
- `trade_seq_spot` sequence starting at 1, formatted into the
  `MFX-<n>` deal_ref pattern at insert time

See `claude-memory/project_mo_db_bitemporal.md` for the broader
bitemporal convention.

## API contract (pending)

No SPOT endpoints exist yet. When implemented, they should mirror the
cashflow endpoints (`cashflow-schema-mapping.md` → API contract
section):

| Method | Route | Body | Success body |
| ------ | ----- | ---- | ------------ |
| POST | `/api/spot/insert` | `outputRecord` (object) | `rows[0]` is the inserted row with server-allocated `deal_ref` and `effective_start` |
| POST | `/api/spot/amend`  | `outputRecord` with `deal_ref` populated | `rows[0]` is the newly inserted live row |
| GET  | `/api/spot/recent?limit=N` | n/a | `rows` is the N most recent live rows ordered by `trade_date DESC` |
| GET  | `/api/spot/:deal_ref` | n/a | `rows[0]` is the live row for that deal_ref |
