# Venue-Sourced PnL & Trade Ingestion — Working Doc

**Date:** 2026-06-15
**Authors:** Peter + Claude
**Status:** Findings locked; ingestion pipeline = next build
**Scope:** SPCX delta-neutral book (Binance perp + Hyperliquid spot) used as the
worked example; the methodology and ingestion plan generalise to all books.

---

## 0. TL;DR / Why this doc exists

We set out to compute COB PnL for our trades from **ClickHouse**, and discovered
ClickHouse's fill data (`production.execution`) is **silently lossy** — it drops a
large, *biased* fraction of fills. We re-sourced the same book directly from the
**venue APIs** (Binance papi, Hyperliquid `/info`) and got numbers that reconcile
to the cent against the exchanges' own position endpoints.

**Decision:** until the ClickHouse collectors are fixed, the trade/PnL pipeline
depends on **external venue APIs first**.

- **"Street data"** = pulled live from the venue API (Binance / Hyperliquid). Source of truth *today*.
- **"House data"** = ClickHouse (`production.*`). The intended long-term source, **not ready** (lossy).

The PnL **avg-cost engine itself is validated** — fed the complete venue fills it
reproduces Binance's own `entryPrice` (9 dp) and `realizedPnl` (6 dp). The only
problem was the data source.

---

## 1. Data sources & access

### 1.1 ClickHouse ("house data") — currently NOT trusted
- Endpoint: `https://jp-clickhouse-api.internal.tokkalabs.com:443`
- Creds: user `prod_ro` (read-only). Stored in DBeaver; recovered via AES-128-CBC
  decrypt of `credentials-config.json` (DBeaver fixed local key).
- Query via HTTP: `POST` SQL body, append `FORMAT TabSeparated`.

Key tables:
| table | what it is | trust |
|---|---|---|
| `production.execution` | our own fills (book/trader/strategy tagged) | **LOSSY — do not trust** |
| `production.position` | venue-reported aggregate positions (`source='aggregate'`) | derived; inherits gaps |
| `production.trade` | public market-data trade feed (used for **marks**) | OK for marks |
| `production.fill` | (no native rows; not used) | — |

**Gotchas:**
- Timestamps are **microseconds** (`ts_edge_first_seen / 1_000_000` = unix seconds).
- `instrument_id` is **NOT globally unique** — it collides across exchanges
  (id 99 = binance bnb *and* hip-xyz crcl). **Mark on `(exchange, codename)`**, not `instrument_id`.
- Correlated subqueries are disabled; use `IN (...)` / `argMaxIf`.

### 1.2 Venue APIs ("street data") — source of truth today
Creds in `nxgenmo/.env` (convention `<acct>.BINANCE_API_KEY` / `<acct>.BINANCE_API_SECRET`,
`TRADING_<nn>@HYPERLIQUID=<wallet>`). **Never print secrets; read-only calls only.**

**Binance Portfolio Margin (papi)** — signed HMAC-SHA256, base `https://papi.binance.com`:
- `GET /papi/v1/um/positionRisk?symbol=…` → current net `positionAmt`, `entryPrice` (ground truth)
- `GET /papi/v1/um/userTrades?symbol=…` → fills (`qty`,`price`,`buyer`,`commission`,`realizedPnl`,`time`,`id`).
  Paginate forward by `fromId`; full history retained.

**Hyperliquid (`/info`, public POST, no auth)** — base `https://api.hyperliquid.xyz/info`:
- `{"type":"spotClearinghouseState","user":addr}` → spot balances + `entryNtl` (ground truth balance)
- `{"type":"userFillsByTime","user":addr,"startTime":..,"endTime":..}` → fills (2000/page, ascending; paginate by time). Fields: `coin`,`px`,`sz`,`side`(B/A),`fee`,`feeToken`,`closedPnl`,`startPosition`,`time`,`tid`.
- `{"type":"userNonFundingLedgerUpdates",...}` → deposits / `send` (spot transfers) — needed to see minted-token transfers.
- Spot pair coin ids look like `@465` (= SPCXD/USDC). `feeToken` confirms the base token.

