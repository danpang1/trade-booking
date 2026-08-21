"""Full-account recon for 810 (Binance) + TRADING_06 (Hyperliquid)
+ WALLET_CRB_EVM_02 (Robinhood chain).

Reconciles EVERY moved instrument balance over a COB day:
    balance Δ = trade/cash Δ + unrealized Δ + transfers   (diff ≈ 0)

Robinhood-chain legs have no tq_hist_balance snapshots; their SOD/EOD balances
are CHAIN-RECONSTRUCTED (Σ Blockscout transfer deltas before the boundary) and
their trade/transfer deltas come from the same transfer stream, so their diff
validates the fill-vs-funding classification rather than an independent source.

- POSITION legs (perp contracts / spot tokens): trade Δ = net traded qty.
- CASH legs (USDT / USDC pools): cash = realized+funding-fees from that
  pool's fills; unrealized Δ from tq_hist_position; transfers from the ledger.

HL has THREE USDC pools (spot / main-perp / xyz-dex); fills route by coin:
  @<n>  -> spot ;  xyz:*  -> xyz-dex ;  other perp (e.g. HYPE) -> main-perp.
Window is bounded by the actual snap record_ts (not nominal 00:00).
"""
from __future__ import annotations

import gzip
import hashlib
import hmac
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pg import PG_HOST, PG_PORT, PG_USER, PG_PASS, PG_DB  # noqa: E402

ENV = Path(__file__).resolve().parent / ".env"
BUF = 60
ZERO = D(0)
BIN_FUT = "TK810@BINANCE_USDT_FUTURE"
BIN_PM = "TK810@BINANCE_PORTFOLIO_MARGIN"
BIN_SPOT = "TK810@BINANCE_SPOT"
HL_SPOT = "TRADING_06@HYPERLIQUID_SPOT"
HL_FUT = "TRADING_06@HYPERLIQUID_FUTURES"
BITSTAMP = "MOON-TOKKA@BITSTAMP"   # Bitstamp Moon tokenized-equity spot (dormant)
NTV_ACCT = "TRADING_01@NATIVECORE"  # Native Core spot-credit (snaps: tq_hist_position_mo)
RH_ACCT = "WALLET_CRB_EVM_02_ROBINHOOD"   # Robinhood-chain RFQ maker wallet
RH_WALLET = "0x9f736f87e6293ac1bd9142e257dbfac8b7acf1ae"
RH_USDG = "USDG"                   # quote token symbol on Robinhood chain
RH_API = ("https://robinhoodchain.blockscout.com/api/v2/addresses/"
          + RH_WALLET + "/token-transfers")
SPOT_COIN = {"SPCXD": "@465", "HYPE": "@107"}   # HL spot token -> pair coin

# Account-name SQL predicate for every 8041 (Central Risk Book) account carrying
# venue balance snapshots. Bitstamp Moon is included so recon activates the
# moment its tq_hist_balance snapshots start flowing; there are none yet, so it
# contributes no rows today (dormant wiring).
ACCT_SQL = ("(account_name LIKE 'TK810@%%' OR account_name LIKE 'TRADING_06@%%' "
            "OR account_name LIKE 'MOON-TOKKA@BITSTAMP%%')")


def _load_venue_map():
    """{refdata account name -> venue} from public/refdata/accounts.json (exchange)."""
    p = Path(__file__).resolve().parent.parent / "public" / "refdata" / "accounts.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {r["name"]: r["venue"] for r in d.get("exchange", [])}


_VENUE_MAP = _load_venue_map()


def venue_of(account_name):
    """Resolve a snapshot account_name to its venue via refdata (match on base)."""
    for base, ven in sorted(_VENUE_MAP.items(), key=lambda kv: -len(kv[0])):
        if account_name.startswith(base):
            return ven
    for tok in ("BINANCE", "HYPERLIQUID", "ROBINHOOD", "NATIVECORE"):
        if tok in account_name:
            return "NATIVE CORE" if tok == "NATIVECORE" else tok
    return "?"


def env(key):
    for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return ""


# Blockscout PRO keys: metered ONLY via the api.blockscout.com/<chain_id>
# gateway — instance domains silently IGNORE the apikey param (verified
# 2026-07-21). Free tier = 100K credits/day @ 5 RPS per key; on 402/403/429
# _bs_get rotates to the next key. No keys → anonymous instance access.
_BS_KEYS = [k for k in (env("BLOCKSCOUT_API_KEY"),
                        env("BLOCKSCOUT_API_KEY2")) if k]
_bs_key_idx = 0


def _bs_keyed(url):
    """Route a Blockscout instance URL through the metered PRO gateway."""
    if not _BS_KEYS:
        return url
    url = url.replace("https://robinhoodchain.blockscout.com/",
                      "https://api.blockscout.com/4663/")
    return (url + ("&" if "?" in url else "?")
            + "apikey=" + _BS_KEYS[_bs_key_idx])


def _bs_get(url):
    """GET a Blockscout page dict: retries transient failures, rotates to the
    next API key when the active one's daily credit pool is exhausted."""
    global _bs_key_idx
    for attempt in range(12):
        try:
            r = urllib.request.urlopen(urllib.request.Request(
                _bs_keyed(url), headers={"User-Agent": "Mozilla/5.0"}),
                timeout=30)
            body = json.loads(r.read())
            if isinstance(body, dict):   # 200 + "Internal server error" body
                return body
        except urllib.error.HTTPError as e:
            # 429 = transient RPS burst: back off and retry the SAME key.
            # Only 402/403 (credits/auth) rotates — a 429-triggered rotation
            # onto a dead key #2 killed the 2026-07-23 recon run.
            if e.code in (402, 403) and _bs_key_idx + 1 < len(_BS_KEYS):
                _bs_key_idx += 1
                print(f"  (blockscout key exhausted -> key #{_bs_key_idx + 1})")
                continue
            if attempt == 11:
                raise
        except Exception:                # URLError, IncompleteRead, resets
            if attempt == 11:
                raise
        time.sleep(min(30, 2 * (attempt + 1)))
    raise RuntimeError("Blockscout kept returning non-dict bodies")


