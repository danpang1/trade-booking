# SPOT Schema (trade-booking skill)

The fields a SPOT draft must carry. The plugin's local validator
(`validate_spot_payload`) AND the server's `spot_db.validate_payload` enforce the
same core rules — if one fails, the other will too. Top-level keys map 1:1 to the
`trades_spot` columns (no nested `payload` block).

## Required fields

| Field | Type | Notes |
|---|---|---|
| `direction` | enum | `LONG` or `SHORT`. Swap "give A, receive B" ⇒ LONG, base = received asset (B). |
| `entity` | string | Auto-filled from the portfolio's refdata row — don't ask the user. |
| `portfolio_id` | int | User-facing PTF **number** (e.g. 8041). Must match a portfolio in refdata. |
| `portfolio_name` | string | Must match the name of `portfolio_id`'s refdata row. |
| `base_asset` | string | Ticker; must be a `symbol` in refdata tokens. The asset you receive on LONG. |
| `base_amount` | numeric string | Amount of base. `> 0`. |
| `quote_asset` | string | Ticker; must be in refdata tokens. Must differ from `base_asset`. |
| `quote_amount` | numeric string | Amount of quote. `base_amount × price == quote_amount`. |
| `price` | numeric string | Quote per base. For a 1:1 stablecoin swap, `1.0`. |
| `trade_date` | ISO 8601 + tz | When the booking is recorded (typically "now"). |
| `value_date` | ISO 8601 + tz | When value moves (typically "now" or T+1). |
| `user_id` | string | Set automatically by the plugin from the logged-in username. |
| `status` | enum | `PENDING` / `CONFIRMED` / `PROCESSED` / `SETTLED` / `CANCELLED`. Default `PENDING`. |

## Optional fields

| Field | Type | Notes |
|---|---|---|
| `account` | string | Refdata account name (e.g. `MOON-TK@PAXOS`). Omit if unknown. |
| `account_type` | enum | `EXCHANGE` / `WALLET` / `BROKER`. Required only when `account` is set. |
| `counterparty` | string | NAMED counterparty in refdata (NOT a portfolio number). Omit if none. |
| `counterparty_id` | string | Derived from `counterparty`; leave to the form/server. |
| `fee_asset` | string | Ticker in refdata tokens, if a fee applies. |
| `fee_amount` | numeric string | Fee magnitude. |
| `external_trade_id` | string | Venue's trade id, if known. |
| `txid_reference` | string | 0x tx hash for on-chain settlement, if known. |
| `comment` | string | Free-text. |

`txn_type` is NOT sent — the server defaults it to `SPOT`. `deal_ref` (`MFX-<n>`)
is allocated server-side at insert.

## Swap mapping rule (canonical)

`Swap <amtA> <A> to <amtB> <B> [on <venue>] [@ <price>]`:

- `direction = LONG`
- `base_asset = B`, `base_amount = amtB` (received)
- `quote_asset = A`, `quote_amount = amtA` (given)
- `price` = quote-per-base; derive `amtA / amtB` if omitted
- Identity: `base_amount × price == quote_amount`

`buy X at P` ⇒ LONG, base = X. `sell X at P` ⇒ SHORT, base = X.

## Validation order (plugin)

1. All required fields non-empty.
2. `direction` ∈ {LONG, SHORT}; `status` ∈ valid statuses.
3. `base_amount`, `quote_amount`, `price` (and `fee_amount` if set) numeric.
4. `base_asset != quote_asset`; `portfolio_id` is an integer.
5. `base_amount × price == quote_amount` (small relative tolerance).
6. Refdata: `portfolio_id`/`portfolio_name`, `base_asset`/`quote_asset`/`fee_asset`
   ∈ tokens; `account` + `account_type` and `counterparty` only when present.
