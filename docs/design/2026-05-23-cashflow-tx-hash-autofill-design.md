# Cashflow Form — Autofill from On-Chain TX Hash

**Date:** 2026-05-23
**Status:** Approved (brainstorming complete, ready for implementation plan)
**Scope:** Add a "Fetch" button next to the `tx_hash` field on the cashflow booking form. When the user pastes an EVM transaction hash and clicks Fetch, the backend calls Goldrush (Covalent), parses the transaction, and auto-fills the empty cashflow fields (asset, amount, gas fee, gas asset, dates).

---

## 1. Motivation

Cashflow bookings today are typed entirely by hand. For every on-chain deposit, withdrawal, fee, or transfer, the user has to:

- Look up the tx on a block explorer
- Read off the asset, the amount (with the right decimals applied)
- Compute gas fee = `gas_used × gas_price`
- Copy timestamps

This is slow and error-prone — wrong decimals, fat-finger amounts, wrong gas asset. Pulling the data straight from chain via Goldrush removes those errors and turns ~30 seconds of typing into one click.

---

## 2. Decisions taken during brainstorming

| Decision | Choice | Rationale |
|---|---|---|
| Which forms get this v1 | Cashflow only | Cashflow is the form most tied to on-chain activity; prove it works here first, expand later if useful |
| Chain coverage | EVM-only via Goldrush (~25 chains) | Goldrush has a single unified endpoint for all EVM chains; non-EVM (Solana, Tron, BTC, etc.) needs separate providers — defer until actually needed |
| UX trigger | Inline "Fetch" button next to the `tx_hash` field | Matches existing form style; explicit click is predictable and doesn't fire on accidental paste |
| Multi-transfer rule | Auto-fill if exactly one transfer (or native-only); show an inline picker if multiple | Most real cashflows are single-transfer; the picker handles batch sends and contract interactions without silently picking wrong |
| Overwrite policy | Empty-only — never clobber a value the user already typed | Trust user input over chain inference; user can clear a field manually if they want it refetched |
| Counterparty / direction inference | Don't attempt | No wallet-address → counterparty registry exists in refdata; guessing would be wrong often enough to lose trust |
| Caching | None | Goldrush rate limits are generous; user fetches once per booking |

Out of scope for v1 (worth revisiting later):
- Non-EVM chains (Solana, Tron, BTC, TON, etc.)
- Wallet-address → counterparty / portfolio auto-resolution (would need a new refdata table)
- Direction (INCOMING / OUTGOING) inference
- Extending to SPOT, FUTURE, LOAN forms
- Caching of fetched txs
- Background "verify hash matches typed amounts" check

---

## 3. Backend

### New script: `scripts/cashflow_tx_fetch.py`

Follows the existing spawn-Python pattern (stdin JSON in, stdout JSON out, non-zero exit on error).

**Input (stdin):**
```json
{ "tx_hash": "0x…", "network": "ETHEREUM" }
```

**Behavior:**
1. Validate `tx_hash` is `0x` + 64 hex chars and `network` is in the EVM allowlist (see §3.1). Bad input → exit 2, `{ok:false, error:"invalid input", detail:"…"}`.
2. Map our network name → Goldrush chain name (table in §3.1).
3. Call Goldrush:
   ```
   GET https://api.covalenthq.com/v1/{chain_name}/transaction_v2/{tx_hash}/
   Authorization: Bearer {GOLDRUSH_API_KEY}
   ```
4. Parse the response:
   - `gas_fee = (gas_spent * gas_price) / 10^18`, expressed as a string-decimal to preserve precision
   - `gas_asset` = native asset of the chain (lookup from network)
   - `timestamp` = `block_signed_at`
   - `transfers` = list of `{asset, amount, from, to, decimals, contract_address}` derived from `log_events` with `decoded.name == "Transfer"` and standard ERC-20 signature. Amount = `raw / 10^decimals` as a string-decimal.
   - If `transfers` is empty AND tx `value > 0`, synthesize a single native transfer: `{asset: gas_asset, amount: value/10^18, from: tx.from_address, to: tx.to_address, decimals: 18, contract_address: null}`.
5. Return:
   ```json
   {
     "ok": true,
     "transfers": [ {asset, amount, from, to, decimals, contract_address}, … ],
     "gas_fee": "0.001234",
     "gas_asset": "ETH",
     "timestamp": "2026-05-23T10:15:32Z",
     "block_number": 19234567,
     "tx_from": "0x…",
     "tx_to": "0x…"
   }
   ```