def to_ms(dt):
    return int((dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp() * 1000)


def _pg():
    import psycopg2
    return psycopg2.connect(host=PG_HOST, port=PG_PORT, user=PG_USER, password=PG_PASS,
                            database=PG_DB, connect_timeout=15)


def instrument_mo_map():
    """{raw venue instrument -> standardized instrument_mo} from the snapshots
    (e.g. SPCX-P/USDT@BINANCE_USDT_FUTURE -> SPCXUSDT, HYPE-P/USD@... -> HYPEUSD)."""
    pg = _pg()
    out = {}
    try:
        cur = pg.cursor()
        for tbl in ("tq_hist_balance", "tq_hist_position"):
            cur.execute(
                "SELECT DISTINCT instrument, instrument_mo FROM " + tbl
                + " WHERE " + ACCT_SQL
                + "   AND instrument_mo IS NOT NULL AND record_ts >= '2026-06-01'")
            for inst, mo in cur.fetchall():
                if inst and mo:
                    out[inst] = mo
    finally:
        pg.close()
    return out


def to_mo(inst, mo_map):
    """Map a raw/constructed instrument label to its instrument_mo, with fallbacks
    for HL spot-token (TOKEN/USDC@HYPERLIQUID_SPOT) and HL perp-coin (HYPE, xyz:X) forms."""
    if inst in mo_map:
        return mo_map[inst]
    if "/USDC@HYPERLIQUID_SPOT" in inst:                 # spot token leg -> base token
        return mo_map.get(inst.split("/")[0], inst.split("/")[0])
    full = inst + "-P/USD@HYPERLIQUID_FUTURES"           # HL perp coin -> full perp inst
    if full in mo_map:
        return mo_map[full]
    return inst


def snaps(boundary_dt):
    """{(account, instrument): (signed_qty, ts)} for both accounts at a boundary."""
    pg = _pg()
    out = {}
    try:
        cur = pg.cursor()
        hi = boundary_dt + timedelta(minutes=BUF)
        cur.execute("""
            SELECT DISTINCT ON (account_name, instrument)
                account_name, instrument, instrument_type, side, total_qty, record_ts
            FROM tq_hist_balance
            WHERE """ + ACCT_SQL + """
              AND record_ts >= %s AND record_ts < %s
            ORDER BY account_name, instrument, record_ts
        """, (boundary_dt, hi))
        for a, i, it, s, q, ts in cur.fetchall():
            sq = float(q)
            if "PERP" in str(it or "").upper() and (s or "").lower() == "short":
                sq = -abs(sq)
            out[(a, i)] = (D(str(sq)), ts)
    finally:
        pg.close()
    return out


def _boundary_key(sod, eod):
    """A snap key present in BOTH boundaries, to read the window record_ts from.

    Any account's snap record_ts works; it must just exist in both dicts. Prefer
    the SPCX perp leg; fall back to any common key (new accounts like
    TK810@BINANCE_PORTFOLIO_MARGIN may appear in only one boundary).
    """
    common = set(sod) & set(eod)
    if not common:
        raise RuntimeError("no common (account, instrument) snap key across SOD/EOD")
    for k in common:
        if k[0] == BIN_FUT and "SPCX" in str(k[1]).upper():
            return k
    return sorted(common)[0]


def unrealized_sum(account, inst_like, boundary_dt):
    pg = _pg()
    try:
        cur = pg.cursor()
        hi = boundary_dt + timedelta(minutes=BUF)
        cur.execute("""
            SELECT COALESCE(SUM(u), 0) FROM (
              SELECT DISTINCT ON (instrument) unsettled_pnl u FROM tq_hist_position
              WHERE account_name = %s AND instrument ILIKE %s
                AND record_ts >= %s AND record_ts < %s
              ORDER BY instrument, record_ts) x
        """, (account, inst_like, boundary_dt, hi))
        return D(str(cur.fetchone()[0]))
    finally:
        pg.close()


# ── binance ──
def _bin(path, params):
    k, s = env("810.BINANCE_API_KEY"), env("810.BINANCE_API_SECRET")
    p = dict(params)
    p["timestamp"] = int(time.time() * 1000)
    p["recvWindow"] = 60000
    qs = urllib.parse.urlencode(p)
    sig = hmac.new(s.encode(), qs.encode(), hashlib.sha256).hexdigest()
    return json.loads(urllib.request.urlopen(urllib.request.Request(
        "https://papi.binance.com" + path + "?" + qs + "&signature=" + sig,
        headers={"X-MBX-APIKEY": k}), timeout=20).read())


def bin_pos_net(symbol, w0, w1):
    fills, seen = [], set()
    seed = _bin("/papi/v1/um/userTrades", {"symbol": symbol, "limit": 1000, "startTime": 1781000000000})
    fid = min(int(f["id"]) for f in seed) if seed else 0
    while True:
        b = _bin("/papi/v1/um/userTrades", {"symbol": symbol, "limit": 1000, "fromId": fid})
        if not b:
            break
        new = [f for f in b if int(f["id"]) not in seen]
        for f in new:
            seen.add(int(f["id"]))
        fills += new
        if len(b) < 1000:
            break
        fid = max(int(f["id"]) for f in b) + 1
    win = [f for f in fills if w0 <= int(f["time"]) < w1]
    net = sum((D(f["qty"]) * (D(1) if f["buyer"] else D(-1)) for f in win), ZERO)
    return net, len(win)


def bin_income(w0, w1):
    rows, cur = [], w0
    while True:
        b = _bin("/papi/v1/um/income", {"startTime": cur, "endTime": w1, "limit": 1000})
        if not b:
            break
        rows += b
        if len(b) < 1000:
            break
        cur = max(int(r["time"]) for r in b) + 1
    cash, transfer, n = ZERO, ZERO, 0
    for r in rows:
        if not (w0 <= int(r["time"]) < w1):
            continue
        n += 1
        amt = D(str(r["income"]))
        if "TRANSFER" in str(r.get("incomeType", "")).upper():
            transfer += amt
        else:
            cash += amt
    return cash, transfer, n


def _sapi(path, params):
    k, s = env("810.BINANCE_API_KEY"), env("810.BINANCE_API_SECRET")
    p = dict(params)
    p["timestamp"] = int(time.time() * 1000)
    p["recvWindow"] = 60000
    qs = urllib.parse.urlencode(p)
    sig = hmac.new(s.encode(), qs.encode(), hashlib.sha256).hexdigest()
    return json.loads(urllib.request.urlopen(urllib.request.Request(
        "https://api.binance.com" + path + "?" + qs + "&signature=" + sig,
        headers={"X-MBX-APIKEY": k}), timeout=25).read())


def bin_transfers_usdt(w0, w1):
    """Net USDT universal transfers per Binance wallet in [w0, w1) (+in / -out).
    Dedups by tranId — Binance echoes one transfer under several type filters
    (e.g. MAIN_PORTFOLIO_MARGIN and MAIN_MARGIN return the same tranId)."""
    PAIRS = [("MAIN_PORTFOLIO_MARGIN", "MAIN", "PORTFOLIO_MARGIN"),
             ("PORTFOLIO_MARGIN_MAIN", "PORTFOLIO_MARGIN", "MAIN"),
             ("MAIN_FUNDING", "MAIN", "FUNDING"),
             ("FUNDING_MAIN", "FUNDING", "MAIN")]
    moves, seen = defaultdict(lambda: ZERO), set()
    for t, frm, to in PAIRS:
        try:
            r = _sapi("/sapi/v1/asset/transfer",
                      {"type": t, "startTime": w0, "endTime": w1, "size": 100})
        except Exception:
            continue
        for x in (r.get("rows", []) if isinstance(r, dict) else r):
            if x.get("asset") != "USDT" or x.get("tranId") in seen:
                continue
            seen.add(x.get("tranId"))
            amt = D(str(x["amount"]))
            moves[frm] -= amt
            moves[to] += amt
    return moves


def bin_sub_master_spot(w0, w1):
    """Net flow PER ASSET into the 810 sub-account's SPOT wallet via master<->sub
    transfers in [w0, w1) (+in / -out), as {asset: net}. These are invisible to
    the universal transfer endpoint; only `subUserHistory` exposes them to a
    sub-account key. (Was USDT-only until 2026-07-14 — the ETH/USDC/TSLAB spot
    moves around the B-token trading made the per-asset view necessary.)"""
    net = defaultdict(lambda: ZERO)
    for ty, sign in ((1, D(1)), (2, D(-1))):   # 1 = into sub, 2 = out of sub
        try:
            r = _sapi("/sapi/v1/sub-account/transfer/subUserHistory",
                      {"type": ty, "startTime": w0, "endTime": w1, "limit": 500})
        except Exception:
            continue
        for x in (r if isinstance(r, list) else r.get("rows", [])):
            wallet = x.get("toAccountType") if ty == 1 else x.get("fromAccountType")
            if wallet == "SPOT":
                net[str(x.get("asset"))] += sign * D(str(x["qty"]))
    return net


def bin_spot_user_trades_raw(symbol):
    """Full plain-spot myTrades walk for one symbol (raw venue rows)."""
    fills, seen = [], set()
    seed = _sapi("/api/v3/myTrades", {"symbol": symbol, "limit": 1000,
                                      "startTime": 1781000000000})
    if not seed:
        return []
    fid = min(int(f["id"]) for f in seed)
    while True:
        b = _sapi("/api/v3/myTrades", {"symbol": symbol, "limit": 1000, "fromId": fid})
        if not b:
            break
        new = [f for f in b if int(f["id"]) not in seen]
        for f in new:
            seen.add(int(f["id"]))
        fills += new
        if len(b) < 1000:
            break
        fid = max(int(f["id"]) for f in b) + 1
    return fills


def _bin_spot_symbol(asset):
    """Snapshot asset -> its traded spot symbol (ETH trades against USDC)."""
    return "ETHUSDC" if asset == "ETH" else asset + "USDT"


def _bin_spot_pull(assets):
    """{symbol: raw spot fills} per snapshot asset — deposit-only assets that
    have no Binance listing (e.g. TSLAB) 400 on myTrades and count as no
    fills; their balance moves are transfers, covered by subUserHistory."""
    out = {}
    for x in assets:
        sym = _bin_spot_symbol(x)
        try:
            out[sym] = bin_spot_user_trades_raw(sym)
        except Exception:
            out[sym] = []
    return out


# ── hyperliquid ──
def _hl_end_ms():
    """Dynamic upper bound for HL pulls: now + 1 day. A fixed constant silently
    truncates every fill/ledger event after it (was 1782200000000 = 2026-06-23
    07:33 UTC). Evaluated per-call so it never expires."""
    return int(time.time() * 1000) + 86_400_000


def _hl(b):
    for attempt in range(6):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(
                "https://api.hyperliquid.xyz/info", data=json.dumps(b).encode(),
                headers={"Content-Type": "application/json"}), timeout=30).read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 5:
                time.sleep(2 * (attempt + 1))
                continue
            raise


