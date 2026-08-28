# CASHFLOW Schema (v0.1)

The 14 required fields a CASHFLOW draft must carry. The plugin's local validator AND the server's `cashflow_db.validate_payload` enforce the same rules — if one fails, the other will too.

| Field | Type | Notes |
|---|---|---|
| `cashflow_type` | enum | One of: `INTER PTF FUNDING`, `RETAINER FEES`, `OPEX`, `OPEX - OTHER EXPENSE`, `OPEX - CONTRA ACC`, `OTHER INCOME`, `OTHER EXPENSE`, `TRANSFER FEES`, `TRADING FEES`, `TRADING REWARDS`, `STRATEGY TESTING EXPENSE`, `STRATEGY TESTING RETURNED`, `INTEREST EXPENSE`, `INTEREST INCOME`, `WITHHOLDING TAX`, `LOAN`, `LOAN REPAYMENT`, `MARGIN LOAN`, `MARGIN REPAYMENT` |
| `direction` | enum | `INCOMING` or `OUTGOING` |
| `entity` | string | Legal entity. Common values: `TOKKA LABS PTE LTD`, `ECHO CREEK LIMITED`, `IMAGINE LABS PTE LTD`, `NATIVE TECHNOLOGY LIMITED`, `RANGE PROTOCOL LIMITED` |
| `portfolio_id` | int | Must match an `id` in `tokka-mo refdata` |
| `portfolio_name` | string | Must match the name of `portfolio_id`'s row in `tokka-mo refdata` |
| `counterparty` | string | Must match a `name` in `tokka-mo refdata`. Mandatory — if the vendor isn't catalogued, ask the user; never fall back to `TOKKA TREASURY` |
| `account` | string | Must match an `account` name in `tokka-mo refdata` (e.g. `TK006@BINANCE`) |
| `account_type` | enum | `EXCHANGE`, `WALLET`, `BROKER`, or `BANK` |
| `asset` | string | Must match a `symbol` in `tokka-mo refdata` (e.g. `USDC`) |
| `amount` | numeric string | Positive magnitude. Server derives signed amount from `direction` |
| `trade_date` | ISO 8601 + tz | When the booking is recorded (typically "now") |
| `value_date` | ISO 8601 + tz | When the value moves (typically "now" or T+1) |
| `user_id` | string | Set automatically by the plugin from the logged-in username |
| `status` | enum | `PENDING`, `CONFIRMED`, `PROCESSED`, `SETTLED`, `CANCELLED`. Default `PENDING` for drafts. |

## Optional fields

| Field | Type | Notes |
|---|---|---|
| `network` | enum | Uppercase chain name (`ETHEREUM`, `BASE`, `ARBITRUM`, ...). Required if `account_type=WALLET` |
| `tx_hash` | string | 0x-prefixed 64-hex if known. EVM networks only |
| `comment` | string | Free-text |

## Where values come from

- `portfolio_id` / `portfolio_name`: `refdata.portfolios`
- `counterparty`: `refdata.counterparties`
- `account`: `refdata.accounts`
- `asset`: `refdata.tokens`
- `user_id`: `tokka-mo whoami` (auto)
- `cashflow_type` / `direction` / `status` / `account_type`: enums in this doc — NOT from refdata

## Validation order

The plugin validates in this order (fail fast):
1. All 14 required fields non-empty
2. Enum membership
3. Amount non-zero, parses as float
4. Dates parse as ISO 8601 with timezone
5. Refdata-bound fields (portfolio, counterparty, account, asset) match cache

Both client and server validate. The client catches typos before a round-trip; the server is the source of truth.
