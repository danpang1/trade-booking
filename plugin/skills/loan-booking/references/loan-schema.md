# Loan schema and worked examples

## trades_loan — the facility (MLA)

Mandatory on insert:

| Field | Type | Values |
|---|---|---|
| `direction` | enum | `BORROW`, `LEND` |
| `loan_type` | enum | `EXTERNAL`, `INTERNAL`, `VIP LOAN`, `DEFI LENDING` |
| `entity` | string | booking entity, must be in refdata |
| `portfolio_id` | int | must exist in refdata |
| `portfolio_name` | string | must match `portfolio_id` exactly |
| `counterparty` | string | must be in refdata (**required by this skill**, not by the server) |
| `principal_asset` | string | token symbol from refdata |
| `principal_amount` | numeric | > 0 |
| `interest_asset` | string | token symbol; usually equals `principal_asset` |
| `interest_type` | enum | `FIXED`, `FLOATING` |
| `trade_date` | ISO 8601 | must carry a timezone |
| `status` | enum | `LIVE`, `MATURED`, `CANCELLED` — `LIVE` for a new facility |

Optional: `interest_rate_pa_pct`, `maturity_date`, `day_count_basis` (360 or
365, defaults 365), `floating_benchmark`, `wht_pct`, `order_id`, `comment`,
`is_hedged` and the `hedged_*` / `hedge_proceeds_*` fields,
`collateral_asset` / `collateral_amount`.

The table is bitemporal (SCD Type 2): PK is `(deal_ref, effective_start)`, and
the live row is the one with `effective_end IS NULL`. Amending supersedes
rather than overwrites, so nothing is ever really deleted — which is why an
MLA created by mistake stays visible as a `CANCELLED` row forever.

## loan_cashflow_map — the link

Plain many-to-many: one cashflow can serve several loans, one loan has many
cashflows. PK `(loan_deal_ref, cashflow_deal_ref)`. **Not** bitemporal — the
mapping is a snapshot of what is currently linked, and re-writing a cashflow's
mappings replaces the whole set for that cashflow.

Written only from the cashflow side, via `_meta.loan_deal_refs`. There is no
"add a cashflow to this loan" operation from the loan side.

Refs must match `MLA\d{8}` and resolve to a **live** loan row. Both are checked
inside the same transaction as the cashflow write.

## Worked examples

### Repayment against a known facility

> "repay 500k USDC to Kraken on the Feb facility"

```bash
python <cli> loan-list --counterparty KRAKEN --asset USDC
```

Then one CASHFLOW draft:

```json
{
  "txn_type": "CASHFLOW",
  "cashflow_type": "LOAN REPAYMENT",
  "direction": "OUTGOING",
  "entity": "TOKKA LABS PTE LTD",
  "portfolio_id": 8888,
  "portfolio_name": "TOKKA LABS - TREASURY",
  "counterparty": "KRAKEN",
  "account": "<from refdata>",
  "account_type": "BANK",
  "asset": "USDC",
  "amount": "500000",
  "trade_date": "2026-09-01T00:00:00Z",
  "value_date": "2026-09-01T00:00:00Z",
  "status": "CONFIRMED",
  "user_id": "CLAUDE:danny.pang",
  "_meta": { "loan_deal_refs": ["MLA00000412"] }
}
```

Direction is `OUTGOING`: money we repay leaves us. A drawdown would be
`cashflow_type: "LOAN"` and `INCOMING`.

### Interest on an existing loan

Same shape, `cashflow_type: "INTEREST EXPENSE"`, `direction: "OUTGOING"`,
tagged to the same MLA. The mapping is typed `INTEREST` automatically, so
principal and interest stay distinguishable against one facility.

### New facility drawn the same day

Loan first — this is the irreversible step, and it needs an explicit yes:

```bash
echo '{ ...loan payload... }' | python <cli> loan-open --dry-run   # validate
echo '{ ...loan payload... }' | python <cli> loan-open --yes       # writes it
# -> Loan MLA00000584 created and LIVE.
```

Then the drawdown cashflow with `"_meta": {"loan_deal_refs": ["MLA00000584"]}`
and `cashflow_type: "LOAN"`, `direction: "INCOMING"`.

If that second step fails, the facility exists with nothing drawn against it.
Report it and let the operator decide — do not re-run `loan-open`, which would
create a second facility.

## Direction cheat-sheet

| Event | cashflow_type | direction |
|---|---|---|
| We draw down money we borrowed | `LOAN` | `INCOMING` |
| We repay principal | `LOAN REPAYMENT` | `OUTGOING` |
| We pay interest | `INTEREST EXPENSE` | `OUTGOING` |
| We lend money out | `LOAN` | `OUTGOING` |
| A borrower repays us | `LOAN REPAYMENT` | `INCOMING` |
| We receive interest | `INTEREST INCOME` | `INCOMING` |

`LOAN` and `LOAN REPAYMENT` cut both ways — the same type is used for lending
and borrowing, so the direction is settled by the MLA's `direction`, not by the
cashflow type. On a `BORROW` facility a repayment is money leaving; on a `LEND`
facility it is money arriving.
