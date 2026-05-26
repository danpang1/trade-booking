# Worked Examples

## Example 1 — Single OPEX

**User:** "book a 500 USDC OPEX payment to TOKKA TREASURY out of CDA"

**Skill behavior:**

1. Parse → `{cashflow_type: OPEX, direction: OUTGOING, amount: "500", asset: USDC, counterparty: TOKKA TREASURY, portfolio: CDA(8006)}`. Missing: `account`, `account_type`, `network`, `entity`.
2. Refdata lookup: `CDA` → `portfolio_id=8006`. Ask user: "Which account is this out of?" — present the chalk-list of accounts for portfolio 8006.
3. User answers: `TOKKA TREASURY WALLET` (chain: ETHEREUM).
4. Preview:

```
CASHFLOW · OPEX · OUTGOING
  amount:        500 USDC
  entity:        TOKKA LABS PTE LTD
  portfolio:     8006 (CDA)
  counterparty:  TOKKA TREASURY
  account:       TOKKA TREASURY WALLET (WALLET)
  network:       ETHEREUM
  value_date:    2026-05-26T12:00:00+00:00
```

5. Ask "Submit? (y/N)"; on `y`, shell out:

```bash
tokka-mo book <<'JSON'
{
  "cashflow_type": "OPEX",
  "direction": "OUTGOING",
  "entity": "TOKKA LABS PTE LTD",
  "portfolio_id": 8006,
  "portfolio_name": "CDA",
  "counterparty": "TOKKA TREASURY",
  "account": "TOKKA TREASURY WALLET",
  "account_type": "WALLET",
  "network": "ETHEREUM",
  "asset": "USDC",
  "amount": "500",
  "trade_date": "2026-05-26T12:00:00+00:00",
  "value_date": "2026-05-26T12:00:00+00:00",
  "user_id": "danny.pang",
  "status": "PENDING"
}
JSON
```

6. Report:
```
Draft #42 created (PENDING_REVIEW). Review at https://mo-tools.tokkalabs.com/pending
```

## Example 2 — 6-row batch from a Slack paste

**User pastes:**
```
funding in to 8006 from Galaxy: 100k USDC
funding in to 8006 from Galaxy: 200k USDC
funding in to 8006 from Galaxy: 50k USDT
OPEX outgoing from 8006: 10k USDC to OFFICE VENDOR
OPEX outgoing from 8006: 5k USDC to OFFICE VENDOR
INTEREST INCOME to 8006 from Galaxy: 2k USDC
```

**Skill behavior:**

1. Parse 6 cashflows. Identify `OFFICE VENDOR` isn't in refdata. **STOP and ask the user**: "OFFICE VENDOR isn't in counterparties. Should I use TOKKA TREASURY as a placeholder, or do you want to add OFFICE VENDOR first?"
2. User says: "Use TOKKA TREASURY for now."
3. Preview a 6-row table.
4. "Submit batch? (y/N)" — on `y`:

```bash
tokka-mo book-batch <<'JSON'
{"trades": [
  {"payload": {...row 1...}},
  {"payload": {...row 2...}},
  ...
]}
JSON
```

5. Report:
```
Batch a8b3-1234-... · 6 drafts created (#43, #44, #45, #46, #47, #48). Review at https://mo-tools.../pending
```

## Example 3 — Edge case: missing field

**User:** "book an outgoing transfer"

**Skill behavior:**

1. Identifies that direction=OUTGOING is the only thing known. cashflow_type, amount, asset, counterparty, portfolio, account all missing.
2. **Ask ONE round of batched questions** (not one at a time):
   > Need a few details to draft this:
   > - cashflow_type? (OPEX, TRANSFER FEES, INTER PTF FUNDING, ...)
   > - amount + asset? (e.g. "100 USDC")
   > - to whom? (counterparty)
   > - from which portfolio + account?
3. After answers, proceed to validation + preview as in Example 1.
