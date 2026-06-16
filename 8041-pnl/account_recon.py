"""Full-account recon for 810 (Binance) + TRADING_06 (Hyperliquid).

Reconciles EVERY moved instrument balance over a COB day:
    balance Δ = trade/cash Δ + unrealized Δ + transfers   (diff ≈ 0)

- POSITION legs (perp contracts / spot tokens): trade Δ = net traded qty.
- CASH legs (USDT / USDC pools): cash = realized+funding-fees from that
  pool's fills; unrealized Δ from tq_hist_position; transfers from the ledger.

HL has THREE USDC pools (spot / main-perp / xyz-dex); fills route by coin:
  @<n>  -> spot ;  xyz:*  -> xyz-dex ;  other perp (e.g. HYPE) -> main-perp.
Window is bounded by the actual snap record_ts (not nominal 00:00).
"""
from __future__ import annotations

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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pg import PG_HOST, PG_PORT, PG_USER, PG_PASS, PG_DB  # noqa: E402

ENV = Path(__file__).resolve().parent / ".env"
BUF = 60
ZERO = D(0)
BIN_FUT = "TK810@BINANCE_USDT_FUTURE"
HL_SPOT = "TRADING_06@HYPERLIQUID_SPOT"
HL_FUT = "TRADING_06@HYPERLIQUID_FUTURES"
SPOT_COIN = {"SPCXD": "@465", "HYPE": "@107"}   # HL spot token -> pair coin


def env(key):
    for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return ""


def to_ms(dt):
    return int((dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp() * 1000)


def _pg():
    import psycopg2
    return psycopg2.connect(host=PG_HOST, port=PG_PORT, user=PG_USER, password=PG_PASS,
                            database=PG_DB, connect_timeout=15)


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
            WHERE (account_name LIKE 'TK810@%%' OR account_name LIKE 'TRADING_06@%%')
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
    p = dict(params); p["timestamp"] = int(time.time() * 1000); p["recvWindow"] = 60000
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
    return sum((D(f["qty"]) * (D(1) if f["buyer"] else D(-1))
                for f in fills if w0 <= int(f["time"]) < w1), ZERO)


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
    cash, transfer = ZERO, ZERO
    for r in rows:
        if not (w0 <= int(r["time"]) < w1):
            continue
        amt = D(str(r["income"]))
        if "TRANSFER" in str(r.get("incomeType", "")).upper():
            transfer += amt
        else:
            cash += amt
    return cash, transfer


# ── hyperliquid ──
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
                 "endTime": 1782200000000, "aggregateByTime": False})
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
                "startTime": 1778000000000, "endTime": 1782200000000})


def pool_of(coin):
    if coin.startswith("@"):
        return "spot"
    if coin.startswith("xyz:"):
        return "xyz"
    return "main"