def hl_fills():
    addr = env("TRADING_06@HYPERLIQUID")
    out, seen, start = [], set(), 1778000000000
    while True:
        b = _hl({"type": "userFillsByTime", "user": addr, "startTime": start,
                 "endTime": _hl_end_ms(), "aggregateByTime": False})
        if not b:
            break
        fr = [f for f in b if f["tid"] not in seen]
        for f in fr:
            seen.add(f["tid"])
        out += fr
        bm = max(int(f["time"]) for f in b)
        if len(b) < 2000 or bm <= start:
            break
        start = bm + 1
    return out


def hl_funding():
    addr = env("TRADING_06@HYPERLIQUID")
    out, seen, start = [], set(), 1778000000000
    while True:
        b = _hl({"type": "userFunding", "user": addr, "startTime": start})
        if not b:
            break
        fr = [r for r in b if (r["time"], r["delta"]["coin"]) not in seen]
        for r in fr:
            seen.add((r["time"], r["delta"]["coin"]))
        out += fr
        bm = max(int(r["time"]) for r in b)
        if len(b) < 500 or bm <= start:
            break
        start = bm + 1
    return out


def hl_ledger():
    addr = env("TRADING_06@HYPERLIQUID")
    return _hl({"type": "userNonFundingLedgerUpdates", "user": addr,
                "startTime": 1778000000000, "endTime": _hl_end_ms()})


def pool_of(coin):
    if coin.startswith("@"):
        return "spot"
    if coin.startswith("xyz:"):
        return "xyz"
    return "main"


_RH_CACHE = None
RH_XFER_CACHE_P = Path(__file__).resolve().parent / "rh_transfer_cache.json.gz"
RH_PULL_WORKERS = 8


def _bs_ts(item):
    return datetime.strptime(item["timestamp"].split(".")[0],
                             "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def _slim(t):
    """Only the transfer fields rh_events folds on — the raw Blockscout item
    is ~1KB of nested metadata; slimmed the full-history disk cache stays MBs."""
    tok = t.get("token") or {}
    return {"transaction_hash": t.get("transaction_hash"),
            "timestamp": t.get("timestamp"),
            "block_number": t.get("block_number"),
            "index": t.get("index", t.get("log_index")),
            "from": {"hash": (t.get("from") or {}).get("hash")},
            "to": {"hash": (t.get("to") or {}).get("hash")},
            "token": {"address_hash": tok.get("address_hash"),
                      "symbol": tok.get("symbol"),
                      "decimals": tok.get("decimals")},
            "total": {"value": (t.get("total") or {}).get("value")}}


def _rh_page(params):
    return _bs_get(RH_API + (("?" + urllib.parse.urlencode(params))
                             if params else ""))


def _rh_worker_bounds(floor_blk, head_blk):
    """Descending block edges splitting (floor_blk, head_blk] into ranges of
    roughly equal FILL volume (stored trade-date octiles -> blocks via binary
    search) — raw block splits would idle most workers because activity sits
    in a narrow recent band. Small gaps skip the probes and go single-range."""
    if head_blk - floor_blk < 150_000:
        return [head_blk, floor_blk]
    import avgcost_db as _adb
    conn = _adb.connect()
    cur = conn.cursor()
    cur.execute("""SELECT percentile_disc(ARRAY[0.125,0.25,0.375,0.5,
                                                0.625,0.75,0.875])
                       WITHIN GROUP (ORDER BY trade_date)
                   FROM trades_spot_avgcost
                   WHERE instrument LIKE '%%@ROBINHOOD'""")
    row = cur.fetchone()
    conn.close()
    dates = sorted({d for d in (row[0] or [])}, reverse=True)
    edges = [head_blk]
    for dt in dates:                       # newest -> oldest interior edges
        lo, hi = floor_blk, edges[-1]
        target = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        while hi - lo > 2000:
            mid = (lo + hi) // 2
            pr = _rh_page({"block_number": mid, "index": 0}).get("items", [])
            if pr and _bs_ts(pr[0]) >= target:
                hi = mid
            else:
                lo = mid
        if floor_blk < lo < edges[-1]:
            edges.append(lo)
    edges.append(floor_blk)
    return edges


def _rh_pull_transfers(floor_blk):
    """All wallet token transfers with block_number > floor_blk, fetched by
    parallel keyset-cursor workers (Blockscout accepts fabricated
    (block_number, index) cursors — verified 2026-07-21). Ranges tile exactly
    (worker keeps block > its floor, next starts at floor+1); identity-dedup
    happens in rh_events."""
    first = _rh_page(None)
    items0 = first.get("items", [])
    if not items0:
        return []
    head_blk = items0[0]["block_number"]
    if head_blk <= floor_blk or not first.get("next_page_params"):
        return [t for t in items0 if t["block_number"] > floor_blk]
    edges = _rh_worker_bounds(floor_blk, head_blk)

    def pull(top, floor):
        out, params = [], (None if top == head_blk
                           else {"block_number": top + 1, "index": 0})
        while True:
            d = _rh_page(params)
            items = d.get("items", [])
            out += [t for t in items if t["block_number"] > floor]
            params = d.get("next_page_params")
            if not params:
                return out
            if items and items[-1]["block_number"] <= floor:
                return out

    def staggered(i):
        time.sleep(i * 0.6)     # spread worker starts under the 5 req/s cap
        return pull(edges[i], edges[i + 1])

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=RH_PULL_WORKERS) as ex:
        futs = [ex.submit(staggered, i) for i in range(len(edges) - 1)]
        chunks = [f.result() for f in futs]
    out = [t for c in chunks for t in c]
    print(f"  (robinhood: pulled {len(out)} transfers, "
          f"{len(edges) - 1} workers, blocks {floor_blk}..{head_blk})")
    return out


def rh_events():
    """(fills, xfers) for the Robinhood-chain RFQ maker wallet, from Blockscout.

    The chain is BOTH trade source and balance source — the wallet has no
    tq_hist_balance snapshots, and every flow is an ERC-20 transfer, so balances
    reconstruct exactly from the transfer history. Each event =
    {"time": ms, "deltas": {SYM: ±qty}}; a swap tx (transfers both ways) is a
    fill, a one-way tx is a funding transfer. Cached for the process AND on
    disk (rh_transfer_cache.json.gz): the full-history walk is paid once,
    later runs top up only blocks above the cached high-water mark."""
    global _RH_CACHE
    if _RH_CACHE is not None:
        return _RH_CACHE
    cached, floor = [], 0
    if RH_XFER_CACHE_P.exists():
        with gzip.open(RH_XFER_CACHE_P, "rt", encoding="utf-8") as f:
            obj = json.load(f)
        cached = obj["transfers"]
        floor = max(0, obj["max_block"] - 1_000)   # overlap; dedup absorbs
    fresh = [_slim(t) for t in _rh_pull_transfers(floor)]
    seen, transfers = set(), []
    for t in cached + fresh:
        k = (t["transaction_hash"], t["token"]["address_hash"],
             t["from"]["hash"], t["to"]["hash"], t["total"]["value"],
             t["block_number"], t.get("index"))
        if k not in seen:
            seen.add(k)
            transfers.append(t)
    if fresh:
        with gzip.open(RH_XFER_CACHE_P, "wt", encoding="utf-8") as f:
            json.dump({"max_block": max(t["block_number"] for t in transfers),
                       "transfers": transfers}, f)
    by_tx = defaultdict(list)
    for t in transfers:
        by_tx[t["transaction_hash"].lower()].append(t)
    fills, xfers = [], []
    for tx, ts in by_tx.items():
        deltas = defaultdict(lambda: ZERO)
        has_in = has_out = False
        for t in ts:
            tok = t.get("token") or {}
            sym = str(tok.get("symbol") or "?").upper()
            dec = int(tok.get("decimals") or 18)
            val = D(int((t.get("total") or {}).get("value") or 0)) / D(10) ** dec
            frm = (t.get("from") or {}).get("hash", "").lower()
            to = (t.get("to") or {}).get("hash", "").lower()
            if frm == RH_WALLET:
                deltas[sym] -= val
                has_out = True
            if to == RH_WALLET:
                deltas[sym] += val
                has_in = True
        t_ms = int(datetime.strptime(ts[0]["timestamp"], "%Y-%m-%dT%H:%M:%S.%fZ")
                   .replace(tzinfo=timezone.utc).timestamp() * 1000)
        evt = {"time": t_ms, "deltas": dict(deltas)}
        (fills if (has_in and has_out) else xfers).append(evt)
    _RH_CACHE = (fills, xfers)
    return _RH_CACHE


def rh_balances(t_ms):
    """{SYM: qty} wallet balances at t_ms, reconstructed as the sum of all
    transfer deltas strictly before t_ms (the wallet was born empty)."""
    fills, xfers = rh_events()
    bal = defaultdict(lambda: ZERO)
    for e in fills + xfers:
        if e["time"] < t_ms:
            for s, v in e["deltas"].items():
                bal[s] += v
    return bal