---

## 2. PnL methodology (avg-cost trade basis)

Engine: `nxgenmo/scripts/pnl_avgcost/engine.py` (canonical; do not fork).

```
Daily PnL = Realized + ΔUnrealized + Fees + Funding + Interest + Rebates + Non-cash
```

- **Weighted-average (moving) cost**, Decimal arithmetic, sign-flip handling.
  - `apply_fill(pos, qty_signed, price)`: +qty = buy, −qty = sell.
  - Same-direction add → re-average cost. Reduction → realize, avg unchanged.
    Sign-flip → close old at price (realize), open residual at price.
  - `unrealized(pos, mark)`: long `(mark−avg)·qty`; short `(avg−mark)·|qty|`.
- **Key** = `(venue, account, asset, product)`.
- **Replay** all fills before SOD to build opening `(qty, avg_cost)`; then per day apply
  fills in time order, accumulate realized/fees, snapshot EOD position, mark it.
- **Marks**: EOD = last trade `≤ 23:59:59 UTC` (carry-forward: SOD mark of day N = EOD mark of day N−1).
- **Order matters** for avg cost: a *sell* between two *buys* re-weights the later buy,
  so events (incl. mints/transfers) must be walked **chronologically**.

### 2.1 Mint / issuance events (new requirement)
Some spot legs are **not bought on the orderbook** — they are **minted** (issued) at a
known cost and **transferred in** (`send`). Neither the venue nor ClickHouse holds the
**mint price**. The avg-cost walk therefore needs a **mint event type**:
`add qty @ mint_px` injected at the transfer timestamp, alongside trades and transfers.
Without it, the spot leg's basis is wrong (HL's own `entryNtl` mis-valued the transfers).

---

## 3. Worked example — SPCX delta-neutral book (`CHARLES_DOWLING` / `MM-CRB-01`)

One book, two legs, ~delta-neutral. Numbers as of COB 14-Jun-2026.

| leg | venue / acct | position | **avg entry** | how sourced |
|---|---|---|---|---|
| perp | Binance papi acct **810** (`SPCXUSDT`) | **SHORT 541.94** | **168.72** | orderbook `userTrades` (1004 fills) |
| spot | Hyperliquid `TRADING_06` (`@465` SPCXD) | **LONG 541.94** | **165.01** | **mints + `@465` spot** |

Matching 541.94 on both legs ⇒ the hedge. Entry spread **short 168.72 / long 165.01
≈ 3.71/unit (~$2,010)** locked in.

### 3.1 The HL long was minted + transferred, not traded
- Spot balance +541.94 SPCXD; `@465` orderbook fills net only **−57.84**.
- `nonFundingLedger`: **599.839 SPCXD transferred in** via 3 `send`s from sister wallet
  `0x8dc4…c031` (Jun 12: 1.0, 298.90, 299.939).
- **Mint cost basis (user-provided):** `299.9 @ 162.575` + `299.93899 @ 166.70057`
  = 599.839 minted @ avg **164.64**.
- Walk = mints (164.64) + `@465` net −57.84 ⇒ final **541.94 @ 165.01** (reconciles to
  balance after ~0.06 SPCXD in-kind fees). HL's reported `entryNtl` ⇒ 130.71 is **wrong**
  (it mis-valued the transfers at ~68/unit).

### 3.2 ClickHouse vs venue truth (the data-loss finding)
| metric | Binance (truth) | ClickHouse `execution`/`position` |
|---|---:|---:|
| Binance SPCX net | **−541.94** | −255.56 (753 of 1004 fills; ~25% dropped, sell-biased) |
| HL SPCXD net | **+541.94** (spot bal) | −108 (wrong sign *and* size) |

ClickHouse drops fills silently and with a **directional bias** (more sells than buys
dropped on Binance), so the net is ~2× wrong. Confirmed systemic (native venue also
missing 4 of 5 instruments earlier).

