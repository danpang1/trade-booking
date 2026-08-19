# Hourly Uniswap LP snapshot venue

**Date:** 2026-08-19
**Status:** design approved, not yet implemented
**Repo:** `bitbucket.org/tokka-labs/middle-office-tools`

## Problem

`WALLET_CRB_EVM_08` (`0xe2Ed71633b1918de6E796d9BbAFa3aA4432973A5`) provides
liquidity to a Uniswap **v4** SPY/USDG pool on Robinhood Chain. In v4 the tokens
leave the wallet into the PoolManager singleton and the wallet holds only a
position NFT, so every ERC-20 balance reader goes blind to the position.

Measured 2026-08-19:

| Source | SPY | USDG | approx USD |
|---|---|---|---|
| ClickHouse `production.account_balance_snapshot` (official collector, 09:00 UTC) | 0.837694 | 7,461.29 | ~8k |
| Uniswap v4 position #744219, decoded live | 211.687826 | 47,534.431013 | ~155k |

No `_LP_` instrument exists anywhere in ClickHouse, and prod
`tq_hist_balance_mo` carries no `WALLET_CRB_EVM%` rows at all. This collector is
therefore the **only** source for roughly 95% of the account's value.

Cadence matters: between the 2026-08-18 and 2026-08-19 snaps the split moved
143.198279 SPY / 100,251.200454 USDG → 234.489203 SPY / 30,029.333323 USDG.
Only 6 LP snapshots exist in total, because the existing reader
(`recon-dashboard/8041-pnl/rh_lp_positions.py`) is driven by the **daily**
`daily_cycle.py`. Hourly captures the drift the daily cadence averages away.

## Non-goals

- No book mutation **in this module**. `classify()`, `LP_DEPOSIT` /
  `LP_WITHDRAWAL` retyping, `LP_REBALANCE` and `LP_FEE` legs stay in the 8041
  `daily_cycle`; they touch `venue_transfers`, which is not part of the
  venue-collector contract. (The 8041 side is covered below — it was extended in
  the same session, 2026-08-19.)
- No `tq_hist_position_mo` rows. Balance rows only.
- No Ethereum-mainnet Uniswap coverage (would need a second v3 decode path).
- No `account_id` corrections in the 8041 scripts, and no backfill of existing
  rows.

## Decisions

| Decision | Choice |
|---|---|
| Where it runs | new venue module + own CronJob in `middle-office-tools` |
| What it writes | `tq_hist_balance_mo` balance rows only |
| Coverage | auto-discover every v4 position NFT on every Robinhood-chain wallet |
| Environments | **UAT only** (not registered in `deploy_k8s-prod.sh`) |
| keccak-256 | add `pycryptodome`, same import the validated 8041 reader uses |
| `account_id` | `509532` for EVM_08, `506532` for EVM_07 |
| 8041 id bugs | left alone, recorded under Known gaps |
| Existing rows | not backfilled, recorded under Known gaps |

## Account id convention

`account_id` for a chain wallet = `reference_data.account_wallet.id × 1000 +
chain code`. Verified against ClickHouse `production.account_balance_snapshot`,
which is the authority for the venue-collector id space:

| account_id | account_name |
|---|---|
| 449502 | WALLET_CRB_EVM_01_BINANCE SMART CHAIN |
| 460501 | WALLET_CRB_EVM_02_ETHEREUM |
| 460532 | WALLET_CRB_EVM_02_ROBINHOOD |
| 466501 | WALLET_CRB_EVM_04_ETHEREUM |
| 489532 | WALLET_CRB_EVM_05_ROBINHOOD |
| 506532 | WALLET_CRB_EVM_07_ROBINHOOD |
| 509532 | WALLET_CRB_EVM_08_ROBINHOOD |

Chain codes: `501` = ETHEREUM, `502` = BINANCE SMART CHAIN, `532` = ROBINHOOD.
`reference_data.account_wallet` gives `id 509 → WALLET_CRB_EVM_08`, walletId
`0xe2Ed…73A5`, ACTIVE / PRODUCTION, portfolio `TOKKA LABS - MM - CENTRAL RISK
BOOK`, vaultKey `transfer/prod/account/wallet/509`. Hence `509 × 1000 + 532`.

## Files

| File | Change |
|---|---|
| `scripts/stream_uniswap_lp_balance.py` | new — venue module |
| `scripts/snapshot_uniswap_lp.py` | new — cron entrypoint |
| `scripts/uniswap_lp_tokens.json` | new — token allowlist |
| `helm_values/cron/uniswap-lp-snapshots.yaml` | new — CronJob |
| `scripts/deploy_k8s-uat.sh` | +1 `run_helm.sh` line |
| `requirements.txt`, `requirements-freeze.txt` | + `pycryptodome` |
| `tests/test_uniswap_lp.py` | new — unit tests |