def hl_perp_pnl(date_iso):
    """Per-leg PnL for HL futures (HYPE + xyz:*): realized + ΔUnreal + funding − fees.

    Uses HL's own realized (closedPnl) and venue unsettled_pnl (tq_hist_position)
    — no mark needed. Returns list of dicts. Net-flat legs (e.g. HYPE) have ΔUnreal 0.
    """
    sod_dt = datetime.strptime(date_iso, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    eod_dt = sod_dt + timedelta(days=1)
    sod, eod = snaps(sod_dt), snaps(eod_dt)
    anyk = next(iter(sod))
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


def run_recon(date_iso):
    sod_dt = datetime.strptime(date_iso, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    eod_dt = sod_dt + timedelta(days=1)
    print(f"Pulling snaps + venue data for full-account recon ({date_iso})...")
    sod, eod = snaps(sod_dt), snaps(eod_dt)
    anyk = next(iter(sod))
    w0, w1 = to_ms(sod[anyk][1]), to_ms(eod[anyk][1])

    # HL aggregates per coin
    fills = hl_fills()
    net_qty, realized, usdc_fee, inkind = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO), defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    spot_usdc = defaultdict(lambda: ZERO)
    for f in fills:
        if not (w0 <= int(f["time"]) < w1):
            continue
        c = f["coin"]
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
    for r in hl_funding():
        if w0 <= int(r["time"]) < w1:
            d = r["delta"]
            fund_by_pool[pool_of(d["coin"])] += D(str(d["usdc"]))
    # realized/fees aggregated to pool
    real_pool, fee_pool = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    for c in set(realized) | set(usdc_fee):
        real_pool[pool_of(c)] += realized[c]
        fee_pool[pool_of(c)] += usdc_fee[c]
    # transfers by (asset, pool) from ledger
    addr = env("TRADING_06@HYPERLIQUID").lower()
    POOL = {"spot": "spot", "": "main", "perp": "main", "xyz": "xyz"}
    tx = defaultdict(lambda: ZERO)   # (asset, pool) -> signed
    for u in hl_ledger():
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

    # ── build rows ──
    rows = []
    keys = sorted(set(sod) | set(eod))
    for k in keys:
        acct, inst = k
        bal_d = eod.get(k, (ZERO, None))[0] - sod.get(k, (ZERO, None))[0]
        if abs(bal_d) < D("1e-6"):
            continue
        unreal, transfers, td = None, ZERO, None
        label = inst[:34]
        if acct == BIN_FUT and inst == "USDT":
            td, transfers = bin_income(w0, w1)
            unreal = unrealized_sum(BIN_FUT, "%SPCX%", eod_dt) - unrealized_sum(BIN_FUT, "%SPCX%", sod_dt)
        elif acct == BIN_FUT:  # SPCX perp position
            td = bin_pos_net("SPCXUSDT", w0, w1)
        elif acct == HL_SPOT and inst == "USDC":
            td = sum(spot_usdc.values(), ZERO) - sum(v for c, v in usdc_fee.items() if c.startswith("@"))
            transfers = tx.get(("USDC", "spot"), ZERO)
        elif acct == HL_SPOT:  # spot token (SPCXD/HYPE)
            coin = SPOT_COIN.get(inst, inst)
            td = net_qty.get(coin, ZERO)
            transfers = tx.get((inst.upper(), "spot"), ZERO)
        elif acct == HL_FUT and inst in ("USDC", "xyz:USDC"):
            pool = "xyz" if inst == "xyz:USDC" else "main"
            td = real_pool[pool] + fund_by_pool[pool] - fee_pool[pool]
            ilk = "xyz:%-P%" if pool == "xyz" else "HYPE"
            unreal = unrealized_sum(HL_FUT, ilk, eod_dt) - unrealized_sum(HL_FUT, ilk, sod_dt)
            transfers = tx.get(("USDC", pool), ZERO)
        elif acct == HL_FUT:  # xyz perp position
            base = inst.split("-P/")[0]    # 'xyz:CRCL'
            td = net_qty.get(base, ZERO)
        accounted = td + (unreal or ZERO) + transfers
        diff = bal_d - accounted
        status = "OK" if abs(diff) < D("0.05") else "CHECK"
        short_acct = acct.replace("@BINANCE_USDT_FUTURE", "·BIN-FUT").replace(
            "@HYPERLIQUID_SPOT", "·HL-SPOT").replace("@HYPERLIQUID_FUTURES", "·HL-FUT")
        s_bal = sod.get(k, (ZERO,))[0]
        e_bal = eod.get(k, (ZERO,))[0]
        rows.append([short_acct.split("·")[1], label,
                     f"{float(s_bal):,.4f}", f"{float(e_bal):,.4f}",
                     f"{float(bal_d):,.4f}", f"{float(td):,.4f}",
                     ("—" if unreal is None else f"{float(unreal):,.2f}"),
                     f"{float(transfers):,.2f}", f"{float(diff):,.4f}", status])

    cols = ["acct", "instrument", "SOD bal", "EOD bal", "balance Δ", "trade/cash Δ",
            "unreal", "transfers", "diff", "status"]
    w = [max(len(cols[i]), *(len(r[i]) for r in rows)) for i in range(len(cols))]

    def bar(a, b, c):
        return a + b.join("─" * (w[i] + 2) for i in range(len(w))) + c

    def line(cs, center=False):
        return "│" + "│".join(" " + (cs[i].center(w[i]) if center else
               (cs[i].ljust(w[i]) if i in (0, 1, 9) else cs[i].rjust(w[i]))) + " "
               for i in range(len(cs))) + "│"

    print(f"\nFULL-ACCOUNT RECON — COB {date_iso}  (snaps {sod[anyk][1]} → {eod[anyk][1]})")
    print(bar("┌", "┬", "┐"))
    print(line(cols, True))
    print(bar("├", "┼", "┤"))
    for r in rows:
        print(line(r))
    print(bar("└", "┴", "┘"))
    print("identity: balance Δ = trade/cash Δ + unreal Δ + transfers.  "
          "HYPE perp/spot net 0 (no balance move).")


if __name__ == "__main__":
    run_recon(sys.argv[1] if len(sys.argv) > 1 else "2026-06-15")