**Error shapes** (non-zero exit code, `{ok:false, error, detail?}`):
- Invalid hash / unsupported network → exit 2, `error:"invalid input"`
- Tx not found (Goldrush 404 or null data) → exit 4, `error:"tx not found"` — frontend renders "Not found on {network} — wrong network?"
- Goldrush 5xx / network error → exit 5, `error:"upstream unavailable"` — frontend renders "Couldn't reach chain explorer, try again"
- Missing `GOLDRUSH_API_KEY` env → exit 6, `error:"server misconfigured"` — frontend renders generic error and logs server-side
- No transfers and no native value → exit 7, `error:"no transfers"` — frontend renders "No transfers found in this tx"

### 3.1 Network → Goldrush chain mapping

The 25 EVM chains we support, mapped to Goldrush chain names. Lives as a dict at the top of `cashflow_tx_fetch.py`. Non-EVM networks are NOT in this map and trigger the unsupported-network error.

| Our `network` | Goldrush `chain_name` | Native asset |
|---|---|---|
| ETHEREUM | eth-mainnet | ETH |
| BINANCE SMART CHAIN | bsc-mainnet | BNB |
| POLYGON | matic-mainnet | MATIC |
| ARBITRUM | arbitrum-mainnet | ETH |
| OPTIMISM | optimism-mainnet | ETH |
| BASE | base-mainnet | ETH |
| AVALANCHE | avalanche-mainnet | AVAX |
| LINEA | linea-mainnet | ETH |
| SCROLL | scroll-mainnet | ETH |
| MANTLE | mantle-mainnet | MNT |
| BLAST | blast-mainnet | ETH |
| MODE | mode-mainnet | ETH |
| CELO | celo-mainnet | CELO |
| ZKSYNC | zksync-mainnet | ETH |
| SONIC | sonic-mainnet | S |
| GNOSIS | gnosis-mainnet | xDAI |
| BERACHAIN | berachain-mainnet | BERA |
| HYPEREVM | hyperevm-mainnet | HYPE |
| UNICHAIN | unichain-mainnet | ETH |
| SONEIUM | soneium-mainnet | ETH |
| ZETA | zetachain-mainnet | ZETA |
| PLASMA | plasma-mainnet | XPL |
| TEMPO | tempo-mainnet | TEMPO |
| SAGAEVM | sagaevm-mainnet | SAGA |
| XRPLEVM | xrplevm-mainnet | XRP |

> **Implementer note:** Goldrush chain names occasionally drift. Verify each name against `GET https://api.covalenthq.com/v1/chains/` at implementation time. If any chain in the table above isn't supported by Goldrush at the time of build, drop it from the map (it'll surface as "unsupported network" in the UI) — don't fake it.

### New Node route: `POST /api/cashflow/fetch-tx`

In `server.js`, add a handler that:
1. Requires an authenticated session (same middleware as `/api/cashflow/insert`).
2. Reads JSON body `{tx_hash, network}`.
3. Spawns `python3 scripts/cashflow_tx_fetch.py` with the body on stdin, captures stdout.
4. Passes the script's JSON straight through to the client. Map script exit codes to HTTP status:
   - exit 0 → 200
   - exit 2 (invalid input) → 400
   - exit 4 (not found) → 404
   - exit 5 (upstream) → 502
   - exit 6 (misconfig) → 500
   - exit 7 (no transfers) → 422
   - other → 500

### Env

New env var `GOLDRUSH_API_KEY`. Loaded the same way as `MO_DB_*` — process env wins, `.env` fallback. Add a line to `.env.example` (gitignored `.env` updated manually by the operator).

---

## 4. Frontend

All changes inside `src/TradeBookingForm.jsx`, scoped to the cashflow section. No new files in v1 unless the diff makes the file uncomfortably larger — if the helper logic grows past ~80 lines, extract `src/utils/txFetch.js`.

### 4.1 New UI elements

Sit right next to the existing `tx_hash` input:

```
[ tx_hash input                    ] [Fetch]
```

