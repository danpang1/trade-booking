"""Portfolio 8041 (Central Risk Book) — DAILY PnL + full-account recon.

  python pnl_8041_daily.py --date 2026-06-15 --mark 199.82

Produces, for the COB --date:
  1. FULL PnL (ALL trades) — every instrument on Binance 810 + HL TRADING_06
     (both map to portfolio 8041): SPCX delta-neutral pair via avg-cost engine
     + every HL futures leg (HYPE, xyz:*) via realized/unrealized/funding/fees.
  2. FULL-ACCOUNT RECON — balance Δ = trade/cash Δ + unrealized + transfers.

Avg-cost replay runs from book inception; only the --date COB is reported.
EOD mark for --date is pinned via --mark (or PINNED_MARKS / the 24/7 feed).
"""
from __future__ import annotations
import argparse, hashlib, hmac, json, sys, time, urllib.parse, urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
from engine import Position, apply_fill, unrealized, D, ZERO  # noqa: E402

CH = ("https://jp-clickhouse-api.internal.tokkalabs.com:443/"
      "?user=prod_ro&password=scCtp%21Ez8%233h%23LK8")

INCEPTION = "2026-06-12"   # SPCX book start (avg-cost replay anchor)
PINNED_MARKS = {"2026-06-14": "168.01", "2026-06-15": "199.82"}   # user-pinned EOD marks

_ap = argparse.ArgumentParser(description="Portfolio 8041 daily PnL + recon")
_ap.add_argument("--date", default="2026-06-15", help="COB day YYYY-MM-DD")
_ap.add_argument("--mark", default=None, help="EOD mark for --date (overrides pinned/feed)")
_args, _ = _ap.parse_known_args()
COB = _args.date


def _drange(a, b):
    da, db = datetime.strptime(a, "%Y-%m-%d"), datetime.strptime(b, "%Y-%m-%d")
    out, d = [], da
    while d <= db:
        out.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return out