def _rh_inject_snaps(bnd, t_ms):
    """Add synthetic (RH_ACCT, SYM) balance entries at t_ms into a snaps dict
    (naive UTC ts, matching the tq_hist record_ts convention)."""
    ts = datetime.fromtimestamp(t_ms / 1000, timezone.utc).replace(tzinfo=None)
    for s, q in rh_balances(t_ms).items():
        if q != 0:
            bnd[(RH_ACCT, s)] = (q, ts)


_NTV_CACHE = None


def ntv_trades():
    """Stored Native fills (trades_spot_avgcost) as window-filterable events:
    {"time" ms, "sym", "qty" signed, "px", "fee_asset", "fee"}. The store is the
    validated CSV∪ClickHouse union (see native_trades_source.py). Cached."""
    global _NTV_CACHE
    if _NTV_CACHE is not None:
        return _NTV_CACHE
    import avgcost_db as adb
    conn = adb.connect()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT extract(epoch FROM trade_date) * 1000, base_asset, base_amount,
                   direction, price, fee_asset, fee_amount
            FROM trades_spot_avgcost WHERE account = %s
        """, (NTV_ACCT,))
        rows = cur.fetchall()
    finally:
        conn.close()
    out = []
    for ms, sym, qty, direction, px, fa, fee in rows:
        sign = D(1) if str(direction).upper() == "LONG" else D(-1)
        out.append({"time": int(ms), "sym": str(sym).upper(),
                    "qty": D(str(qty)) * sign, "px": D(str(px)),
                    "fee_asset": str(fa or "").upper(), "fee": D(str(fee or 0))})
    _NTV_CACHE = out
    return out


def ntv_snaps(boundary_dt):
    """{(NTV_ACCT, SYM): (signed_qty, ts)} at a boundary, from the hourly
    tq_hist_position_mo snapshots (MO DB — the Native streamer's table)."""
    import avgcost_db as adb
    conn = adb.connect()
    out = {}
    try:
        cur = conn.cursor()
        hi = boundary_dt + timedelta(minutes=BUF)
        cur.execute("""
            SELECT DISTINCT ON (instrument) instrument, side, pos_qty, record_ts
            FROM tq_hist_position_mo
            WHERE account_name = %s AND record_ts >= %s AND record_ts < %s
            ORDER BY instrument, record_ts
        """, (NTV_ACCT, boundary_dt, hi))
        for inst, side, q, ts in cur.fetchall():
            sq = D(str(q))
            if str(side or "").lower() == "short":
                sq = -abs(sq)
            out[(NTV_ACCT, inst.split("@")[0].upper())] = (sq, ts)
    finally:
        conn.close()
    return out


def hl_perp_pnl(date_iso):
    """Per-leg PnL for HL futures (HYPE + xyz:*): realized + ΔUnreal + funding − fees.

    Uses HL's own realized (closedPnl) and venue unsettled_pnl (tq_hist_position)
    — no mark needed. Returns list of dicts. Net-flat legs (e.g. HYPE) have ΔUnreal 0.
    """
    sod_dt = datetime.strptime(date_iso, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    eod_dt = sod_dt + timedelta(days=1)
    sod, eod = snaps(sod_dt), snaps(eod_dt)
    anyk = _boundary_key(sod, eod)
    w0, w1 = to_ms(sod[anyk][1]), to_ms(eod[anyk][1])
    realized, usdcfee, cnt = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO), defaultdict(int)
    for f in hl_fills():
        if not (w0 <= int(f["time"]) < w1) or f["coin"].startswith("@"):
            continue
        realized[f["coin"]] += D(f.get("closedPnl", "0"))
        cnt[f["coin"]] += 1
        if f["feeToken"] == "USDC":
            usdcfee[f["coin"]] += D(f["fee"])
    fund = defaultdict(lambda: ZERO)
    for r in hl_funding():
        if w0 <= int(r["time"]) < w1:
            fund[r["delta"]["coin"]] += D(str(r["delta"]["usdc"]))

    def _futbal(snap_dict, coin):
        for (a, i), (q, _) in snap_dict.items():
            if a == HL_FUT and i.startswith(coin):
                return q
        return ZERO

    legs = []
    for c in sorted(realized, key=lambda x: -cnt[x]):
        du = (unrealized_sum(HL_FUT, c + "%", eod_dt) - unrealized_sum(HL_FUT, c + "%", sod_dt)
              ) if c.startswith("xyz:") else ZERO
        legs.append({"coin": c, "n": cnt[c], "realized": realized[c], "du": du,
                     "funding": fund[c], "fees": usdcfee[c],
                     "total": realized[c] + du + fund[c] - usdcfee[c],
                     "sod_bal": _futbal(sod, c), "eod_bal": _futbal(eod, c)})
    return {"legs": legs, "sod": sod, "eod": eod}


def _manual_agg(w0, w1):
    """Net booked manual (source='manual') trades in [w0, w1) from the avg-cost
    store: ({base_asset -> net signed qty}, net USDC cash consideration).
    LONG => +qty / cash out; SHORT => -qty / cash in. Reference figures for the
    recon's informational manual column (Dinari settles off-venue on the credit
    line, so the USDC figure is NOT an HL flow and stays out of the identity)."""
    import avgcost_db as adb
    w0d = datetime.fromtimestamp(w0 / 1000, timezone.utc)
    w1d = datetime.fromtimestamp(w1 / 1000, timezone.utc)
    qty, cash = defaultdict(lambda: ZERO), ZERO
    try:
        conn = adb.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT base_asset, direction, base_amount, price "
                    "FROM trades_spot_avgcost WHERE source = 'manual' "
                    "  AND trade_date >= %s AND trade_date < %s",
                    (w0d, w1d))
                for base_asset, direction, amt, px in cur.fetchall():
                    sign = D(1) if str(direction).upper() == "LONG" else D(-1)
                    sq = sign * D(str(amt))
                    qty[str(base_asset).upper()] += sq
                    cash += -(sq * D(str(px)))
        finally:
            conn.close()
    except Exception as e:
        print(f"  (manual agg skipped: {e})")
    return qty, cash


def drange(a, b):
    """Inclusive list of YYYY-MM-DD strings from a to b."""
    da, db = datetime.strptime(a, "%Y-%m-%d"), datetime.strptime(b, "%Y-%m-%d")
    out, d = [], da
    while d <= db:
        out.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return out


def _dt0(d):
    return datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc)


# ── raw Binance pulls (pull once, slice to any sub-window in-memory) ──
def bin_user_trades_raw(symbol):
    """ALL userTrades for a symbol (paginated, unfiltered). Slice per window with
    bin_net_in — so an MTD run pulls each symbol once, not once per day."""
    fills, seen = [], set()
    seed = _bin("/papi/v1/um/userTrades", {"symbol": symbol, "limit": 1000, "startTime": 1781000000000})
    fid = min(int(f["id"]) for f in seed) if seed else 0
    while True:
        b = _bin("/papi/v1/um/userTrades", {"symbol": symbol, "limit": 1000, "fromId": fid})
        if not b:
            break
        new = [f for f in b if int(f["id"]) not in seen]
        for f in new:
            seen.add(int(f["id"]))
        fills += new
        if len(b) < 1000:
            break
        fid = max(int(f["id"]) for f in b) + 1
    return fills


def bin_net_in(fills, w0, w1):
    win = [f for f in fills if w0 <= int(f["time"]) < w1]
    net = sum((D(f["qty"]) * (D(1) if f["buyer"] else D(-1)) for f in win), ZERO)
    return net, len(win)


def bin_income_raw(w0, w1):
    """Raw income rows over [w0, w1) — slice per day with bin_income_in."""
    rows, cur = [], w0
    while True:
        b = _bin("/papi/v1/um/income", {"startTime": cur, "endTime": w1, "limit": 1000})
        if not b:
            break
        rows += b
        if len(b) < 1000:
            break
        cur = max(int(r["time"]) for r in b) + 1
    return rows


def bin_income_in(rows, w0, w1, asset=None):
    """UM income in [w0, w1); asset filters to one margin currency (the
    ETHUSDC perp realizes/funds in USDC — its income must not land on the
    USDT cash row)."""
    cash, transfer, n = ZERO, ZERO, 0
    for r in rows:
        if not (w0 <= int(r["time"]) < w1):
            continue
        if asset and str(r.get("asset", "USDT")) != asset:
            continue
        n += 1
        amt = D(str(r["income"]))
        if "TRANSFER" in str(r.get("incomeType", "")).upper():
            transfer += amt
        else:
            cash += amt
    return cash, transfer, n


