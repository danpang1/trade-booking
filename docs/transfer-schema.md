# trades_transfer — schema and conventions

A **transfer** is a movement of an asset from one account to another. It changes
*where* a position sits, never P&L. It has its own table so the P&L engine, which
reads `trades_cashflow`, never sees one: "transfers do not affect P&L" is a
property of where the row lives, not a type someone has to remember to exclude.

The pairing with P&L: a trading fee is a `TRADING FEES` **cashflow** (P&L); the
money leaving the account to pay it is an `EXTERNAL` **transfer** (settlement).

Column order approved 2026-09-28. DDL: `scripts/apply_schema_transfer.py`.

| # | column | type | notes |
|---|---|---|---|
| 1 | `id` | BIGINT identity | PK |
| 2 | `deal_ref` | TEXT NOT NULL | `MTR` + 8 digits from `trade_seq_transfer`, DB-assigned |
| 3 | `transfer_type` | TEXT NOT NULL | `INTERNAL` \| `EXTERNAL` |
| 4 | `direction` | TEXT NOT NULL | `INCOMING` \| `OUTGOING` |
| 5 | `source_account_name` | TEXT NOT NULL | |
| 6 | `source_product` | TEXT | SPOT / FUNDING / chain; NULL for a counterparty |
| 7 | `source_account_id` | TEXT | gateway id (ours) or wallet address / venue ref (counterparty) |
| 8 | `dest_account_name` | TEXT NOT NULL | |
| 9 | `dest_product` | TEXT | |
| 10 | `dest_account_id` | TEXT | |
| 11 | `asset` | TEXT NOT NULL | |
| 12 | `amount` | NUMERIC(36,18) NOT NULL | signed: INCOMING +, OUTGOING − |
| 13 | `fee_asset` | TEXT | |
| 14 | `fee_amount` | NUMERIC(36,18) | default 0; paid by the source on top of `amount` |
| 15 | `initiated_datetime` | TIMESTAMPTZ NOT NULL | |
| 16 | `completed_datetime` | TIMESTAMPTZ | NULL until it lands |
| 17 | `network` | TEXT | |
| 18 | `ext_transfer_id` | TEXT | tx hash or the venue's transfer id; partial index |
| 19 | `effective_start` | TIMESTAMPTZ NOT NULL | SCD Type 2 |
| 20 | `effective_end` | TIMESTAMPTZ | |
| 21 | `user_id` | TEXT NOT NULL | Created By — never changes |
| 22 | `status` | TEXT NOT NULL | PENDING / CONFIRMED / COMPLETED / CANCELLED |
| 23 | `comment` | TEXT | |
| 24 | `updated_by` | TEXT | who made this version |

Unique `(deal_ref, effective_start)`.

## Which end is ours

Read from `transfer_type` + `direction`, never from a name lookup:

| transfer_type | direction | source | dest |
|---|---|---|---|
| INTERNAL | OUTGOING (always) | ours | ours |
| EXTERNAL | OUTGOING | ours | counterparty |
| EXTERNAL | INCOMING | counterparty | ours |

An `INTERNAL` transfer is booked from the source's point of view: `OUTGOING`,
amount negative; the destination gains `|amount|`. Both ends must be in the same
portfolio (the form filters the pickers); a movement between portfolios is an
`INTER PTF FUNDING` cashflow, not a transfer. The same account at both ends is
allowed only with two different products (spot → funding, chain A → chain B).

The counterparty end's name must be a refdata counterparty; our end's name a
refdata account. The validator refuses an amount whose sign disagrees with the
direction.

## What is not on the row

* **No portfolio.** Access control scopes every other book on `portfolio_id`;
  with nothing to scope on, `/api/transfer/*` is **admin-only**
  (`serverScope.mjs`). Deal Enquiry treats a 403 from the transfer feed as
  "none" for a non-admin. To lift this, derive portfolio from the own-side
  account at query time.
* **No tech-DB mirror.** `manual_trade` / `manual_cashflow` feed the position
  service; a transfer is neither, and there is no `manual_transfer` table yet.
  Every insert logs this to stderr.
* **No bulk edit.** Transfer rows cannot be selected in Deal Enquiry's bulk
  editor; amend one at a time.

## API

Same shape as the other books, on `/api/transfer/{insert,amend,recent,:deal_ref,:deal_ref/history}`.
Rows come back with read-only aliases so Deal Enquiry can render them in the
shared table: `txn_type = "TRANSFER"`, `trade_date` / `value_date` (initiated /
completed), `account` (our end, with product), `counterparty` (the far end). The
form loads from the real columns, never the aliases.