### 3.3 Corrected COB PnL (unified mark, Jun-14 = 168.01)
Script: `scripts/pnl_avgcost/spcx_book_cob.py`. Unified mark across both legs makes the
combined book **basis-independent** (mark cancels: `(short_avg−m)q + (m−long_avg)q`).

| COB | realized | ΔUnreal (net) | fees | **book net** |
|---|---:|---:|---:|---:|
| Jun 12 | 277.9 | ~2,613 | 20.2 | **+2,870.5** |
| Jun 13 | 720.5 | ~−603 | 15.5 | **+102.1** |
| Jun 14 | 127.8 | ~−2.1 | 11.0 | **+114.7** |
| **3-day** | **1,126** | **~2,005 (open spread)** | **~47** | **+3,087.3** |

Day-1 banks the entry spread; days 2–3 are small accruals. Total ≈ realized + open-spread
MTM − fees, robust to the mark choice.

---

## 4. Scripts produced

| path | purpose | status |
|---|---|---|
| `scripts/pnl_avgcost/engine.py` | canonical avg-cost engine | existing, validated |
| `scripts/pnl_avgcost/spcx_book_cob.py` | **corrected** venue-sourced SPCX book COB PnL (Binance `userTrades` + HL mints/`@465`, unified mark) | keep |
| `scripts/pnl_avgcost/ch_cob_pnl.py` | COB PnL from ClickHouse `production.execution` | **superseded** (lossy source) |
| `scripts/_tmp_spcx_810_check.py` | Binance SPCX position/trades/avg-cost cross-check | scratch |
| `scripts/_tmp_spcxd_hl06_check.py` | HL SPCXD balance/fills/mints/avg-cost cross-check | scratch |

---

## 5. Next build — Trade ingestion (street-data-first)

**Goal:** pull our trades from **Binance + Hyperliquid APIs** (creds in `.env`), **enrich**
to MO refdata, and persist into **`trades_spot`** / **`trades_futures`** (UAT Postgres
`middle_office`, written via `trade-booking/scripts/spot_db.py` style primitives).

**Design already agreed (earlier session):**
- **Master/child grain.** Master = 1 row per **order** (`local_order_id`), aggregated VWAP →
  the deal TMS sees, `deal_ref` from the MFX/futures sequence. Child = 1 row per **fill**,
  immutable, FK → master `deal_ref`. Dedup key = the venue fill id (Binance `id` /
  Hyperliquid `tid`); for ClickHouse it was `cp_event_id`.
- **Source switch.** Same schema, pluggable source: **street (API) now**, **house (ClickHouse)
  later** — one adapter interface so the switch is a config flag.
- **Idempotent** upsert on fill id so re-runs don't double-book.

**Still open (decide before coding):**
1. **trades_spot vs trades_futures split** — spot legs (HL `@465`) → `trades_spot`; perp legs
   (Binance UM, HL `xyz:` perps) → `trades_futures`. Confirm `trades_futures` schema exists / mirror `trades_spot`.
2. **Refdata mapping** — `book_id`/`strategy_id`/`exchange` → `entity`/`portfolio`/`counterparty`/`account`.
   Need the mapping table (the hard part).
3. **Mint/transfer events** — spot legs minted + `send`-transferred must be ingested as
   non-trade events (with cost basis) or the spot basis is wrong. New event type.
4. **Fees** — venue fills carry commission (Binance USDT; HL SPCXD/USDC). Map to `fee_asset`/`fee_amount`.
5. **Write path** — reuse `spot_db.py` primitives (bitemporal SCD2, refdata validation) vs new futures path.
6. **Trigger** — scheduled batch (cron/CronJob) with a durable watermark; not a streaming daemon (YAGNI).

---

## 6. Operating rules / lessons
- **Never trust `production.execution` for positions or PnL** until collectors fixed; cross-check vs venue.
- **Mark on `(exchange, codename)`**, CH timestamps are microseconds.
- **Walk events chronologically**; include mints/transfers, not just trades.
- For delta-neutral books, **mark both legs at one reference** to strip perp↔spot basis noise.
- Venue APIs: **read-only, secrets from `.env`, never echoed.**