COLS = ["venue", "account", "instrument", "Trades_API", "Trades_Manual", "SOD bal", "EOD bal",
        "balance Δ", "trade/cash Δ", "trade/cash Δ (manual)", "unreal", "transfers", "diff", "status"]


def _compute_rows(sod, eod, sod_dt, eod_dt, w0, w1, *, fills, funding, ledger,
                  bin_trades, income_rows, uni_xfer, sub_spot, man_qty, man_usdc,
                  mo_map, rh_fills=(), rh_xfers=(), ntv_fills=(),
                  bin_spot_trades=None, skip_zero=True):
    """Per-window recon rows (numeric dicts) — the identity logic, with all venue
    data injected so a caller can slice any sub-window. skip_zero drops rows whose
    balance Δ is ~0 (daily display); set False for MTD aggregation so cash legs
    still contribute their unreal/realized on flat-balance days (telescoping)."""
    net_qty, realized, usdc_fee, inkind = (defaultdict(lambda: ZERO) for _ in range(4))
    spot_usdc = defaultdict(lambda: ZERO)
    n_by_coin = defaultdict(int)
    for f in fills:
        if not (w0 <= int(f["time"]) < w1):
            continue
        c = f["coin"]
        n_by_coin[c] += 1
        sz, px = D(f["sz"]), D(f["px"])
        net_qty[c] += sz if f["side"] == "B" else -sz
        realized[c] += D(f.get("closedPnl", "0"))
        if f["feeToken"] == "USDC":
            usdc_fee[c] += D(f["fee"])
        else:
            inkind[c] += D(f["fee"])
        if c.startswith("@"):
            spot_usdc[c] += (sz * px) if f["side"] == "A" else (-sz * px)
    fund_by_pool = defaultdict(lambda: ZERO)
    for r in funding:
        if w0 <= int(r["time"]) < w1:
            d = r["delta"]
            fund_by_pool[pool_of(d["coin"])] += D(str(d["usdc"]))
    real_pool, fee_pool = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    for c in set(realized) | set(usdc_fee):
        real_pool[pool_of(c)] += realized[c]
        fee_pool[pool_of(c)] += usdc_fee[c]
    addr = env("TRADING_06@HYPERLIQUID").lower()
    POOL = {"spot": "spot", "": "main", "perp": "main", "xyz": "xyz"}
    tx = defaultdict(lambda: ZERO)
    tx_in_n = defaultdict(int)
    for u in ledger:
        if not (w0 <= int(u["time"]) < w1):
            continue
        d = u.get("delta", {})
        if d.get("type") in ("send", "spotTransfer"):
            tok = str(d.get("token", "")).upper()
            amt = D(str(d.get("amount", 0)))
            if str(d.get("user", "")).lower() == addr:
                tx[(tok, POOL.get(d.get("sourceDex"), "main"))] -= amt
            if str(d.get("destination", "")).lower() == addr:
                tx[(tok, POOL.get(d.get("destinationDex"), "main"))] += amt
                tx_in_n[(tok, POOL.get(d.get("destinationDex"), "main"))] += 1
    bin_cash, bin_xfer, bin_n = bin_income_in(income_rows, w0, w1, asset="USDT")
    binc_cash, binc_xfer, binc_n = bin_income_in(income_rows, w0, w1, asset="USDC")

    # Binance plain-spot window aggregates: token Δ / quote cash Δ per asset,
    # commissions (paid in BNB) tracked as their own asset row.
    bsp_qty, bsp_cash = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    bsp_n, bsp_ncash = defaultdict(int), defaultdict(int)
    bsp_bnb, bsp_nbnb = ZERO, 0
    for sym, fl in (bin_spot_trades or {}).items():
        base, quote = sym[:-4], sym[-4:]
        for f in fl:
            if not (w0 <= int(f["time"]) < w1):
                continue
            sq = D(f["qty"]) * (D(1) if f["isBuyer"] else D(-1))
            bsp_qty[base] += sq
            bsp_n[base] += 1
            bsp_cash[quote] -= sq * D(f["price"])
            bsp_ncash[quote] += 1
            ca = f.get("commissionAsset")
            if ca == "BNB":
                bsp_bnb += D(f["commission"])
                bsp_nbnb += 1
            elif ca == quote:
                bsp_cash[quote] -= D(f["commission"])
            elif ca == base:
                bsp_qty[base] -= D(f["commission"])

    # Robinhood-chain window aggregates: traded qty / USDG cash from fill txs,
    # funding transfers per token; fills counted once per non-USDG token.
    rh_qty, rh_xf = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    rh_usdg, rh_nn = ZERO, defaultdict(int)
    for e in rh_fills:
        if w0 <= e["time"] < w1:
            for s, v in e["deltas"].items():
                if s == RH_USDG:
                    rh_usdg += v
                else:
                    rh_qty[s] += v
                    rh_nn[s] += 1
    for e in rh_xfers:
        if w0 <= e["time"] < w1:
            for s, v in e["deltas"].items():
                rh_xf[s] += v

    # Native window aggregates: token Δ = signed qty − in-kind fee (buys pay
    # fee in the BASE token); USDT cash = −Σ qty×px − USDT fees.
    ntv_qty, ntv_ink = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    ntv_cash, ntv_nn = ZERO, defaultdict(int)
    for t in ntv_fills:
        if w0 <= t["time"] < w1:
            s = t["sym"]
            ntv_qty[s] += t["qty"]
            ntv_nn[s] += 1
            ntv_cash += -t["qty"] * t["px"]
            if t["fee_asset"] == "USDT":
                ntv_cash -= t["fee"]
            elif t["fee_asset"] == s:
                ntv_ink[s] += t["fee"]

    out = []
    for k in sorted(set(sod) | set(eod)):
        acct, inst = k
        bal_d = eod.get(k, (ZERO, None))[0] - sod.get(k, (ZERO, None))[0]
        if skip_zero and abs(bal_d) < D("1e-6"):
            continue
        unreal, transfers, td, trd, trd_manual = None, ZERO, None, 0, 0
        td_manual = None
        label = to_mo(inst, mo_map)[:34]
        if acct == BIN_PM and inst == "USDT":
            td = ZERO
            transfers = uni_xfer.get("PORTFOLIO_MARGIN", ZERO) - bin_xfer
        elif acct == BIN_SPOT and inst in ("USDT", "USDC"):
            td, trd = bsp_cash.get(inst, ZERO), bsp_ncash.get(inst, 0)
            transfers = sub_spot.get(inst, ZERO)
            if inst == "USDT":
                transfers += uni_xfer.get("MAIN", ZERO)
        elif acct == BIN_SPOT and inst == "BNB":
            td, trd = -bsp_bnb, bsp_nbnb          # spot commissions paid in BNB
            transfers = sub_spot.get(inst, ZERO)
        elif acct == BIN_SPOT:                    # B-token / ETH position row
            td = bsp_qty.get(inst, ZERO)
            trd = bsp_n.get(inst, 0)
            transfers = sub_spot.get(inst, ZERO)
        elif acct == BIN_FUT and inst == "USDT":
            td, transfers, trd = bin_cash, bin_xfer, bin_n
            unreal = unrealized_sum(BIN_FUT, "%SPCX%", eod_dt) - unrealized_sum(BIN_FUT, "%SPCX%", sod_dt)
        elif acct == BIN_FUT and inst == "USDC":  # ETHUSDC perp margin cash
            td, transfers, trd = binc_cash, binc_xfer, binc_n
            # USDC-margined perps ONLY (ETH-P/USDT is a separate USDT-margined
            # position whose unreal lives on the USDT row's balance)
            unreal = (unrealized_sum(BIN_FUT, "%-P/USDC@%", eod_dt)
                      - unrealized_sum(BIN_FUT, "%-P/USDC@%", sod_dt))
        elif acct == BIN_FUT:  # perp position — keyed by the row's own symbol (not hardcoded)
            sym = to_mo(inst, mo_map)
            td, trd = bin_net_in(bin_trades.get(sym, []), w0, w1)
        elif acct == HL_SPOT and inst == "USDC":
            td = sum(spot_usdc.values(), ZERO) - sum(v for c, v in usdc_fee.items() if c.startswith("@"))
            trd = sum(n for c, n in n_by_coin.items() if c.startswith("@"))
            transfers = tx.get(("USDC", "spot"), ZERO)
            td_manual = man_usdc if man_usdc != 0 else None
        elif acct == HL_SPOT:  # spot token (SPCXD/HYPE)
            coin = SPOT_COIN.get(inst, inst)
            td = net_qty.get(coin, ZERO) - inkind.get(coin, ZERO)
            trd = n_by_coin.get(coin, 0)
            trd_manual = tx_in_n.get((inst.upper(), "spot"), 0)
            transfers = tx.get((inst.upper(), "spot"), ZERO)
            td_manual = man_qty.get(inst.upper())
        elif acct == HL_FUT and inst in ("USDC", "xyz:USDC"):
            pool = "xyz" if inst == "xyz:USDC" else "main"
            td = real_pool[pool] + fund_by_pool[pool] - fee_pool[pool]
            trd = sum(n for c, n in n_by_coin.items() if not c.startswith("@") and pool_of(c) == pool)
            ilk = "xyz:%-P%" if pool == "xyz" else "HYPE"
            unreal = unrealized_sum(HL_FUT, ilk, eod_dt) - unrealized_sum(HL_FUT, ilk, sod_dt)
            transfers = tx.get(("USDC", pool), ZERO)
        elif acct == HL_FUT:  # xyz perp position
            base = inst.split("-P/")[0]
            td = net_qty.get(base, ZERO)
            trd = n_by_coin.get(base, 0)
        elif acct == RH_ACCT and inst == RH_USDG:  # Robinhood cash leg
            td = rh_usdg
            trd = sum(rh_nn.values())
            transfers = rh_xf.get(RH_USDG, ZERO)
        elif acct == RH_ACCT:  # Robinhood token position leg
            td = rh_qty.get(inst, ZERO)
            trd = rh_nn.get(inst, 0)
            transfers = rh_xf.get(inst, ZERO)
        elif acct == NTV_ACCT and inst == "USDT":  # Native cash / credit leg
            td = ntv_cash
            trd = sum(ntv_nn.values())
            # credit-line draws/repays have no ledger feed -> land in diff
        elif acct == NTV_ACCT:  # Native token position leg
            td = ntv_qty.get(inst, ZERO) - ntv_ink.get(inst, ZERO)
            trd = ntv_nn.get(inst, 0)
        accounted = (td or ZERO) + (unreal or ZERO) + transfers
        out.append({"venue": venue_of(acct), "acct": acct, "inst": inst, "label": label,
                    "trd": trd, "trd_manual": trd_manual, "td": td, "td_manual": td_manual,
                    "unreal": unreal, "transfers": transfers, "bal_d": bal_d,
                    "s_bal": sod.get(k, (ZERO,))[0], "e_bal": eod.get(k, (ZERO,))[0],
                    "diff": bal_d - accounted})
    return out