`stream_uniswap_lp_balance.py` exposes `snap_once(conn, dry_run) -> int` plus the
standard `main()` with `--once / --hourly / --interval / --dry-run / --verbose`,
matching `stream_native_balance.py`.

`snapshot_uniswap_lp.py` is a thin entrypoint calling
`snapshot_all.run(dry_run, tasks=[("uniswap_lp.balance", stream_uniswap_lp_balance)])`,
reusing the shared connection, per-task isolation and summary logging — the same
trick `snapshot_bitstamp.py` uses.

A separate CronJob rather than an entry in `snapshot_all.TASKS` because
`venue-snapshots` deploys to **both** environments; a TASKS entry would leak
into prod, and this is UAT-only.

`scripts/uniswap_lp_tokens.json` is copied from `8041-pnl/rh_token_map.json`
(`{addr: [SYM, decimals]}`). It ships without a Dockerfile change — the
production stage already does `COPY ./scripts ./scripts`.

## Config (self-contained; prod cannot import from the 8041 folder)

```python
RPC        = "https://rpc.mainnet.chain.robinhood.com"
POSM       = "0x58daec3116aae6d93017baaea7749052e8a04fa7"   # v4 PositionManager
BLOCKSCOUT = "https://robinhoodchain.blockscout.com/api/v2"
EXCH       = "ROBINHOOD"
INSTR_VENUE = "ROBINHOOD"

WALLETS = [
    {"account_id": 509532, "account_name": "WALLET_CRB_EVM_08_ROBINHOOD",
     "address": "0xe2Ed71633b1918de6E796d9BbAFa3aA4432973A5"},
    {"account_id": 506532, "account_name": "WALLET_CRB_EVM_07_ROBINHOOD",
     "address": "0x2C3E763E5A0913a9cF984F85FbAdf45230A08e72"},
]
```

EVM_07 currently holds no LP NFTs; listing it means a future LP there is covered
with no code change.

## Read path

