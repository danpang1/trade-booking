"""Uniswap v4 LP balance snapshot collector → middle_office.tq_hist_balance_mo.

In Uniswap v4 the supplied tokens leave the wallet into the PoolManager
singleton and the wallet holds only a position NFT, so every ERC-20 balance
reader — including the official venue collector — goes blind to the position.
Measured 2026-08-19 on WALLET_CRB_EVM_08: the ERC-20 feed saw ~$8k while the LP
held ~$210k. This collector is the only source for that value.

Writes, per open position, TWO rows per token:

  (1) {SYM}@ROBINHOOD_LP_{tokenId}     — liquidity-decomposed amount
  (2) {SYM}@ROBINHOOD_LPFEE_{tokenId}  — uncollected fees owed

Both fold to the same asset on the recon board (it keys on
instrument.split('@')[0]), so the account value is right while supplied and
earned stay separately readable. Fee rows are written even when zero: a MISSING
instrument means the NFT was burned, an explicit 0 means nothing is owed.

Convention
----------
- Public read-only RPC + Blockscout (no auth, no venue credentials).
- account_id = reference_data.account_wallet.id x 1000 + chain code
  (501 ETHEREUM, 502 BSC, 532 ROBINHOOD) — matches ClickHouse
  production.account_balance_snapshot, which is the authority for this id space.
- sync_ts/update_ts = FETCH TIME, matching stream_native_balance.py and every
  other collector here. An earlier revision stamped the hour boundary on the
  belief that recon_dashboard.fetch_snaps SUMS rows sharing an hour bucket, so
  a second row in the hour would double the position. That is not what it does:
  it groups by exact sync_ts and takes `ts = max(by_ts)` per hour — the LATEST
  snapshot in the hour wins and earlier ones are ignored (five call sites, e.g.
  recon_dashboard.py:382-385). Summing happens only WITHIN one sync_ts, which
  is the WETH-into-ETH fold. Boundary stamping made every run inside an hour
  collide on one key, so an ad-hoc run silently wrote nothing.
- INSERT still ends with ON CONFLICT (account_name, sync_ts, instrument)
  DO NOTHING. Two rows at the SAME sync_ts for the same instrument would land
  inside one `ts` group and genuinely double, so the guard stays — it is just
  no longer the thing that forces the timestamp choice.
- The Robinhood RPC keeps only ~9 minutes of archive state, so these are tip
  reads; read_block and read_ts go into original_data so the staleness is on
  the record. Amounts alone are uninterpretable without the price they were
  read at — the LP composition swings ~1.77 SPY per tick in a 155-tick range.
- This module writes balance rows ONLY. The book-side legs (LP_DEPOSIT /
  LP_WITHDRAWAL / LP_REBALANCE / LP_FEE) live in the 8041 daily_cycle; they
  touch venue_transfers, which is not part of the venue-collector contract.

Run
---
    python scripts/stream_uniswap_lp_balance.py --once --dry-run
    python scripts/stream_uniswap_lp_balance.py --once
    python scripts/stream_uniswap_lp_balance.py --hourly
"""
from __future__ import annotations

import argparse
import json
import logging
import signal
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D, getcontext
from pathlib import Path

from Crypto.Hash import keccak

import mo_db

getcontext().prec = 50


# ── Constants ──────────────────────────────────────────────────────────
RPC = "https://rpc.mainnet.chain.robinhood.com"
POSM = "0x58daec3116aae6d93017baaea7749052e8a04fa7"   # v4 PositionManager
BLOCKSCOUT = "https://robinhoodchain.blockscout.com/api/v2"
EXCH = "ROBINHOOD"
INSTR_VENUE = "ROBINHOOD"

# Every Robinhood-chain wallet that could hold a v4 position. EVM_07 holds none
# today; listing it means a future LP there is covered with no code change.
WALLETS = [
    {"account_id": 509532, "account_name": "WALLET_CRB_EVM_08_ROBINHOOD",
     "address": "0xe2Ed71633b1918de6E796d9BbAFa3aA4432973A5"},
    {"account_id": 506532, "account_name": "WALLET_CRB_EVM_07_ROBINHOOD",
     "address": "0x2C3E763E5A0913a9cF984F85FbAdf45230A08e72"},
]