def _fmt_row(r):
    td, td_m, un = r["td"], r["td_manual"], r["unreal"]
    status = ("UNMAPPED" if td is None else "OK" if abs(r["diff"]) < D("0.05") else "CHECK")
    return [r["venue"], r["acct"], r["label"], str(r["trd"]), str(r.get("trd_manual", 0)),
            f"{float(r['s_bal']):,.4f}", f"{float(r['e_bal']):,.4f}",
            f"{float(r['bal_d']):,.4f}", ("—" if td is None else f"{float(td):,.4f}"),
            ("—" if td_m is None else f"{float(td_m):,.4f}"),
            ("—" if un is None else f"{float(un):,.2f}"),
            f"{float(r['transfers']):,.2f}", f"{float(r['diff']):,.4f}", status]


def _render(title, info_lines, display_rows, cols=None):
    rows = display_rows
    flow = cols is None                # default = the flow-recon table
    cols = COLS if cols is None else cols
    ljust_cols = {0, 1, 2, len(cols) - 1} if not flow else {0, 1, 2, 13}
    w = ([max(len(cols[i]), *(len(r[i]) for r in rows)) for i in range(len(cols))]
         if rows else [len(c) for c in cols])

    def bar(a, b, c):
        return a + b.join("─" * (w[i] + 2) for i in range(len(w))) + c

    def line(cs, center=False):
        return "│" + "│".join(" " + (cs[i].center(w[i]) if center else
                                     (cs[i].ljust(w[i]) if i in ljust_cols else cs[i].rjust(w[i]))) + " "
                              for i in range(len(cs))) + "│"

    print(f"\n{title}")
    for ln in info_lines:
        print(ln)
    print(bar("┌", "┬", "┐"))
    print(line(cols, True))
    print(bar("├", "┼", "┤"))
    for r in rows:
        print(line(r))
    print(bar("└", "┴", "┘"))
    if flow:
        print("identity: balance Δ = trade/cash Δ + unreal Δ + transfers.  "
              "HYPE perp/spot net 0 (no balance move).")
        print("trade/cash Δ (manual): net BOOKED Dinari trades (avg-cost store) — "
              "token leg = qty, HL-spot USDC = USDC consideration; reference only "
              "(Dinari settles on the Native credit line), NOT in the identity.")


def run_recon(date_iso):
    sod_dt = _dt0(date_iso)
    eod_dt = sod_dt + timedelta(days=1)
    print(f"Pulling snaps + venue data for full-account recon ({date_iso})...")
    sod, eod = snaps(sod_dt), snaps(eod_dt)
    anyk = _boundary_key(sod, eod)
    w0, w1 = to_ms(sod[anyk][1]), to_ms(eod[anyk][1])
    sod_ts = sorted({ts for _, ts in sod.values()})
    eod_ts = sorted({ts for _, ts in eod.values()})
    sod_note = "" if len(sod_ts) == 1 else f"  (+{len(sod_ts)-1} more, latest {sod_ts[-1]})"
    eod_note = "" if len(eod_ts) == 1 else f"  (+{len(eod_ts)-1} more, latest {eod_ts[-1]})"
    mo_map = instrument_mo_map()
    bin_syms = {to_mo(i, mo_map) for (a, i) in (set(sod) | set(eod)) if a == BIN_FUT and i not in ("USDT", "USDC")}
    bin_trades = {s: bin_user_trades_raw(s) for s in bin_syms}
    spot_assets = {i for (a, i) in (set(sod) | set(eod))
                   if a == BIN_SPOT and i not in ("USDT", "USDC", "BNB")}
    bin_spot_trades = _bin_spot_pull(spot_assets)
    income_rows = bin_income_raw(w0, w1)
    uni_xfer = bin_transfers_usdt(w0, w1)
    sub_spot = bin_sub_master_spot(w0, w1)
    man_qty, man_usdc = _manual_agg(w0, w1)
    try:
        rh_fills, rh_xfers = rh_events()
        _rh_inject_snaps(sod, w0)
        _rh_inject_snaps(eod, w1)
    except Exception as e:
        rh_fills, rh_xfers = (), ()
        print(f"  (robinhood recon legs skipped: {e})")
    try:
        ntv_fills_ = ntv_trades()
        sod.update(ntv_snaps(sod_dt))
        eod.update(ntv_snaps(eod_dt))
    except Exception as e:
        ntv_fills_ = ()
        print(f"  (native recon legs skipped: {e})")
    rows = _compute_rows(sod, eod, sod_dt, eod_dt, w0, w1, fills=hl_fills(), funding=hl_funding(),
                         ledger=hl_ledger(), bin_trades=bin_trades, income_rows=income_rows,
                         uni_xfer=uni_xfer, sub_spot=sub_spot, man_qty=man_qty, man_usdc=man_usdc,
                         mo_map=mo_map, rh_fills=rh_fills, rh_xfers=rh_xfers,
                         ntv_fills=ntv_fills_, bin_spot_trades=bin_spot_trades, skip_zero=True)
    info = [f"  SOD snap (w0): {sod[anyk][1]} UTC{sod_note}",
            f"  EOD snap (w1): {eod[anyk][1]} UTC{eod_note}",
            "  trade/cash Δ + transfers pulled for window [w0, w1)  "
            "(Binance userTrades/income, HL fills/funding/ledger)",
            "  Robinhood (WALLET_CRB_EVM_02): balances CHAIN-RECONSTRUCTED from "
            "Blockscout transfers at w0/w1 (no tq_hist snapshots)",
            "  Native (TRADING_01@NATIVECORE): positions from tq_hist_position_mo; "
            "trade Δ from the stored CSV∪CH union; USDT diff = credit-line flows "
            "(no ledger feed)"]
    if not any(a.startswith(BITSTAMP) for (a, _) in (set(sod) | set(eod))):
        info.append("  Bitstamp Moon (MOON-TOKKA@BITSTAMP): recon wired but DORMANT "
                    "— no tq_hist_balance snapshots yet (PnL table only for now).")
    _render(f"FULL-ACCOUNT RECON — COB {date_iso}", info, [_fmt_row(r) for r in rows])


