# TRANSFER Schema (trade-booking skill)

A transfer is a **movement** of an asset between two accounts. It changes where
a position sits and never touches P&L: it lives in its own table (`transfer`,
deal refs `MTR…`), which the P&L engine never reads. If money changed hands for
something (a fee, a purchase, income) that is a CASHFLOW or a SPOT, not a
transfer. If it just moved from one of our accounts to another, or between us
and a counterparty's wallet, it is a transfer.

One row carries **both ends**. The plugin's `validate_transfer_payload` and the
server's `transfer_db.validate_payload` enforce the same rules. Top-level keys
map 1:1 to the `transfer` columns.

## Which end is ours

| `transfer_type` | `direction` | `source_*` | `dest_*` |
|---|---|---|---|
| `INTERNAL` | `OUTGOING` (book from the sender) | ours (sender) | ours (receiver) |
| `EXTERNAL` | `OUTGOING` | ours | counterparty |
| `EXTERNAL` | `INCOMING` | counterparty | ours |

For an INTERNAL transfer book the leg from the **sender**: `OUTGOING`, amount
negative. The server books the INCOMING mirror on the receiver itself, so you
submit **one** payload and two MTR rows appear. Do not submit the mirror.

## Required fields

| Field | Type | Notes |
|---|---|---|
| `transfer_type` | enum | `INTERNAL` (both ends ours) or `EXTERNAL` (one end a counterparty). |
| `direction` | enum | `OUTGOING` / `INCOMING`, from the **source** account's point of view. |
| `source_account_name` | string | Ours: exact refdata account name (`TK801@BINANCE`). Counterparty: exact refdata counterparty name. |
| `source_product` | string | Ours: the gateway sub-account, **mandatory whenever the account offers a choice** and must be one of its options (`SPOT`, `FUNDING`, a chain for a wallet). Counterparty end: `null`. |
| `dest_account_name` | string | Same rule as source. |
| `dest_product` | string | Same rule as source. |
| `asset` | string | Ticker in refdata tokens. SPCXD on HyperCore is booked as `SPCX`. |
| `amount` | numeric string | **Signed by direction**: OUTGOING negative (`"-100"`), INCOMING positive. Never zero. |
| `initiated_datetime` | ISO 8601 + tz | When the transfer was sent. |
| `user_id` | string | Set by the plugin. |
| `status` | enum | `PENDING` / `CONFIRMED` / `COMPLETED` / `CANCELLED`. A draft is `PENDING`; approval confirms it. |

## Optional fields

| Field | Type | Notes |
|---|---|---|
| `source_account_id` / `dest_account_id` | string | Ours: leave `null`, the server stamps the gateway id from account + product. Counterparty end: the wallet address or venue reference, if the user gave one. |
| `completed_datetime` | ISO 8601 + tz | When it landed. Blank while in flight. |
| `fee_asset` / `fee_amount` | string / numeric string | Paid by the sender on top of `amount`. |
| `network` | string | Chain name (`HYPEREVM`, `ARBITRUM`, `BINANCE SMART CHAIN`) when it moved on chain; `null` for a venue-internal move. |
| `ext_transfer_id` | string | Tx hash or the venue's transfer id, if known. |
| `comment` | string | Free text. |
| `internal_journal` | `"Y"` or `null` | Only when the user says it is a book-keeping journal, not a real movement. |

`deal_ref` is allocated server-side. `portfolio` is **not** a column: a transfer
may cross portfolios, and each end's portfolio is read from its account's
refdata row.

## Reading a request

`transfer <amount> <asset> from <A> [<product>] to <B> [<product>]`

- `A` is the **source**, `B` the **destination**. "send", "move", "withdraw to",
  "top up B from A" all put the money's origin in source.
- Both `A` and `B` resolve to refdata accounts → `INTERNAL`, `OUTGOING`,
  `amount = -<amount>`.
- One of them is a counterparty (a client's wallet, an exchange we have no
  account on) → `EXTERNAL`; the counterparty side's name is the counterparty,
  its product `null`, its `*_account_id` whatever address the user gave.
- Account shorthand ("tk801binance", "hyperliquid06", "hl 06") goes through
  refdata exactly like a SPOT account. If it matches nothing or several,
  **ask** — never pick.
- "spot", "funding", "futures" next to an account name is its product. If the
  account offers several and none was named, **ask**.

## Validation order (plugin)

1. All required fields non-empty.
2. Enums: `transfer_type`, `direction`, `status`.
3. `amount` numeric, non-zero, sign matches direction; `fee_amount` numeric if set.
4. `asset` (and `fee_asset`) in refdata tokens.
5. Own end(s) in refdata accounts, with a `*_product` from that account's options
   wherever it offers any; counterparty end in refdata counterparties.
6. Same account on both ends only with two different products.