SEL_POOL_AND_INFO = "0x7ba03aad"    # getPoolAndPositionInfo(uint256)
SEL_LIQUIDITY = "0x1efeed33"        # getPositionLiquidity(uint256)
SEL_POOL_MANAGER = "0xdc4c90d3"     # poolManager()
SEL_EXTSLOAD = "0x1e2eaeaf"         # extsload(bytes32)
SEL_BALANCE_OF = "0x70a08231"       # balanceOf(address)

MASK256 = (1 << 256) - 1
Q96 = D(1 << 96)
Q128 = D(1 << 128)
POOLS_SLOT = 6                      # PoolManager._pools
# Pool.State offsets from the per-pool base slot (v4-core Pool.sol):
#   +0 slot0, +1 feeGrowthGlobal0, +2 feeGrowthGlobal1, +3 liquidity,
#   +4 ticks mapping, +5 tickBitmap, +6 positions mapping
FG0_OFF, FG1_OFF, TICKS_OFF, POSITIONS_OFF = 1, 2, 4, 6

SCRIPT_DIR = Path(__file__).resolve().parent
TOKENS_FILE = SCRIPT_DIR / "uniswap_lp_tokens.json"

log = logging.getLogger("stream_uniswap_lp_balance")


# ─────────────────────────────────────────────────────────────────────
# chain plumbing
# ─────────────────────────────────────────────────────────────────────

def _tokens() -> dict[str, tuple[str, int]]:
    """{contract: (SYMBOL, decimals)} allowlist. GoldRush/Blockscout return no
    token metadata on robinhood-mainnet, so the map is authoritative."""
    raw = json.loads(TOKENS_FILE.read_text(encoding="utf-8"))
    return {k.lower(): (v[0], int(v[1])) for k, v in raw.items()}


def _rpc(method: str, params: list, timeout: int = 60):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                       "params": params}).encode()
    req = urllib.request.Request(
        RPC, data=body,
        headers={"Content-Type": "application/json", "User-Agent": "tokka-mo"})
    for attempt in range(5):
        try:
            d = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
            if "result" not in d:
                raise RuntimeError(str(d.get("error"))[:200])
            return d["result"]
        except Exception:
            if attempt == 4:
                raise
            time.sleep(2 * (attempt + 1))


def _call(to: str, data: str) -> str:
    return _rpc("eth_call", [{"to": to, "data": data}, "latest"])


def _keccak(hexstr: str) -> str:
    k = keccak.new(digest_bits=256)
    k.update(bytes.fromhex(hexstr))
    return k.hexdigest()


def _s24(v: int) -> int:
    """Sign-extend a 24-bit two's-complement tick."""
    return v - (1 << 24) if v >= (1 << 23) else v


_pm_cache: str | None = None


def pool_manager() -> str:
    global _pm_cache
    if _pm_cache is None:
        _pm_cache = "0x" + _call(POSM, SEL_POOL_MANAGER)[26:]
    return _pm_cache


def _sload(slot: str) -> int:
    """One PoolManager storage word — v4 exposes state only via extsload."""
    return int(_call(pool_manager(), SEL_EXTSLOAD + slot), 16)


def _slot_add(slot: str, n: int) -> str:
    return format((int(slot, 16) + n) & MASK256, "064x")


def _sqrt_ratio(tick: int) -> D:
    return (D("1.0001") ** (D(tick) / 2)) * Q96


# ─────────────────────────────────────────────────────────────────────
# position discovery + decode
# ─────────────────────────────────────────────────────────────────────

def discover(address: str, timeout: int = 60) -> list[int]:
    """Position-NFT token ids owned by `address`.

    Blockscout is the only enumeration source: the v4 PositionManager is NOT
    ERC721Enumerable (tokenOfOwnerByIndex reverts, verified 2026-08-19). The
    caller cross-checks the count against balanceOf so a partial response
    fails loudly instead of silently under-reporting a position.
    """
    url = f"{BLOCKSCOUT}/addresses/{address}/nft?type=ERC-721"
    req = urllib.request.Request(url, headers={"User-Agent": "tokka-mo"})
    for attempt in range(5):
        try:
            d = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
            break
        except Exception:
            if attempt == 4:
                raise
            time.sleep(5 * (attempt + 1))
    out = []
    for it in d.get("items", []):
        tok = it.get("token") or {}
        addr = (tok.get("address_hash") or tok.get("address") or "").lower()
        if addr == POSM and it.get("id"):
            out.append(int(it["id"]))
    return out