def run_recon_mtd(cob, inception):
    """One recon table aggregated inception..COB: trade/cash Δ, unreal Δ, transfers
    and Trades counts SUMMED over each day's (validated) recon; balance Δ taken
    from the inception-SOD vs COB-EOD snapshots; diff = Σ daily diffs. Avoids the
    HL fill-reconstruction error of a single 2+ week window (each day's pull is
    small + complete) and the snapshot/fill boundary races mostly cancel."""
    days = drange(inception, cob)
    cob_next = (_dt0(cob) + timedelta(days=1)).strftime("%Y-%m-%d")
    cutoffs = drange(inception, cob_next)
    print(f"Pulling snaps + raw venue data (once) for MTD recon ({inception} -> COB {cob})...")
    snap_cache = {d: snaps(_dt0(d)) for d in cutoffs}
    mo_map = instrument_mo_map()
    fills, funding, ledger = hl_fills(), hl_funding(), hl_ledger()
    bin_syms = {to_mo(i, mo_map) for snp in snap_cache.values()
                for (a, i) in snp if a == BIN_FUT and i not in ("USDT", "USDC")}
    bin_trades = {s: bin_user_trades_raw(s) for s in bin_syms}
    spot_assets = {i for snp in snap_cache.values() for (a, i) in snp
                   if a == BIN_SPOT and i not in ("USDT", "USDC", "BNB")}
    bin_spot_trades = _bin_spot_pull(spot_assets)
    anchor = _boundary_key(snap_cache[inception], snap_cache[cob_next])
    w0_full, w1_full = to_ms(snap_cache[inception][anchor][1]), to_ms(snap_cache[cob_next][anchor][1])
    income_rows = bin_income_raw(w0_full, w1_full)
    try:
        rh_fills, rh_xfers = rh_events()
        for d in cutoffs:
            snp = snap_cache[d]
            t_ref = to_ms(snp[anchor][1]) if anchor in snp else to_ms(_dt0(d))
            _rh_inject_snaps(snp, t_ref)
    except Exception as e:
        rh_fills, rh_xfers = (), ()
        print(f"  (robinhood recon legs skipped: {e})")
    try:
        ntv_fills_ = ntv_trades()
        for d in cutoffs:
            snap_cache[d].update(ntv_snaps(_dt0(d)))
    except Exception as e:
        ntv_fills_ = ()
        print(f"  (native recon legs skipped: {e})")

    acc = {}
    for d in days:
        d1 = (_dt0(d) + timedelta(days=1)).strftime("%Y-%m-%d")
        sod, eod = snap_cache[d], snap_cache[d1]
        try:
            anyk = _boundary_key(sod, eod)
        except RuntimeError:
            continue
        w0, w1 = to_ms(sod[anyk][1]), to_ms(eod[anyk][1])
        uni_xfer = bin_transfers_usdt(w0, w1)
        sub_spot = bin_sub_master_spot(w0, w1)
        man_qty, man_usdc = _manual_agg(w0, w1)
        for r in _compute_rows(sod, eod, _dt0(d), _dt0(d) + timedelta(days=1), w0, w1,
                               fills=fills, funding=funding, ledger=ledger, bin_trades=bin_trades,
                               income_rows=income_rows, uni_xfer=uni_xfer, sub_spot=sub_spot,
                               man_qty=man_qty, man_usdc=man_usdc, mo_map=mo_map,
                               rh_fills=rh_fills, rh_xfers=rh_xfers, ntv_fills=ntv_fills_,
                               bin_spot_trades=bin_spot_trades, skip_zero=False):
            a = acc.setdefault((r["acct"], r["inst"]),
                               {"venue": r["venue"], "label": r["label"], "trd": 0, "trd_manual": 0,
                                "td": ZERO, "td_any": False, "td_manual": ZERO, "tdm_any": False,
                                "unreal": ZERO, "un_any": False, "transfers": ZERO})
            a["trd"] += r["trd"]
            a["trd_manual"] += r.get("trd_manual", 0) or 0
            if r["td"] is not None:
                a["td"] += r["td"]
                a["td_any"] = True
            if r["td_manual"] is not None:
                a["td_manual"] += r["td_manual"]
                a["tdm_any"] = True
            if r["unreal"] is not None:
                a["unreal"] += r["unreal"]
                a["un_any"] = True
            a["transfers"] += r["transfers"]

    sod0, eodN = snap_cache[inception], snap_cache[cob_next]
    display = []
    for k in sorted(acc):
        acct, inst = k
        a = acc[k]
        s_bal, e_bal = sod0.get(k, (ZERO,))[0], eodN.get(k, (ZERO,))[0]
        bal_d = e_bal - s_bal
        td = a["td"] if a["td_any"] else None
        unreal = a["unreal"] if a["un_any"] else None
        td_manual = a["td_manual"] if a["tdm_any"] else None
        diff = bal_d - ((td or ZERO) + (unreal or ZERO) + a["transfers"])
        if all(abs(x) < D("1e-6") for x in (bal_d, td or ZERO, unreal or ZERO, a["transfers"])):
            continue
        display.append(_fmt_row({"venue": a["venue"], "acct": acct, "inst": inst, "label": a["label"],
                                 "trd": a["trd"], "trd_manual": a["trd_manual"], "td": td,
                                 "td_manual": td_manual, "unreal": unreal, "transfers": a["transfers"],
                                 "bal_d": bal_d, "s_bal": s_bal, "e_bal": e_bal, "diff": diff}))
    info = [f"  SOD snap (inception): {sod0[anchor][1]} UTC",
            f"  EOD snap (COB):       {eodN[anchor][1]} UTC",
            f"  daily-aggregated over {len(days)} days [{inception}..{cob}]: trade/cash Δ, unreal Δ, "
            "transfers, Trades summed per day; balance Δ = inception SOD → COB EOD; diff = Σ daily diffs"]
    _render(f"FULL-ACCOUNT RECON — MTD {inception} → COB {cob}  (daily-aggregated)", info, display)


# ── POSITION BUILD-UP vs VENUE BALANCES (stock recon) ───────────────────
# Compares the avg-cost engine's EOD position (build-up of every stored fill)
# against an actual venue balance/position snapshot at the SAME boundary
# (COB+1 00:00 UTC), one row per stored leg, balance SOURCE stated per row:
#   TK810@BINANCE_*          tq_hist_balance (internal snapshot streamer)
#   TRADING_06@HYPERLIQUID_* tq_hist_balance (internal snapshot streamer)
#   TRADING_01@NATIVECORE    tq_hist_position_mo (MO DB, Native streamer)
#   WALLET_CRB_EVM_02        GoldRush historical_balances, robinhood-mainnet
#                            (block pinned at 00:00:00Z of COB+1; token
#                            symbols/decimals via robinhoodchain Blockscout,
#                            cached in goldrush_token_map.json — GoldRush
#                            metadata is null on this Frontier-tier chain)
#   WALLET_ETH_RFQ_01        GoldRush historical_balances, eth-mainnet
#                            (native ETH + WETH combined)
#   MOON-TOKKA@BITSTAMP      none yet -> NO SNAP
# Cash legs (USDT/USDC/USDG) are excluded — the engine builds BASE positions.
# Robinhood inventory arrives by one-way chain transfer (not fills), so the
# identity there is balance = build-up + cumulative funding transfers.
GR_KEY = env("GOLDRUSH_API_KEY")
GR_TOKEN_MAP_P = Path(__file__).resolve().parent / "goldrush_token_map.json"
ETH_RFQ_WALLET = "0x391af49b1793529f430c4b5918da6bb237306865"
WETH_CONTRACT = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
NATIVE_TOKEN = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"


def goldrush_historical_balances(chain, address, date_iso):
    """Raw GoldRush historical_balances items for address at date_iso —
    snapshotted at the block signed 00:00:00Z of date_iso (pass COB+1 for a
    COB EOD boundary; semantics verified 2026-07-14)."""
    url = (f"https://api.covalenthq.com/v1/{chain}/address/{address}/"
           f"historical_balances/?date={date_iso}&key={GR_KEY}")
    d = json.loads(urllib.request.urlopen(urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0"}),   # default python UA -> 403
        timeout=45).read())
    if d.get("error"):
        raise RuntimeError(f"GoldRush {chain}: {d.get('error_message')}")
    return d["data"]["items"]