- **Fetch button**: disabled when (`network` is empty) OR (network is non-EVM) OR (hash doesn't match `/^0x[0-9a-fA-F]{64}$/`). Hover tooltip explains why it's disabled in each case.
- **Loading state**: button shows a spinner (lucide-react `Loader2` with `animate-spin`), label changes to "Fetching…", button stays disabled.
- **Error state**: a red one-liner appears under the input. Cleared on next Fetch click or on field edit.
- **Multi-transfer picker**: when the response has >1 transfer, render a small card list directly under the input. Each row shows `{asset} {amount} — {from_short} → {to_short}` with a "Use this" button. Picking a row applies the fill and clears the picker. There's also a "Cancel" link to dismiss without filling.

### 4.2 Fetch flow

```
user picks network
user pastes tx_hash
user clicks Fetch
  → button disables, spinner shows
  → POST /api/cashflow/fetch-tx { tx_hash, network }
  → on 200:
      if transfers.length == 1:
          applyAutofill(transfers[0], gas_fee, gas_asset, timestamp, tx_from, tx_to)
      else (transfers.length > 1):
          render multi-transfer picker; applyAutofill on row click
  → on non-200: show inline error
```

### 4.3 `applyAutofill(transfer, gas_fee, gas_asset, timestamp, tx_from, tx_to)`

Empty-only fill. A field is "empty" if its current value is `""`, `null`, or `undefined`. Numbers stored as strings count as empty when `""`.

| Form field | Source | Fill rule |
|---|---|---|
| `cf_asset` | `transfer.asset` | empty-only |
| `cf_amount` | `transfer.amount` | empty-only |
| `gas_asset` | `gas_asset` from response | empty-only |
| `gas_fee` | `gas_fee` from response | empty-only |
| `trade_date` | date portion of `timestamp` (YYYY-MM-DD, UTC) | empty-only |
| `value_date` | same as `trade_date` | empty-only |
| `notes` | append `\nfrom: {tx_from} → to: {tx_to} (tx ${tx_hash})` | always append (with leading newline only if notes is non-empty) |
| Everything else (`cf_direction`, `cf_type`, `counterparty`, `account_name`, `portfolio`, `status`, `fee_asset`, `fee_amount`, `cf_mirror`, `cf_loan_deal_refs`) | — | not touched |

After fill, surface a small green "Filled from chain" confirmation under the input that auto-dismisses after a few seconds.

---

## 5. Error handling — user-facing strings

| Backend signal | UI message under tx_hash input |
|---|---|
| Hash regex fails client-side | "Looks like an invalid hash" (no fetch fired) |
| Non-EVM network selected | Button stays disabled; tooltip: "Tx fetch only supports EVM chains for now" |
| 400 invalid input | "Couldn't read that hash, double-check it" |
| 404 not found | "Not found on {network} — wrong network?" |
| 422 no transfers | "No token or native transfers found in this tx" |
| 502 upstream | "Couldn't reach chain explorer, try again" |
| 500 misconfig or other | "Something went wrong fetching this tx" (server-side log has the detail) |

---

## 6. Testing

- **Unit tests for `tx_fetch.py`** with mocked Goldrush HTTP responses:
  - Single ERC-20 transfer (USDT on ETH) → one transfer returned, correct decimals, correct gas
  - Native ETH transfer (no log_events, value > 0) → synthesized native transfer
  - Multi-transfer batch tx → all transfers returned in order
  - Tx with `value == 0` and no Transfer logs → exit 7
  - Goldrush 404 → exit 4
  - Goldrush 500 → exit 5
  - Missing API key → exit 6
  - Unsupported network input → exit 2
- **Manual smoke** on a real USDT-on-ETH tx, a native BNB transfer on BSC, and a multi-transfer tx, before merging.

---

## 7. Files touched

**New:**
- `scripts/cashflow_tx_fetch.py` — Goldrush call + parse (matches the flat `scripts/cashflow_*.py` naming)
- `tests/test_cashflow_tx_fetch.py` — unit tests with mocked HTTP (matches top-level `tests/` pattern)

**Modified:**
- `server.js` — add `POST /api/cashflow/fetch-tx` route
- `src/TradeBookingForm.jsx` — cashflow section: Fetch button + loading/error states + multi-transfer picker + `applyAutofill` helper
- `.env.example` — add `GOLDRUSH_API_KEY=`

If the helper/picker logic in `TradeBookingForm.jsx` grows beyond ~80 lines, extract it into a sibling file. The project doesn't have a fixed convention for frontend utility modules yet — pick a path that fits when you get there (e.g., `src/cashflow/txFetch.js`).