def nft_balance(address: str) -> int:
    """Number of position NFTs the PositionManager says `address` owns."""
    data = SEL_BALANCE_OF + "0" * 24 + address[2:].lower()
    return int(_call(POSM, data), 16)


def read_fees(base: str, tid: str, tick: int, tick_lower: int,
              tick_upper: int, liquidity: int) -> tuple[D, D]:
    """Uncollected fees owed to the position, in ATOMS (token0, token1).

    v4 has no view for this — `collect` is the only public path and it needs
    the owner — so the growth accumulators are read straight out of PoolManager
    storage. The position key is keccak(owner ‖ tickLower ‖ tickUpper ‖ salt)
    with owner = PositionManager and salt = bytes32(tokenId).
    """
    fg0 = _sload(_slot_add(base, FG0_OFF))
    fg1 = _sload(_slot_add(base, FG1_OFF))

    def tick_growth(t: int) -> tuple[int, int]:
        # mapping(int24 => TickInfo): key sign-extended to a 32-byte word;
        # TickInfo packs liquidityGross+liquidityNet into its first slot.
        s = _keccak(format(t & MASK256, "064x") + _slot_add(base, TICKS_OFF))
        return _sload(_slot_add(s, 1)), _sload(_slot_add(s, 2))

    lo0, lo1 = tick_growth(tick_lower)
    up0, up1 = tick_growth(tick_upper)
    key = _keccak(POSM[2:] + format(tick_lower & 0xffffff, "06x")
                  + format(tick_upper & 0xffffff, "06x") + tid)
    pslot = _keccak(key + _slot_add(base, POSITIONS_OFF))
    stored = _sload(pslot)
    if stored != liquidity:
        raise RuntimeError(
            f"LP #{int(tid, 16)}: PoolManager position slot holds liquidity "
            f"{stored}, PositionManager reports {liquidity} — storage layout "
            f"or position key changed, refusing to report fees")
    last0 = _sload(_slot_add(pslot, 1))
    last1 = _sload(_slot_add(pslot, 2))

    def owed(g: int, lo: int, up: int, last: int) -> D:
        below = lo if tick >= tick_lower else (g - lo) & MASK256
        above = up if tick < tick_upper else (g - up) & MASK256
        inside = (g - below - above) & MASK256
        return D(liquidity) * D((inside - last) & MASK256) / Q128

    return owed(fg0, lo0, up0, last0), owed(fg1, lo1, up1, last1)