Lifted from `rh_lp_positions.py`, which was re-validated against the chain on
2026-08-19 (produced `211.687826 SPY / 47534.431013 USDG` for #744219).

1. `discover(address)` — Blockscout `/addresses/{addr}/nft?type=ERC-721`,
   filtered to `POSM`. Retry 5× with backoff; it 429s on the free tier.
2. **Completeness guard** — compare the discovered NFT count against
   `balanceOf(address)` (selector `0x70a08231`) on the PositionManager. Mismatch
   **raises**. `tokenOfOwnerByIndex` reverts on this contract (verified), so the
   id list must come from Blockscout and this is the only cross-check available.
   Without it a newly minted NFT is silently omitted — the failure mode that hit
   `BIN_UM_SYMBOLS`, and that already occurred here when #682784 closed and
   #744219 opened without the config noticing.
3. `read_fees(base, tid, tick, tickLower, tickUpper, liquidity)` — uncollected
   fees owed. v4 exposes no view for this (`collect` is the only public path and
   it requires the owner), so the growth accumulators come straight out of
   PoolManager storage via `extsload`:
   - `feeGrowthGlobal{0,1}X128` at pool-state offsets `+1`, `+2`
   - `feeGrowthOutside{0,1}X128` from the `ticks` mapping (offset `+4`) at both
     bounds; the `int24` key is sign-extended to a 32-byte word, and `TickInfo`
     packs `liquidityGross`+`liquidityNet` into its first slot
   - `feeGrowthInside{0,1}LastX128` from the `positions` mapping (offset `+6`),
     keyed `keccak(owner ‖ tickLower ‖ tickUpper ‖ salt)` with
     `owner = PositionManager` and `salt = bytes32(tokenId)`
   - `owed = liquidity × (feeGrowthInside − feeGrowthInsideLast) / 2¹²⁸`,
     with `feeGrowthInside = global − below − above`
   - **guard:** assert the liquidity stored at that position slot equals what the
     PositionManager reports. A layout change or a wrong key must raise, never
     silently read as "no fees owed". Validated 2026-08-19: both sources agree
     at `980877245649946819`.
4. `read_position(token_id, tokens)`:
   - `getPoolAndPositionInfo(uint256)` `0x7ba03aad` → PoolKey words + packed
     PositionInfo (`tickLower` bits 8–31, `tickUpper` bits 32–55, both int24)
   - `getPositionLiquidity(uint256)` `0x1efeed33` → 0 means closed, return None
   - `poolId = keccak256(abi.encode(poolKey))`;
     `slot = keccak256(poolId ‖ uint256(6))`;
     `extsload(bytes32)` `0x1e2eaeaf` on `poolManager()` `0xdc4c90d3` → slot0
     (`sqrtPriceX96` low 160 bits, current tick bits 160–183)
   - decompose liquidity into token amounts across the three price regimes
     (below range, in range, above range), quantized to 6 dp
   - a token outside the allowlist **raises** rather than guessing decimals

RPC calls retry 5× with backoff. The Robinhood RPC keeps only ~9 minutes of
archive state, so these are tip reads; the read block and wall-clock go into
`original_data` so the staleness is on the record.

## Write path

**Two** rows per token per open position — the supplied amount and the
uncollected fees, under separate instruments:

| instrument | meaning |
|---|---|
| `{SYM}@ROBINHOOD_LP_{tokenId}` | liquidity-decomposed amount (principal) |
| `{SYM}@ROBINHOOD_LPFEE_{tokenId}` | uncollected fees owed |

Both fold to the same asset on the recon board, which keys on
`instrument.split("@")[0]`, so the account's total value is right while supplied
and earned stay separately readable — the split DeBank shows. Fee rows are
written **even when zero**: a *missing* instrument means the NFT was burned, an
explicit `0` means nothing is owed. Without that distinction a quiet hour and a
closed position look identical.

Common columns:

| Column | Value |
|---|---|
| `account_id`, `account_name` | from `WALLETS` |
| `exch` | `ROBINHOOD` |
| `instrument_type` | `INST_TYPE_SPOT` |
| `side` | `long` |
| `total_qty`, `avail_qty` | decomposed amount |
| `frozen_qty`, `borrowed_qty`, `interest_qty` | `0` |
| `instrument_mo`, `instrument_exch` | `{SYM}` |
| `sync_ts`, `update_ts` | top of the current UTC hour **minus 1 second** |
| `original_data` | `token_id, pool_id, fee, tick_lower, tick_upper, tick, in_range, liquidity, read_block, read_ts` (fee rows add `fee: true`) |

Positions with zero liquidity produce **no row** and are logged as closed.

The instrument suffix is unchanged from `rh_lp_positions.py`, so the recon board
keeps folding the LP into the wallet column, and the `account_id` now matches the
ClickHouse rows for the same account.

The INSERT ends with:

```sql
ON CONFLICT (account_name, sync_ts, instrument) DO NOTHING
```

This is mandatory, not defensive. `tq_hist_balance_mo` has
`uniq_bal_mo_snap (account_name, sync_ts, instrument)`, and the board **sums**
rows sharing an hour bucket — a duplicate row silently doubles the position and
fabricates a break rather than looking like a duplicate. The clause also makes
this collector and the existing `rh_lp_positions.py` safe to run concurrently:
same boundary stamp, first writer wins, second no-ops. `rh_lp_positions.py` is
left untouched.

Note this differs from `stream_native_balance.py`, which stamps `sync_ts` at
fetch time and has no conflict clause. The boundary stamp is required here
because the board buckets LP rows by hour.

## 8041 book side (recon dashboard) — implemented 2026-08-19

The same fee model was applied to `recon-dashboard/8041-pnl/rh_lp_positions.py`,
which is what the recon board reads. Changes:

- `read_fees()` added (the storage read described above) and wired into
  `read_position()`, which now returns `fees` alongside `legs`
- `snap()` writes the `LPFEE` balance rows next to the `LP` rows
- new `_lp_fee_book()` — the fee-side book, `external_id LIKE 'lp-fee:%'`
- new `LP_FEE` delta leg, `external_id = lp-fee:{acct}:{YYYYMMDDHH}:{sym}`,
  self-correcting against `_lp_fee_book()` exactly as `LP_REBALANCE` corrects
  against `_lp_book()`
- `_lp_book()` deliberately still excludes the fee legs (`lp-fee:…` matches
  neither `%:lp` nor `lp-rebal:%`) so the two deltas never fight over the same
  balance
- `feed_v2.TRANSFER_COMP` gains `"LP_FEE": 33`, without which `_transfer_leg`
  raises on the unmapped type
- `snap(dry_run=False)` and a `--dry-run` flag added — the script previously had
  no way to rehearse a write against the live UAT table

**Identity check.** `snapΔ = transfers` per asset, traced through both hours:

| hour | snapshot Δ | transfers |
|---|---|---|
| accrual | `LPFEE +0.24` | `LP_FEE +0.24` |
| collect | `wallet +0.24`, `LPFEE −0.24` → 0 | `LP_WITHDRAWAL +0.24`, mirror `−0.24`, `LP_FEE −0.24`, `LP_REBALANCE +0.24` → 0 |

Income is recognised at accrual and the collection nets out. On collection the
`:lp` mirror pulls the LP-side book down and `LP_REBALANCE` corrects it back up,
which is what cancels the negative `LP_FEE`.

Verified by dry run at 2026-08-19 09:3x UTC (block 40466290):

```
DRY balance SPY@ROBINHOOD_LP_744219          224.435409
DRY balance USDG@ROBINHOOD_LP_744219      37745.063282
DRY balance SPY@ROBINHOOD_LPFEE_744219        0.243942
DRY balance USDG@ROBINHOOD_LPFEE_744219     155.007403
DRY LP_REBALANCE SPY   -10.053794     DRY LP_FEE SPY  +0.243942
DRY LP_REBALANCE USDG +7715.729959    DRY LP_FEE USDG +155.007403
```

The rebalance legs imply `7715.729959 / 10.053794 = 767.44`, i.e. the pool
price — the cross-check that the delta is a real swap, not an artifact.

## Error handling

- RPC and Blockscout: 5 retries with linear backoff
- unknown token, or discovered-count ≠ `balanceOf`: raise
- per-task isolation via `snapshot_all.run` — one bad venue does not stop others
- process exits non-zero only if every task fails

## Testing

`tests/test_uniswap_lp.py`, using recorded `eth_call` responses from the
2026-08-19 live read as fixtures:

- decomposition golden case: #744219, ticks `[-209915, -209760]`, current tick
  `-209880` → `211.687826 SPY`, `47534.431013 USDG`
- fee golden case: same position → `0.238210 SPY`, `153.900114 USDG` owed
- fee guard: a position slot whose stored liquidity disagrees with the
  PositionManager raises rather than returning zero fees
- fee rows are emitted at `0` rather than omitted
- the two out-of-range regimes (`sqrtP <= sa`, `sqrtP >= sb`) return
  single-sided amounts
- int24 sign extension for negative ticks
- keccak-256 against a known vector
- zero liquidity → `read_position` returns `None`, no row emitted
- token outside the allowlist raises
- discovered-count ≠ `balanceOf` raises
- row mapping: instrument string, boundary timestamp, zeroed columns

Pre-deploy: `python scripts/stream_uniswap_lp_balance.py --once --dry-run`, then
`--once` against UAT and confirm one row per token appears at the boundary
timestamp. `scripts/lint_python.sh` (max-line 88) must pass.

## Deploy sequence

1. merge to `main` after `python scripts/update_version.py` (bumps `version.yml`
   and `helm/Chart.yaml`); CI on main runs lint/build/test and publishes
2. trigger the UAT deploy pipeline manually — `main` does not auto-deploy
3. `./scripts/deploy_k8s-uat.sh` includes
   `run_helm.sh middle-office cron uniswap-lp-snapshots uat`

CronJob name length: release `cron-uniswap-lp-snapshots-uat` (29) +
`-uniswap-lp` (11) + `-cronjob` (8) = **48**, inside the k8s 52-char cap.
`cronjobs[].name` must stay `uniswap-lp` — this is the cap that rejected the
Bitstamp cron at 54 chars.

## Known gaps

1. **EVM_07 id is wrong in the 8041 code.** `evm_custody_wallets.py` uses `506`
   where ClickHouse says `506532`; 583 UAT rows carry `506`. Not fixed here.
2. **`rh05_goldrush_snaps.py` uses `489`** where ClickHouse says `489532`.
   (`rh_goldrush_snaps.py` correctly uses `460532`.) Not fixed here.
3. **341 UAT rows for `WALLET_CRB_EVM_08_ROBINHOOD` carry `account_id = 0`**
   (2026-08-14 → 2026-08-19). Not backfilled. The board keys off `account_name`,
   so nothing breaks, but the history is mislabelled.
4. **Between-snap drift is invisible.** The pool trades against the position
   continuously; each snapshot is a point read and the intervening path is lost.
   Hourly narrows this from ~24h to ~1h but does not remove it.
5. **Fee attribution blurs over a full accrue→collect cycle.** Per hour the
   accrual is visible as `LP_FEE`. But on collection the `LP_FEE` leg goes
   negative and the offsetting `LP_REBALANCE` leg goes positive, so cumulatively
   the income ends up attributed to `LP_REBALANCE`. Totals are correct; the
   split is only clean between collections. A dedicated income comp code would
   fix this — see the 8041 note below.
6. **Blockscout is a single point of failure** for NFT discovery. The
   `balanceOf` guard turns a partial response into a loud failure rather than
   silent under-reporting, but there is no second discovery source.
7. **Ethereum-mainnet LPs are not covered.** If EVM_07/EVM_08 open a Uniswap v3
   position on mainnet it will be invisible again.
