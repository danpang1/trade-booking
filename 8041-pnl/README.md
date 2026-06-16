# 8041 PnL — Central Risk Book daily PnL + recon

Standalone **daily PnL + full-account reconciliation** for **portfolio 8041**
(TOKKA LABS - MM - CENTRAL RISK BOOK). Covers Binance **810** + Hyperliquid
**TRADING_06**, which both map to 8041.

## Run
```bash
python pnl_8041_daily.py --date 2026-06-15 --mark 199.82
```
Prints two tables for the COB `--date` (00:00–23:59:59 UTC):
1. **FULL PnL (all trades)** — every instrument on both accounts. SPCX
   delta-neutral pair via the avg-cost engine (at `--mark`); every HL futures
   leg (HYPE + `xyz:*`) via realized (closedPnl) + ΔUnreal + funding − fees.
2. **FULL-ACCOUNT RECON** — `balance Δ = trade/cash Δ + unrealized Δ + transfers`
   for every moved instrument (diff ≈ 0). Both tables lead with SOD/EOD balance.

## Files
| file | purpose |
|---|---|
| `pnl_8041_daily.py` | main command (PnL + recon) |
| `account_recon.py` | full-account recon + HL perp PnL (imported) |
| `engine.py` | avg-cost engine (vendored from nxgenmo) |
| `pg.py` | Postgres creds from `.env` `#POSTGRES BALANCE DB` block |
| `.env` | creds: Postgres + venue (810, TRADING_06) — **DO NOT COMMIT** |

## Data sources
- **Trades / funding** — Binance papi `userTrades`/`income` + Hyperliquid `/info` (street data).
- **Balances / unrealized** — Postgres `tq_oms_data` (`tq_hist_balance`, `tq_hist_position`), hourly snaps. Trade window bounded by the actual snap `record_ts` (~00:02), not nominal 00:00.
- **SPCX marks** — ClickHouse `production.trade` (read-only) + `--mark` pin (the `hip-xyz` proxy is unreliable; pin the real EOD mark).

## Notes
- Binance key 810 is **IP-whitelisted** — run from a whitelisted IP (else `-2015`).
- EOD mark for the SPCX pair is user-pinned and applied to **both** legs, so the delta-neutral book total is basis-independent.
- HL has three USDC pools (spot / main-perp / xyz-dex) routed by fill coin; net-flat legs (e.g. HYPE round-trip) carry PnL via the main-dex pool.