def read_position(token_id: int, tokens: dict) -> dict | None:
    """Decode one position NFT. None when liquidity is 0 (closed).

    A token outside `tokens` raises rather than guessing decimals.
    """
    tid = format(token_id, "064x")
    res = _call(POSM, SEL_POOL_AND_INFO + tid)
    w = [res[2 + i * 64:2 + (i + 1) * 64]
         for i in range((len(res) - 2) // 64)]
    liquidity = int(_call(POSM, SEL_LIQUIDITY + tid), 16)
    if liquidity == 0:
        return None
    cur0, cur1 = "0x" + w[0][24:], "0x" + w[1][24:]
    info = int(w[5], 16)
    tick_lower = _s24((info >> 8) & 0xffffff)
    tick_upper = _s24((info >> 32) & 0xffffff)
    pool_id = _keccak(w[0] + w[1] + w[2] + w[3] + w[4])
    base = _keccak(pool_id + format(POOLS_SLOT, "064x"))
    s0 = _sload(base)
    sqrt_p = D(s0 & ((1 << 160) - 1))
    tick = _s24((s0 >> 160) & 0xffffff)
    sa, sb = _sqrt_ratio(tick_lower), _sqrt_ratio(tick_upper)
    liq = D(liquidity)
    if sqrt_p <= sa:
        a0, a1 = liq * (sb - sa) * Q96 / (sa * sb), D(0)
    elif sqrt_p >= sb:
        a0, a1 = D(0), liq * (sb - sa) / Q96
    else:
        a0 = liq * (sb - sqrt_p) * Q96 / (sqrt_p * sb)
        a1 = liq * (sqrt_p - sa) / Q96
    f0, f1 = read_fees(base, tid, tick, tick_lower, tick_upper, liquidity)
    out = {
        "token_id": token_id, "pool_id": "0x" + pool_id,
        "fee": int(w[2], 16), "tick_lower": tick_lower,
        "tick_upper": tick_upper, "tick": tick, "liquidity": liquidity,
        "in_range": sa < sqrt_p < sb, "legs": [], "fees": [],
    }
    for cur, amt, fee in ((cur0, a0, f0), (cur1, a1, f1)):
        if cur.lower() not in tokens:
            raise RuntimeError(
                f"LP token {cur} not in the allowlist — add it to "
                f"{TOKENS_FILE.name} first")
        sym, dec = tokens[cur.lower()]
        scale = D(10) ** dec
        out["legs"].append((sym, (amt / scale).quantize(D("0.000001"))))
        out["fees"].append((sym, (fee / scale).quantize(D("0.000001"))))
    return out


# ─────────────────────────────────────────────────────────────────────
# normalize + INSERT
# ─────────────────────────────────────────────────────────────────────

def _row(wallet: dict, instrument: str, symbol: str, qty: D,
         stamp: datetime, raw: dict) -> dict:
    return {
        "account_id": wallet["account_id"],
        "account_name": wallet["account_name"],
        "exch": EXCH,
        "instrument": instrument,
        "instrument_type": "INST_TYPE_SPOT",
        "side": "long",
        "total_qty": qty,
        "avail_qty": qty,
        "frozen_qty": 0,
        "instrument_mo": symbol,
        "instrument_exch": symbol,
        "sync_ts": stamp,
        "update_ts": stamp,
        "original_data": json.dumps(raw),
        "borrowed_qty": 0,
        "interest_qty": 0,
    }


def build_rows(wallet: dict, pos: dict, stamp: datetime,
               read_block: int, read_ts: str) -> list[dict]:
    """Balance rows for one open position: supplied + fees, per token."""
    meta = {
        "lp": True, "token_id": pos["token_id"], "pool_id": pos["pool_id"],
        "fee_tier": pos["fee"], "tick_lower": pos["tick_lower"],
        "tick_upper": pos["tick_upper"], "tick": pos["tick"],
        "in_range": pos["in_range"], "liquidity": str(pos["liquidity"]),
        "read_block": read_block, "read_ts": read_ts,
    }
    tid = pos["token_id"]
    rows = [
        _row(wallet, f"{sym}@{INSTR_VENUE}_LP_{tid}", sym, qty, stamp, meta)
        for sym, qty in pos["legs"]
    ]
    rows += [
        _row(wallet, f"{sym}@{INSTR_VENUE}_LPFEE_{tid}", sym, qty, stamp,
             dict(meta, fee=True))
        for sym, qty in pos["fees"]
    ]
    return rows


INSERT_SQL = """
INSERT INTO tq_hist_balance_mo (
    account_id, account_name, exch, instrument, instrument_type, side,
    total_qty, avail_qty, frozen_qty, instrument_mo, instrument_exch,
    sync_ts, update_ts, original_data, borrowed_qty, interest_qty
) VALUES (
    %(account_id)s, %(account_name)s, %(exch)s, %(instrument)s,
    %(instrument_type)s, %(side)s,
    %(total_qty)s, %(avail_qty)s, %(frozen_qty)s, %(instrument_mo)s,
    %(instrument_exch)s,
    %(sync_ts)s, %(update_ts)s, %(original_data)s, %(borrowed_qty)s,
    %(interest_qty)s
)
-- idempotent: the board SUMS rows sharing an hour bucket, so a duplicate does
-- not look like a duplicate — it silently doubles the position and fabricates
-- a break. Backed by uniq_bal_mo_snap.
ON CONFLICT (account_name, sync_ts, instrument) DO NOTHING
"""


def snap_once(conn, dry_run: bool) -> int:
    fetch_dt = datetime.now(timezone.utc).replace(tzinfo=None)
    stamp = fetch_dt          # see the sync_ts note in the module docstring
    block = int(_rpc("eth_blockNumber", []), 16)
    tokens = _tokens()
    rows: list[dict] = []

    for wallet in WALLETS:
        addr = wallet["address"]
        tids = discover(addr)
        owned = nft_balance(addr)
        if len(tids) != owned:
            # A newly minted NFT that Blockscout has not indexed would
            # otherwise vanish from the snapshot without a trace.
            raise RuntimeError(
                f"{wallet['account_name']}: PositionManager reports {owned} "
                f"position NFTs, Blockscout listed {len(tids)} {tids} — "
                f"refusing to snap a partial view")
        for tid in tids:
            pos = read_position(tid, tokens)
            if pos is None:
                log.info(f"{wallet['account_name']}: LP #{tid} closed")
                continue
            rows += build_rows(wallet, pos, stamp, block,
                               fetch_dt.isoformat())
            legs = ", ".join(f"{q} {s}" for s, q in pos["legs"])
            fees = ", ".join(f"{q} {s}" for s, q in pos["fees"])
            log.info(
                f"{wallet['account_name']}: LP #{tid} {legs} "
                f"({'in' if pos['in_range'] else 'OUT OF'} range) "
                f"| fees owed {fees}")

    if dry_run:
        for r in rows:
            log.info(f"DRY {r['account_name']:28s} {r['instrument']:32s} "
                     f"total={r['total_qty']:>18}")
        return len(rows)

    if conn and rows:
        # Per-row rather than execute_batch so the ON CONFLICT skips are
        # COUNTED. Batching hides them, and a snap that silently wrote nothing
        # must not report itself as a success — that is how a stalled feed goes
        # unnoticed. Volume here is a handful of rows per run.
        written = 0
        with conn.cursor() as cur:
            for r in rows:
                cur.execute(INSERT_SQL, r)
                written += cur.rowcount
        conn.commit()
        skipped = len(rows) - written
        log.info(f"tq_hist_balance_mo: {written} inserted, {skipped} skipped "
                 f"of {len(rows)} at sync_ts={stamp}")
        if written == 0 and rows:
            log.warning(
                f"every row was skipped — something already wrote these "
                f"instruments at exactly {stamp}. Expected only on a re-run "
                f"within the same second; investigate otherwise.")
        return written
    return len(rows)


# ─────────────────────────────────────────────────────────────────────
# runner
# ─────────────────────────────────────────────────────────────────────

def _sleep_until_next_hour(stop: dict) -> bool:
    now = datetime.now(timezone.utc)
    next_hr = (now.replace(minute=0, second=0, microsecond=0)
               + timedelta(hours=1))
    total = (next_hr - now).total_seconds()
    log.info(f"next snap at {next_hr.isoformat(timespec='seconds')} "
             f"(sleeping {int(total)}s)")
    deadline = time.monotonic() + total
    while time.monotonic() < deadline:
        if stop["flag"]:
            return True
        time.sleep(min(1.0, deadline - time.monotonic()))
    return False


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Uniswap v4 LP balance snapshot collector")
    ap.add_argument("--interval", type=int, default=300,
                    help="Poll interval in seconds (ignored with --hourly)")
    ap.add_argument("--hourly", action="store_true",
                    help="Snap at the top of every UTC hour")
    ap.add_argument("--once", action="store_true",
                    help="Run a single snap and exit")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print rows but don't INSERT")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    conn = None if args.dry_run else mo_db.connect()
    stop = {"flag": False}

    def handle_sig(*_):
        log.info("shutdown requested")
        stop["flag"] = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, handle_sig)
        except (OSError, ValueError):
            pass

    mode = ("once" if args.once
            else "hourly" if args.hourly else f"interval={args.interval}s")
    log.info(f"mode={mode} dry_run={args.dry_run} wallets={len(WALLETS)}")

    try:
        if args.once:
            snap_once(conn, args.dry_run)
            return
        if args.hourly:
            snap_once(conn, args.dry_run)
            while not stop["flag"]:
                if _sleep_until_next_hour(stop):
                    break
                try:
                    snap_once(conn, args.dry_run)
                except Exception as e:
                    log.error(f"snap_once failed: {e}")
            return
        while not stop["flag"]:
            try:
                snap_once(conn, args.dry_run)
            except Exception as e:
                log.error(f"snap_once failed: {e}")
            for _ in range(args.interval * 10):
                if stop["flag"]:
                    break
                time.sleep(0.1)
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    main()