def _gr_token_map():
    try:
        return json.loads(GR_TOKEN_MAP_P.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _rh_token_meta(contract, cache):
    """(symbol, decimals) for a robinhood-chain token via Blockscout, cached
    on disk — GoldRush returns null metadata for this chain."""
    m = cache.setdefault("robinhood-mainnet", {})
    if contract not in m:
        try:
            r = urllib.request.urlopen(urllib.request.Request(
                _bs_keyed("https://robinhoodchain.blockscout.com/api/v2/tokens/"
                          + contract),
                headers={"User-Agent": "Mozilla/5.0"}), timeout=20)
            t = json.loads(r.read())
            m[contract] = {"symbol": str(t.get("symbol") or "?").upper(),
                           "decimals": int(t.get("decimals") or 18)}
        except Exception:
            m[contract] = {"symbol": "?", "decimals": 18}
        GR_TOKEN_MAP_P.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    return m[contract]["symbol"], m[contract]["decimals"]


def rh_goldrush_balances(date_iso):
    """({SYM: qty}, block_height) for the Robinhood RFQ wallet at date_iso
    00:00Z via GoldRush (independent of the Blockscout transfer stream)."""
    items = goldrush_historical_balances("robinhood-mainnet", RH_WALLET, date_iso)
    cache = _gr_token_map()
    out, block = defaultdict(lambda: ZERO), None
    for it in items:
        block = it.get("block_height", block)
        c = it["contract_address"].lower()
        if c == NATIVE_TOKEN:
            continue                       # gas ETH, not a position
        sym, dec = _rh_token_meta(c, cache)
        out[sym] += D(int(it["balance"])) / D(10) ** dec
    return out, block


def eth_goldrush_balance(date_iso):
    """(ETH+WETH qty, block_height) for the ETH RFQ wallet at date_iso 00:00Z
    via GoldRush eth-mainnet."""
    items = goldrush_historical_balances("eth-mainnet", ETH_RFQ_WALLET, date_iso)
    tot, block = ZERO, None
    for it in items:
        block = it.get("block_height", block)
        c = it["contract_address"].lower()
        if c in (NATIVE_TOKEN, WETH_CONTRACT):
            dec = int(it.get("contract_decimals") or 18)
            tot += D(int(it["balance"])) / D(10) ** dec
    return tot, block


def run_position_recon(date_iso):
    """POSITION BUILD-UP vs VENUE BALANCES at the COB EOD boundary."""
    import avgcost_db as adb
    bnd = _dt0(date_iso) + timedelta(days=1)
    gr_date = bnd.strftime("%Y-%m-%d")
    print(f"\nPulling boundary balances for position recon (COB {date_iso}, "
          f"boundary {gr_date} 00:00 UTC)...")
    snp = snaps(bnd)
    try:
        snp.update(ntv_snaps(bnd))
    except Exception as e:
        print(f"  (native snaps skipped: {e})")
    mo_map = instrument_mo_map()
    try:
        rh_bal, rh_block = rh_goldrush_balances(gr_date)
        rh_src = f"GoldRush robinhood-mainnet blk {rh_block}"
    except Exception as e:
        rh_bal, rh_src = None, f"GoldRush FAILED ({e})"
    try:
        eth_bal, eth_block = eth_goldrush_balance(gr_date)
        eth_src = f"GoldRush eth-mainnet blk {eth_block} (ETH+WETH)"
    except Exception as e:
        eth_bal, eth_src = None, f"GoldRush FAILED ({e})"
    # cumulative Robinhood funding transfers (one-way txs) up to the boundary;
    # None (not zeros) when the walk fails so rows show XFERS? instead of a
    # misleading CHECK against an un-adjusted build-up
    rh_cum_xfer = defaultdict(lambda: ZERO)
    try:
        _, xfers = rh_events()
        for e in xfers:
            if e["time"] < to_ms(bnd):
                for s, v in e["deltas"].items():
                    rh_cum_xfer[s] += v
    except Exception as e:
        rh_cum_xfer = None
        print(f"  (robinhood transfer history FAILED: {e})")

    snapped_accts = {a for (a, _i) in snp}   # accounts with rows at this boundary
    conn = adb.connect()
    rows = []
    try:
        for inst, acct, prod, quote in adb.distinct_instruments(conn):
            q, _avg = adb.pos_at(conn, inst, bnd)
            pos = D(str(q))
            base = inst.split("/")[0]
            xfer, tol = None, D("0.000001")

            def _snap(a, key, what):
                """Snapshot balance; a MISSING row while the account is snapped
                at this boundary means the venue position/balance is ZERO (the
                streamer only writes live rows) — that difference is exactly
                what this recon must surface, so never report it as NO SNAP."""
                v = snp.get((a, key), (None,))[0]
                if v is None:
                    return (ZERO if a in snapped_accts else None), what
                return D(str(v)), what

            if "@BINANCE_USDT_FUTURE" in inst:
                bal, src = _snap(BIN_FUT, inst, "tq_hist_balance (perp position snap)")
            elif "@BINANCE_SPOT" in inst:
                bal, src = _snap(BIN_SPOT, base, "tq_hist_balance (spot wallet snap)")
            elif "@HYPERLIQUID_SPOT" in inst:
                bal, src = _snap(HL_SPOT, base, "tq_hist_balance (spot wallet snap)")
            elif "@HYPERLIQUID_FUTURES" in inst:
                bal, src = _snap(HL_FUT, inst, "tq_hist_balance (perp position snap)")
            elif "@NATIVECORE" in inst:
                bal, src = _snap(NTV_ACCT, base.upper(), "tq_hist_position_mo (MO DB snap)")
                tol = D("0.001")            # MO snapshots round harder
            elif "@ROBINHOOD" in inst:
                bal = None if rh_bal is None else rh_bal.get(base, ZERO)
                src = rh_src
                xfer = None if rh_cum_xfer is None else rh_cum_xfer.get(base, ZERO)
                if rh_cum_xfer is None and bal is not None:
                    # transfer stream down: can't form expected — flag, don't judge
                    rows.append([venue_of(acct), acct, to_mo(inst, mo_map)[:34],
                                 _fq(pos), "?", "?", _fq(bal), "—", "XFERS?", src])
                    continue
            elif "@ETHEREUM_RFQ" in inst:
                bal = eth_bal
                src = eth_src
                tol = D("0.10")             # withdraw fee + gas top-ups/burns
            elif "@BITSTAMP" in inst:
                bal = None
                src = "none — no tq_hist_balance snapshots yet"
            else:
                bal = None
                src = "?"
            if abs(pos) < D("1e-9") and (bal is None or abs(bal) < D("1e-9")) \
                    and xfer in (None, ZERO):
                continue                    # flat leg, flat venue — no row
            expected = pos + (xfer or ZERO)
            diff = None if bal is None else bal - expected
            if diff is None:
                status = "NO SNAP"
            elif abs(diff) <= tol:
                status = "OK"
            else:
                status = "CHECK"
            ven = "ETHEREUM" if "@ETHEREUM_RFQ" in inst else venue_of(acct)
            rows.append([ven, acct, to_mo(inst, mo_map)[:34],
                         _fq(pos), "—" if xfer is None else _fq(xfer), _fq(expected),
                         "—" if bal is None else _fq(bal),
                         "—" if diff is None else _fq(diff), status, src])
    finally:
        conn.close()
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    cols = ["venue", "account", "instrument", "build-up qty", "xfers (cum)",
            "expected", "venue balance", "diff", "status", "balance source"]
    info = [f"  build-up = engine position from EVERY stored fill (trades_spot_avgcost) at {gr_date} 00:00 UTC",
            "  expected = build-up + cumulative funding transfers (Robinhood only — inventory arrives by one-way chain transfer)",
            "  ETH RFQ leg: small diff = Binance withdrawal fee + gas top-ups − gas burns (tol 0.10 ETH)",
            "  flat legs with no snapshot row are hidden; NO SNAP = no balance source wired (Bitstamp)"]
    _render(f"POSITION BUILD-UP vs VENUE BALANCES — COB {date_iso} EOD", info, rows, cols=cols)


def _fq(v):
    return f"{float(v):,.4f}"


if __name__ == "__main__":
    import argparse
    INCEPTION = "2026-06-12"
    ap = argparse.ArgumentParser(description="8041 full-account recon (daily or MTD-aggregated)")
    ap.add_argument("date", nargs="?", default="2026-06-15", help="COB day YYYY-MM-DD")
    ap.add_argument("--date", dest="date_opt", help="COB day (alt to positional)")
    ap.add_argument("--inception", help="MTD start YYYY-MM-DD (enables MTD mode)")
    ap.add_argument("--mtd", action="store_true",
                    help=f"MTD-aggregate from inception ({INCEPTION}) to COB")
    ap.add_argument("--positions-only", action="store_true",
                    help="skip the flow recon; print only the position build-up "
                         "vs balances table")
    a = ap.parse_args()
    cob = a.date_opt or a.date
    inception = a.inception or (INCEPTION if a.mtd else None)
    if inception:
        run_recon_mtd(cob, inception)
    elif a.positions_only:
        run_position_recon(cob)
    else:
        run_recon(cob)
        try:
            run_position_recon(cob)
        except Exception as e:
            print(f"\n(position recon skipped: {e})")
