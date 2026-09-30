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
Draft #42 created (PENDING_REVIEW). Review at https://sg-tms.internal.tokkalabs.com/pending
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

## Example 4 — Single SPOT swap

**User:** "Swap 1,000,000 USDC to 1,000,000 USDG on Paxos @ 1.00 for PTF 8888"

**Skill behavior:**

1. Parse with the swap rule (received = base, LONG): `base_asset=USDG`,
   `base_amount=1000000`, `quote_asset=USDC`, `quote_amount=1000000`, `price=1.00`,
   `direction=LONG`. Venue "Paxos" → account `MOON-TK@PAXOS` (EXCHANGE). Portfolio
   8888 → `portfolio_name=TOKKA LABS - TREASURY`, entity auto-filled.
2. Check `base × price == quote` (1,000,000 × 1.00 = 1,000,000 ✓).
3. Preview:

```
SPOT · LONG · PTF 8888 (TOKKA LABS - TREASURY)
  base:     1,000,000 USDG   (received)
  quote:    1,000,000 USDC   (given)
  price:    1.00 USDC/USDG
  account:  MOON-TK@PAXOS (EXCHANGE)
  value_date: 2026-06-30T12:00:00+00:00
```

4. "Submit? (y/N)"; on `y`:

```bash
${CLAUDE_PLUGIN_ROOT}/bin/tokka-mo book --category SPOT <<'JSON'
{
  "direction": "LONG",
  "entity": "TOKKA LABS PTE LTD",
  "portfolio_id": 8888,
  "portfolio_name": "TOKKA LABS - TREASURY",
  "base_asset": "USDG",
  "base_amount": "1000000",
  "quote_asset": "USDC",
  "quote_amount": "1000000",
  "price": "1.00",
  "account": "MOON-TK@PAXOS",
  "account_type": "EXCHANGE",
  "trade_date": "2026-06-30T12:00:00+00:00",
  "value_date": "2026-06-30T12:00:00+00:00",
  "user_id": "danny.pang",
  "status": "PENDING"
}
JSON
```

## Example 5 — Mixed CASHFLOW + SPOT batch

**User pastes:**
```
PTF 8888 fund PTF 8041 2,000,000 USDT
Swap 1,000,000 USDC to 1,000,000 USD on Paxos @ 1.00
Swap 1,000,000 USDC to 1,000,000 USDG on Paxos @ 1.00
```

**Skill behavior:**

1. Tag each row: row 1 = CASHFLOW (INTER PTF FUNDING — books two legs); rows 2-3 =
   SPOT swaps. Resolve venues/portfolios; ask for any missing account/portfolio.
2. Preview grouped:

```
CASHFLOW (2)
  1. INTER PTF FUNDING · OUTGOING · 8888 → cp 8041 · 2,000,000 USDT
  2. INTER PTF FUNDING · INCOMING · 8041 → cp 8888 · 2,000,000 USDT
SPOT (2)
  3. LONG · base 1,000,000 USD  / quote 1,000,000 USDC @ 1.00 · Paxos
  4. LONG · base 1,000,000 USDG / quote 1,000,000 USDC @ 1.00 · Paxos
```

3. "Submit batch? (y/N)"; on `y`, each trade carries its own `category`:

```bash
${CLAUDE_PLUGIN_ROOT}/bin/tokka-mo book-batch <<'JSON'
{"trades": [
  {"category": "CASHFLOW", "payload": {...funding OUTGOING...}},
  {"category": "CASHFLOW", "payload": {...funding INCOMING...}},
  {"category": "SPOT",     "payload": {...USDC→USD swap...}},
  {"category": "SPOT",     "payload": {...USDC→USDG swap...}}
]}
JSON
```

4. Report the single `batch_id` + all draft IDs + the review URL.


## Example — TRANSFER between our accounts

**User:** "transfer 100 USDT from tk801 binance spot to hyperliquid 06 spot"

**Skill behavior:**

1. Both ends resolve to refdata accounts (`TK801@BINANCE`, `TRADING_06@HYPERLIQUID`)
   → `INTERNAL`, booked from the sender: `OUTGOING`, `amount = "-100"`.
   Both accounts offer several products and the user named `spot` on each,
   so `source_product = dest_product = SPOT`. Nothing to ask.
2. Preview:

```
TRANSFER · INTERNAL · OUTGOING
  source:        TK801@BINANCE · SPOT
  destination:   TRADING_06@HYPERLIQUID · SPOT
  amount:        -100 USDT
  initiated:     2026-09-30T08:00:00+00:00
  status:        PENDING
  (the server books the INCOMING mirror on TRADING_06@HYPERLIQUID)
```

3. Ask "Submit? (y/N)"; on `y`:

```bash
echo '{"transfer_type":"INTERNAL","direction":"OUTGOING","source_account_name":"TK801@BINANCE","source_product":"SPOT","dest_account_name":"TRADING_06@HYPERLIQUID","dest_product":"SPOT","asset":"USDT","amount":"-100","initiated_datetime":"2026-09-30T08:00:00+00:00","user_id":"danny.pang","status":"PENDING"}' | ${CLAUDE_PLUGIN_ROOT}/bin/tokka-mo book --category TRANSFER
```

4. Report `Draft #<id> created (PENDING_REVIEW)` and the review URL. Two MTR
   rows exist once approved: the OUTGOING leg on TK801@BINANCE and its INCOMING
   mirror on TRADING_06@HYPERLIQUID.

**Variant — to a counterparty's wallet:** "send 5,000 USDC from
TOKKA TREASURY WALLET on Ethereum to Galaxy 0xabc…" → `EXTERNAL`, `OUTGOING`,
`source_account_name = TOKKA TREASURY WALLET`, `source_product = ETHEREUM`,
`dest_account_name = GALAXY` (exact refdata counterparty), `dest_product = null`,
`dest_account_id = "0xabc…"`, `network = ETHEREUM`, `amount = "-5000"`.