DAYS = _drange(INCEPTION, COB)
MARK_CUTOFFS = [(datetime.strptime(INCEPTION, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")] + DAYS


def day_of(ms): return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")
def ms_at(y, mo, d, h, mi): return int(datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp() * 1000)


def env(key):
    for line in (REPO / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return None


# ── Binance SPCX perp fills (papi userTrades) ──────────────────────────
def binance_spcx_events():
    key, secret = env("810.BINANCE_API_KEY"), env("810.BINANCE_API_SECRET")
    H = {"X-MBX-APIKEY": key}

    def sget(path, params):
        p = dict(params); p["timestamp"] = int(time.time() * 1000); p["recvWindow"] = 60000
        qs = urllib.parse.urlencode(p)
        sig = hmac.new(secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
        r = urllib.request.urlopen(urllib.request.Request(
            f"https://papi.binance.com{path}?{qs}&signature={sig}", headers=H), timeout=20)
        return json.loads(r.read())

    fills, seen = [], set()
    seed = sget("/papi/v1/um/userTrades", {"symbol": "SPCXUSDT", "limit": 1000, "startTime": 1781000000000})
    from_id = min(int(f["id"]) for f in seed) if seed else 0
    while True:
        batch = sget("/papi/v1/um/userTrades", {"symbol": "SPCXUSDT", "limit": 1000, "fromId": from_id})
        if not batch:
            break
        new = [f for f in batch if int(f["id"]) not in seen]
        for f in new:
            seen.add(int(f["id"]))
        fills += new
        if len(batch) < 1000:
            break
        from_id = max(int(f["id"]) for f in batch) + 1
    ev = []
    for f in fills:
        qty = D(f["qty"]) * (D(1) if f["buyer"] else D(-1))
        ev.append((int(f["time"]), qty, D(f["price"]), D(f["commission"])))  # fee in USDT
    return ev


def binance_funding_by_day():
    """Signed FUNDING_FEE income per day (+ received). On the perp leg only."""
    key, secret = env("810.BINANCE_API_KEY"), env("810.BINANCE_API_SECRET")
    H = {"X-MBX-APIKEY": key}

    def sget(params):
        p = dict(params); p["timestamp"] = int(time.time() * 1000); p["recvWindow"] = 60000
        qs = urllib.parse.urlencode(p)
        sig = hmac.new(secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
        r = urllib.request.urlopen(urllib.request.Request(
            "https://papi.binance.com/papi/v1/um/income?" + qs + "&signature=" + sig,
            headers=H), timeout=20)
        return json.loads(r.read())

    rows, cursor = [], 1781000000000
    while True:
        batch = sget({"incomeType": "FUNDING_FEE", "symbol": "SPCXUSDT",
                      "startTime": cursor, "limit": 1000})
        if not batch:
            break
        rows += batch
        if len(batch) < 1000:
            break
        cursor = max(int(r["time"]) for r in batch) + 1
    by_day = {}
    for r in rows:
        d = day_of(int(r["time"]))
        by_day[d] = by_day.get(d, ZERO) + D(str(r["income"]))
    return by_day


# ── Hyperliquid SPCXD spot fills + mints ───────────────────────────────
def hl_spcxd_events():
    addr = env("TRADING_06@HYPERLIQUID")

    def info(b):
        r = urllib.request.urlopen(urllib.request.Request(
            "https://api.hyperliquid.xyz/info", data=json.dumps(b).encode(),
            headers={"Content-Type": "application/json"}), timeout=30)
        return json.loads(r.read())

    fills, seen, start = [], set(), 1778000000000
    while True:
        batch = info({"type": "userFillsByTime", "user": addr,
                      "startTime": start, "endTime": 1782200000000, "aggregateByTime": False})
        if not batch:
            break
        fresh = [f for f in batch if f["tid"] not in seen]
        for f in fresh:
            seen.add(f["tid"])
        fills += [f for f in fresh if f["coin"] == "@465"]
        bmax = max(int(f["time"]) for f in batch)
        if len(batch) < 2000 or bmax <= start:
            break
        start = bmax + 1
    ev = []
    for f in fills:
        qty = D(f["sz"]) * (D(1) if f["side"] == "B" else D(-1))
        fee = D(f["fee"]) * (D(f["px"]) if f["feeToken"] == "SPCXD" else D(1))  # -> USD
        ev.append((int(f["time"]), qty, D(f["px"]), fee))
    # mints (user cost basis) as opening adds, zero fee
    ev.append((ms_at(2026, 6, 12, 14, 4), D("299.9"), D("162.575"), ZERO))
    ev.append((ms_at(2026, 6, 12, 19, 23), D("299.93899"), D("166.70057"), ZERO))
    return ev


# ── EOD marks from ClickHouse ──────────────────────────────────────────
def ch_marks(codename):
    exprs = [f"toString(argMaxIf(price, ts_edge_first_seen, ts_edge_first_seen <= "
             f"toUnixTimestamp(toDateTime('{c} 23:59:59'))*1000000)) AS m{i}"
             for i, c in enumerate(MARK_CUTOFFS)]
    sql = (f"SELECT {', '.join(exprs)} FROM production.trade "
           f"WHERE codename='{codename}' "
           f"AND ts_edge_first_seen <= toUnixTimestamp(toDateTime('2026-06-14 23:59:59'))*1000000\n"
           f"FORMAT TabSeparated")
    r = urllib.request.urlopen(urllib.request.Request(CH, data=sql.encode(),
        headers={"Content-Type": "text/plain"}), timeout=60)
    vals = r.read().decode().strip().split("\t")
    return {c: (D(v) if v not in ("", "\\N") else None) for c, v in zip(MARK_CUTOFFS, vals)}


# ── daily avg-cost walk for one leg ────────────────────────────────────
def walk(events, marks, label):
    events = sorted(events, key=lambda e: e[0])
    pos = Position()
    out = {}
    sod_mark = {"2026-06-12": "2026-06-11", "2026-06-13": "2026-06-12",
                "2026-06-14": "2026-06-13", "2026-06-15": "2026-06-14"}
    for day in DAYS:
        sod = Position(pos.qty, pos.avg_cost)
        realized = ZERO; fees = ZERO; n = 0
        for t, qty, px, fee in events:
            if day_of(t) == day:
                realized += apply_fill(pos, qty, px).realized
                fees += fee; n += 1
        sm = marks.get(sod_mark[day]); em = marks.get(day)
        su = unrealized(Position(sod.qty, sod.avg_cost), sm) if (sm and sod.qty != 0) else ZERO
        eu = unrealized(pos, em) if (em and pos.qty != 0) else ZERO
        du = eu - su
        total = realized + du - fees
        out[day] = dict(qty=pos.qty, avg=pos.avg_cost, mark=em, realized=realized,
                        du=du, fees=fees, total=total, n=n)
    return out


def f(x, dp=2): return "—" if x is None else f"{float(x):,.{dp}f}"


print("Pulling Binance SPCX userTrades, HL @465 fills, ClickHouse marks...")
bin_ev = binance_spcx_events()
hl_ev = hl_spcxd_events()
# Single unified mark across BOTH legs (strips perp<->spot basis noise).
# Jun-12/13 from the 24/7 hip-xyz spcx perp; Jun-14 user-specified 168.01.
marks = ch_marks("hip-xyz-perp_xyz:spcx-usdc")
for _d, _m in PINNED_MARKS.items():
    if _d in marks:
        marks[_d] = D(_m)
if _args.mark:
    marks[COB] = D(_args.mark)
fund = binance_funding_by_day()
print(f"Unified marks: " + " ".join(f"{d[5:]}={f(marks[d])}" for d in MARK_CUTOFFS[1:]))

legs = {
    "Binance SPCX perp (SHORT)": walk(bin_ev, marks, "bin"),
    "Hyperliquid SPCXD spot (LONG)": walk(hl_ev, marks, "hl"),
}

grand = ZERO
for day in DAYS:
    print(f"\n{'='*108}\nCOB {day} 23:59:59 UTC")
    print(f"{'leg':32} {'eod_qty':>11} {'avg_cost':>10} {'mark':>9} {'realized':>10} "
          f"{'dUnreal':>10} {'funding':>9} {'fees':>8} {'total':>10} {'trd':>4}")
    day_tot = ZERO
    for name, res in legs.items():
        r = res[day]
        fnd = fund.get(day, ZERO) if "Binance" in name else ZERO
        leg_total = r["total"] + fnd
        day_tot += leg_total
        print(f"{name:32} {f(r['qty'],3):>11} {f(r['avg']):>10} {f(r['mark']):>9} "
              f"{f(r['realized']):>10} {f(r['du']):>10} {f(fnd):>9} {f(r['fees']):>8} "
              f"{f(leg_total):>10} {r['n']:>4}")
    grand += day_tot
    print(f"  -> SPCX book net PnL {day} = {f(day_tot)} USD")

print(f"\n{'='*108}")
print(f"SPCX-PAIR PnL ({INCEPTION[5:]}..{COB[5:]} Jun) = {f(grand)} USD  (delta-neutral book)")

# ── FULL-ACCOUNT PnL (ALL trades) for the COB day, then the recon ───────
day = DAYS[-1]
sod_snap, eod_snap = {}, {}
try:
    import account_recon as ar
    _res = ar.hl_perp_pnl(day)
    perp_legs, sod_snap, eod_snap = _res["legs"], _res["sod"], _res["eod"]
except Exception as e:
    perp_legs = []
    print(f"\n(HL perp legs skipped: {e})")


def _snapbal(snap, account, inst):
    return snap.get((account, inst), (ZERO,))[0]


b = legs["Binance SPCX perp (SHORT)"][day]
bf = fund.get(day, ZERO)
h = legs["Hyperliquid SPCXD spot (LONG)"][day]
bin_inst = "SPCX-P/USDT@BINANCE_USDT_FUTURE"
# (acct, instrument, SOD bal, EOD bal, realized, ΔUnreal, funding, fees, net PnL)
pnl_rows = [
    ("BINANCE", bin_inst,
     _snapbal(sod_snap, "TK810@BINANCE_USDT_FUTURE", bin_inst),
     _snapbal(eod_snap, "TK810@BINANCE_USDT_FUTURE", bin_inst),
     b["realized"], b["du"], bf, b["fees"], b["realized"] + b["du"] + bf - b["fees"]),
    ("HL-SPOT", "SPCXD/USDC@HYPERLIQUID_SPOT",
     _snapbal(sod_snap, "TRADING_06@HYPERLIQUID_SPOT", "SPCXD"),
     _snapbal(eod_snap, "TRADING_06@HYPERLIQUID_SPOT", "SPCXD"),
     h["realized"], h["du"], ZERO, h["fees"], h["total"]),
]
for pl in perp_legs:
    pnl_rows.append(("HL-FUT", pl["coin"], pl["sod_bal"], pl["eod_bal"],
                     pl["realized"], pl["du"], pl["funding"], pl["fees"], pl["total"]))
pnl_total = sum((r[8] for r in pnl_rows), ZERO)

pcols = ["acct", "instrument", "SOD bal", "EOD bal", "realized", "ΔUnreal", "funding", "fees", "net PnL"]
pdata = [[r[0], r[1][:34], f(r[2], 4), f(r[3], 4), f(r[4]), f(r[5]), f(r[6]), f(r[7]), f(r[8])]
         for r in pnl_rows]
pdata.append(["TOTAL", "", "", "", "", "", "", "", f(pnl_total)])
pw = [max(len(pcols[i]), *(len(r[i]) for r in pdata)) for i in range(len(pcols))]


def _pbar(a, m, c):
    return a + m.join("─" * (pw[i] + 2) for i in range(len(pw))) + c


def _pline(cs, center=False):
    return "│" + "│".join(" " + (cs[i].center(pw[i]) if center else
           (cs[i].ljust(pw[i]) if i in (0, 1) else cs[i].rjust(pw[i]))) + " "
           for i in range(len(cs))) + "│"


print(f"\n{'='*108}\nPORTFOLIO 8041 — DAILY PnL (ALL TRADES) — COB {day} 23:59:59 UTC")
print(_pbar("┌", "┬", "┐"))
print(_pline(pcols, True))
print(_pbar("├", "┼", "┤"))
for r in pdata:
    print(_pline(r))
print(_pbar("└", "┴", "┘"))
print(f"ALL-TRADES NET PnL {day} = {f(pnl_total)} USD   "
      f"(SPCX book {f(b['realized']+b['du']+bf-b['fees']+h['total'])} + HL perps)")

try:
    ar.run_recon(day)
except Exception as e:
    print(f"\n(recon skipped: {e})")
