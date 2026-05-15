# Cashflow Form → `trades_cashflow` Schema Mapping

Last verified: 2026-05-14.

This is the canonical mapping between the Cashflow form's React state
(`form.*` fields in `src/TradeBookingForm.jsx`) and the UAT Postgres
`trades_cashflow` table columns. Used when:

- Building the submit payload (`outputRecord` in `TradeBookingForm.jsx`).
- Designing INSERTs against `trades_cashflow`.
- Adding new fields — keep this table and the DDL
  (`trade-booking/scripts/apply_schema_cashflow.py`) in sync.

## Mapping table

Order matches both the DDL declaration order and the form's JSON payload
key sequence. Backend can round-trip cleanly without renaming or reordering.

| #  | Schema column       | Form field                        | UI label / location                                                                   |
| -- | ------------------- | --------------------------------- | ------------------------------------------------------------------------------------- |
| 1  | `deal_ref`          | `form.trade_id`                   | "Internal Trade Id" (Summary) — shows `MCF-` placeholder; backend allocates on submit |
| 2  | `external_trade_id` | `form.external_trade_id`          | "External Trade Id (optional)" (Summary)                                              |
| 3  | `txn_type`          | *(derived from `form.category`)*  | Always `'CASHFLOW'` for this table                                                    |
| 4  | `cashflow_type`     | `form.cf_type`                    | "Cashflow Type" (Cashflow Details)                                                    |
| 5  | `direction`         | `form.cf_direction`               | PAY/RECEIVE toggle (Cashflow Details)                                                 |
| 6  | `entity`            | *(derived from `form.portfolio`)* | "Entity (auto from portfolio)" readonly (Summary)                                     |
| 7  | `portfolio_id`      | `form.portfolio`                  | "Portfolio" picker (Summary)                                                          |
| 8  | `portfolio_name`    | *(derived from `form.portfolio`)* | Auto-read from `PORTFOLIOS` lookup                                                    |
| 9  | `counterparty`      | `form.counterparty`               | "Counterparty" picker (Summary) — see Mirror Trade caveat below                       |
| 10 | `account`           | `form.account_name`               | "Account Name" picker (Cashflow Details)                                              |
| 11 | `account_type`      | `form.account_venue_type`         | "Account Type" dropdown (Cashflow Details) — EXCHANGE / WALLET / BROKERAGE            |
| 12 | `asset`             | `form.cf_asset`                   | "Notional Asset" picker (Cashflow Details)                                            |
| 13 | `amount`            | `form.cf_amount`                  | "Notional Amount" (Cashflow Details)                                                  |
| 14 | `fee_asset`         | `form.fee_asset`                  | "Fee Asset" picker (Cashflow Details)                                                 |
| 15 | `fee_amount`        | `form.fee_amount`                 | "Fee Amount" (Cashflow Details)                                                       |
| 16 | `trade_date`        | `form.trade_date`                 | "Trade Date · UTC" (Summary)                                                          |
| 17 | `value_date`        | `form.value_date`                 | "Value Date · UTC" (Summary)                                                          |
| 18 | `network`           | `form.network`                    | "Network" dropdown (Cashflow Details)                                                 |
| 19 | `txid_reference`    | `form.tx_hash`                    | "Tx Hash (optional)" (Cashflow Details)                                               |
| 20 | `effective_start`   | *(server-set)*                    | `NOW()` on insert; amendment time on new versions                                     |
| 21 | `effective_end`     | *(server-set)*                    | `NULL` on insert; stamped on prior row at amendment                                   |
| 22 | `user_id`           | `form.created_by`                 | "Created by" dropdown (Summary)                                                       |
| 23 | `status`            | `form.status`                     | "Status" dropdown (Summary)                                                           |
| 24 | `comment`           | `form.notes`                      | "Free-form notes / comments" textarea (Comments & Attachments)                        |

## Two behaviours that affect the mapping

### 1. INTER PTF FUNDING — Counterparty picker swaps

When `cf_type === "INTER PTF FUNDING"`, the **Counterparty** field in
the Summary renders a `PortfolioPicker` (showing other portfolios)
instead of the regular `CounterpartyPicker`. The selected value stored
in `form.counterparty` is the **portfolio number** (string), not a
counterparty name. Downstream code reading `counterparty` needs to
look at `cashflow_type` to know how to interpret the value.

For all other `cf_type` values, `form.counterparty` is a real
counterparty name from the `COUNTERPARTIES` reference list.

### 2. INTER PTF FUNDING + Mirror Trade — emits TWO records

When `cf_type === "INTER PTF FUNDING"` **and** the "Mirror Trade"
checkbox is ticked, `outputRecord` returns a **2-element array** in
the order `[leg_1, leg_2]`, where:

- **Leg 1** = the form as filled in (portfolio sends, counterparty
  portfolio receives). `payload.mirror_leg = 1`.
- **Leg 2** = the offsetting record on the counterparty portfolio:
  `portfolio` ↔ `counterparty` swapped, `direction` flipped
  (PAY ↔ RECEIVE), `account_name` and `account_venue_type` nulled
  (leg 2 belongs to the other portfolio whose account isn't captured
  in this form). `payload.mirror_leg = 2`.

Backend should INSERT both rows in a single transaction and let the
`trade_seq_cashflow` sequence allocate distinct `deal_ref` values for
each leg.

## Schema source of truth

DDL lives at `trade-booking/scripts/apply_schema_cashflow.py`. The
table follows the bitemporal SCD Type 2 convention documented in
`claude-memory/project_mo_db_bitemporal.md`:

- `PRIMARY KEY (deal_ref, effective_start)`
- Amendments INSERT a new row with new `effective_start`; the prior
  row's `effective_end` is stamped to the amendment time
- "Live" = `effective_end IS NULL`
- `status` CHECK enforces `PENDING / CONFIRMED / PROCESSED / SETTLED / CANCELLED`

## API contract

The frontend posts the JSON payload built by `outputRecord` (this
mapping) to one of four endpoints on the trade-booking Node server
(port 5181). All endpoints return `{ok: true, rows: [...]}` on success
or `{ok: false, error: "..."}` on failure.

| Method | Route | Body | Success body |
| ------ | ----- | ---- | ------------ |
| POST | `/api/cashflow/insert` | `outputRecord` (object, or 2-element array for mirror-leg) | `rows` has 1 or 2 elements, each is the inserted row with server-allocated `deal_ref` and `effective_start` |
| POST | `/api/cashflow/amend` | `outputRecord` with `deal_ref` populated (object only) | `rows[0]` is the newly inserted live row |
| GET | `/api/cashflow/recent?limit=N` | n/a | `rows` is the N most recent live rows ordered by `trade_date DESC` |
| GET | `/api/cashflow/:deal_ref` | n/a | `rows[0]` is the live row for that deal_ref |

Error HTTP statuses:

- 400 — payload validation failure
- 404 — `deal_ref` not found / no live row
- 409 — concurrent amend (`{ok: false, error: "...", code: "conflict"}`)
- 500 — server/DB error

Implementation lives in `trade-booking/scripts/cashflow_*.py` (one
script per endpoint, all sharing `cashflow_db.py`). See the
[design spec](../../docs/superpowers/specs/2026-05-15-cashflow-booking-backend-design.md)
for SCD2 transaction logic and concurrency reasoning.
