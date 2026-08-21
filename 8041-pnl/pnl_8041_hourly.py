"""Portfolio 8041 (Central Risk Book) — HOURLY PnL.

  python pnl_8041_hourly.py --date 2026-06-17

Same scope/methodology as pnl_8041_daily.py, but the COB --date is split into
24 hourly windows [HH:00, HH+1:00) UTC. For each hour and each leg:

    hour PnL = realized + ΔUnreal + funding − fees

Legs:
  - Binance SPCX perp (SHORT)  — avg-cost replay, hourly ΔUnreal at hourly marks.
  - Hyperliquid SPCXD spot (LONG) — avg-cost replay (incl. Dinari cost-basis adds).
  - Hyperliquid perp legs (HYPE, xyz:*) — realized (closedPnl) + funding − fees,
    ΔUnreal from hourly tq_hist_position.unsettled_pnl snapshots.

Marks: hourly SPCX mark from **Binance** fapi /fapi/v1/markPriceKlines (interval
1h, public). A single unified mark is applied to BOTH SPCX legs so the
delta-neutral book stays basis-independent. NO ClickHouse. Fallback mark source
is the Postgres tq_hist_position.index_price hourly snap (still Binance's index).

Outputs an hourly CSV (8041_pnl_cob<DD>_hourly.csv) + console tables, and a
daily roll-up tie-out so the hourly sums reconcile to the daily run.
"""
from __future__ import annotations
import argparse
import hashlib
import hmac
import json
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
from engine import Position, apply_fill, unrealized, D, ZERO        # noqa: E402
import account_recon as ar                                          # noqa: E402

INCEPTION = "2026-06-12"     # SPCX book start (avg-cost replay anchor)
BIN_FUT = "TK810@BINANCE_USDT_FUTURE"
HLS_ACCT = "TRADING_06@HYPERLIQUID_SPOT"
HLF_ACCT = "TRADING_06@HYPERLIQUID_FUTURES"

_ap = argparse.ArgumentParser(description="Portfolio 8041 HOURLY PnL")
_ap.add_argument("--date", default="2026-06-17", help="COB day YYYY-MM-DD")
_ap.add_argument("--symbol", default="SPCXUSDT", help="Binance UM perp symbol for marks")
_ap.add_argument("--mark-source", default="binance", choices=["binance", "pg"],
                 help="hourly mark source (binance markPriceKlines | pg index_price snap)")
_args, _ = _ap.parse_known_args()
COB = _args.date


# ── time helpers ───────────────────────────────────────────────────────
def day_of(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def ms_at(y, mo, d, h, mi):
    return int(datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp() * 1000)


def hour_bounds(cob):
    """25 hour-boundary ms timestamps: 00:00, 01:00, ... 24:00 of the COB day."""
    d0 = datetime.strptime(cob, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return [int((d0 + timedelta(hours=h)).timestamp() * 1000) for h in range(25)]


def _dt(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc)


def _dtn(ms):
    """Naive UTC datetime — for comparing against Postgres record_ts (tz-naive)."""
    return datetime.utcfromtimestamp(ms / 1000)


def f(x, dp=2):
    return "—" if x is None else f"{float(x):,.{dp}f}"


# ── prod MO golden-record creds (Dinari cost-basis) ────────────────────
def _prod_mo_creds():
    envp = REPO.parent.parent / "nxgenmo" / ".env"
    creds, in_block = {}, False
    for ln in envp.read_text(encoding="utf-8", errors="replace").splitlines():
        s, st = ln.rstrip(), ln.strip()
        if st.startswith("#") and "PROD MO DB RO" in st.upper():
            in_block = True
            continue
        if not in_block:
            continue
        if st.startswith("#"):
            break
        if not st:
            continue
        idxs = [i for i in (s.find(":"), s.find("=")) if i >= 0]
        if not idxs:
            continue
        i = min(idxs)
        creds[s[:i].strip().upper()] = s[i + 1:].strip().strip('"').strip("'")
    return creds


_DINARI_TIME_OVERRIDE = {"MFX00000108": (2026, 6, 12, 14, 4),
                         "MFX00000109": (2026, 6, 12, 19, 23)}


def dinari_spcx_buys(cob_iso):
    """Live Dinari SPCX buys (CENTRAL RISK BOOK) up to COB as long-leg cost-basis
    adds: (time_ms, qty, price, fee=0, 'manual'). Bridged SPCX lands on HL as a
    deposit (not a fill), so it is priced here from the prod MO golden record."""
    import psycopg2
    c = _prod_mo_creds()
    conn = psycopg2.connect(host=c["MO_DB_HOST"], port=int(c.get("MO_DB_PORT", "5432")),
                            dbname=c["MO_DB_DATABASE"], user=c["MO_DB_USERNAME"],
                            password=c["MO_DB_PASSWORD"], connect_timeout=15)
    try:
        cur = conn.cursor()
        cur.execute("SET TIMEZONE = 'UTC'")
        cur.execute("""
            SELECT deal_ref, base_amount, price, trade_date
            FROM trades_spot
            WHERE base_asset = 'SPCX' AND counterparty = 'DINARI'
              AND effective_end IS NULL
              AND portfolio_name LIKE '%%CENTRAL RISK BOOK%%'
              AND trade_date < (%s::date + INTERVAL '1 day')
            ORDER BY trade_date, deal_ref
        """, (cob_iso,))
        rows = cur.fetchall()
    finally:
        conn.close()
    ev = []
    for dref, qty, px, td in rows:
        t = ms_at(*_DINARI_TIME_OVERRIDE[dref]) if dref in _DINARI_TIME_OVERRIDE \
            else int(td.timestamp() * 1000)
        ev.append((t, D(str(qty)), D(str(px)), ZERO, "manual"))
    return ev


# ── Binance SPCX perp fills + funding (papi) ───────────────────────────
def _papi(path, params):
    key, secret = ar.env("810.BINANCE_API_KEY"), ar.env("810.BINANCE_API_SECRET")
    p = dict(params)
    p["timestamp"] = int(time.time() * 1000)
    p["recvWindow"] = 60000
    qs = urllib.parse.urlencode(p)
    sig = hmac.new(secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
    r = urllib.request.urlopen(urllib.request.Request(
        "https://papi.binance.com" + path + "?" + qs + "&signature=" + sig,
        headers={"X-MBX-APIKEY": key}), timeout=20)
    return json.loads(r.read())


def binance_spcx_events():
    """All SPCX perp fills as (time_ms, signed_qty, price, fee_usdt, 'api')."""
    fills, seen = [], set()
    seed = _papi("/papi/v1/um/userTrades",
                 {"symbol": "SPCXUSDT", "limit": 1000, "startTime": 1781000000000})
    from_id = min(int(x["id"]) for x in seed) if seed else 0
    while True:
        batch = _papi("/papi/v1/um/userTrades",
                      {"symbol": "SPCXUSDT", "limit": 1000, "fromId": from_id})
        if not batch:
            break
        new = [x for x in batch if int(x["id"]) not in seen]
        for x in new:
            seen.add(int(x["id"]))
        fills += new
        if len(batch) < 1000:
            break
        from_id = max(int(x["id"]) for x in batch) + 1
    ev = []
    for x in fills:
        qty = D(x["qty"]) * (D(1) if x["buyer"] else D(-1))
        ev.append((int(x["time"]), qty, D(x["price"]), D(x["commission"]), "api"))
    return ev


def binance_funding_events():
    """Signed FUNDING_FEE income on the SPCX perp as (time_ms, income)."""
    rows, cursor = [], 1781000000000
    while True:
        batch = _papi("/papi/v1/um/income",
                      {"incomeType": "FUNDING_FEE", "symbol": "SPCXUSDT",
                       "startTime": cursor, "limit": 1000})
        if not batch:
            break
        rows += batch
        if len(batch) < 1000:
            break
        cursor = max(int(r["time"]) for r in batch) + 1
    return [(int(r["time"]), D(str(r["income"]))) for r in rows]


# ── Hyperliquid SPCXD spot fills + Dinari adds ─────────────────────────
def hl_spcxd_events():
    """HL SPCXD (@465) spot fills + Dinari cost-basis adds, as avg-cost events."""
    fills = [fI for fI in ar.hl_fills() if fI["coin"] == "@465"]
    ev = []
    for x in fills:
        qty = D(x["sz"]) * (D(1) if x["side"] == "B" else D(-1))
        fee = D(x["fee"]) * (D(x["px"]) if x["feeToken"] == "SPCXD" else D(1))   # -> USD
        ev.append((int(x["time"]), qty, D(x["px"]), fee, "api"))
    ev += dinari_spcx_buys(COB)
    return ev


# ── hourly marks ───────────────────────────────────────────────────────
def binance_mark_klines(symbol, bnds):
    """{boundary_ms -> mark} from Binance fapi markPriceKlines (1h). The kline
    whose openTime == a boundary supplies the mark AT that boundary (open price);
    the 24:00 boundary uses the next-day 00:00 kline, else the last close."""
    url = ("https://fapi.binance.com/fapi/v1/markPriceKlines?"
           + urllib.parse.urlencode({"symbol": symbol, "interval": "1h",
                                     "startTime": bnds[0], "endTime": bnds[24], "limit": 30}))
    data = json.loads(urllib.request.urlopen(url, timeout=20).read())
    out, last_close = {}, None
    for k in data:
        out[int(k[0])] = D(str(k[1]))     # open at openTime
        last_close = D(str(k[4]))
    if bnds[24] not in out and last_close is not None:
        out[bnds[24]] = last_close
    return out


def pg_index_marks(bnds):
    """Fallback: {boundary_ms -> mark} from tq_hist_position.index_price, picking
    the first SPCX snap in [boundary, boundary+20min) at each hour boundary."""
    pg = ar._pg()
    out = {}
    try:
        cur = pg.cursor()
        cur.execute("""
            SELECT instrument, record_ts, index_price
            FROM tq_hist_position
            WHERE account_name = %s AND instrument ILIKE %s
              AND record_ts >= %s AND record_ts < %s
            ORDER BY record_ts
        """, (BIN_FUT, "%SPCX%", _dt(bnds[0]), _dt(bnds[24]) + timedelta(minutes=30)))
        snaps = [(ts, ip) for _, ts, ip in cur.fetchall() if ip is not None]
    finally:
        pg.close()
    for b in bnds:
        lo, hi = _dtn(b), _dtn(b) + timedelta(minutes=20)
        hit = next((ip for ts, ip in snaps if lo <= ts < hi), None)
        if hit is not None:
            out[b] = D(str(hit))
    return out


# ── hourly avg-cost walk for one SPCX leg ──────────────────────────────
def walk_hourly(events, mark_at, bnds):
    """Return per-hour dicts for an avg-cost leg over the COB day."""
    events = sorted(events, key=lambda e: e[0])
    pos = Position()
    i, n = 0, len(events)
    while i < n and events[i][0] < bnds[0]:           # replay everything before COB
        apply_fill(pos, events[i][1], events[i][2])
        i += 1
    rows = []
    for h in range(24):
        lo, hi = bnds[h], bnds[h + 1]
        sod = Position(pos.qty, pos.avg_cost)
        realized, fees, cnt, n_api, n_man = ZERO, ZERO, 0, 0, 0
        while i < n and events[i][0] < hi:
            _t, qty, px, fee, src = events[i]
            realized += apply_fill(pos, qty, px).realized
            fees += fee
            cnt += 1
            n_man += 1 if src == "manual" else 0
            n_api += 0 if src == "manual" else 1
            i += 1
        sm, em = mark_at.get(lo), mark_at.get(hi)
        su = unrealized(Position(sod.qty, sod.avg_cost), sm) if (sm and sod.qty != 0) else ZERO
        eu = unrealized(pos, em) if (em and pos.qty != 0) else ZERO
        du = eu - su
        rows.append(dict(h=h, sod_qty=sod.qty, qty=pos.qty, avg=pos.avg_cost, mark=em,
                         realized=realized, du=du, fees=fees,
                         total=realized + du - fees, n=cnt, n_api=n_api, n_man=n_man))
    return rows


# ── hourly HL perp legs ────────────────────────────────────────────────
def _coin_of_inst(inst):
    return inst.split("-P")[0]      # 'HYPE-P/USD@..'->'HYPE' ; 'xyz:CRCL-P/..'->'xyz:CRCL'


def hl_fut_unreal_boundaries(coins, bnds):
    """{coin -> {boundary_ms -> Σ unsettled_pnl}} from hourly HL_FUT position snaps."""
    pg = ar._pg()
    try:
        cur = pg.cursor()
        cur.execute("""
            SELECT instrument, record_ts, unsettled_pnl
            FROM tq_hist_position
            WHERE account_name = %s
              AND record_ts >= %s AND record_ts < %s
        """, (HLF_ACCT, _dt(bnds[0]), _dt(bnds[24]) + timedelta(minutes=30)))
        raw = cur.fetchall()
    finally:
        pg.close()
    # snaps[coin] = list of (ts, instrument, u)
    by_coin = defaultdict(list)
    for inst, ts, u in raw:
        if u is None:
            continue
        by_coin[_coin_of_inst(inst)].append((ts, inst, D(str(u))))
    out = {}
    for c in coins:
        out[c] = {}
        rows = sorted(by_coin.get(c, []))
        for b in bnds:
            lo, hi = _dtn(b), _dtn(b) + timedelta(minutes=20)
            # first snap per instrument in window, summed across instruments of this coin
            picked, seen_inst = ZERO, set()
            for ts, inst, u in rows:
                if lo <= ts < hi and inst not in seen_inst:
                    seen_inst.add(inst)
                    picked += u
            out[c][b] = picked if seen_inst else None
    return out


def hl_perp_hourly(bnds):
    """Per-coin hourly dicts for HL futures legs over the COB day."""
    fills = ar.hl_fills()
    funding = ar.hl_funding()
    cob_fills = [x for x in fills if bnds[0] <= int(x["time"]) < bnds[24]
                 and not x["coin"].startswith("@")]
    coins = sorted({x["coin"] for x in cob_fills})
    unreal = hl_fut_unreal_boundaries(coins, bnds)
    legs = {}
    for c in coins:
        hours = []
        for h in range(24):
            lo, hi = bnds[h], bnds[h + 1]
            realized, fees, cnt = ZERO, ZERO, 0
            for x in cob_fills:
                if x["coin"] == c and lo <= int(x["time"]) < hi:
                    realized += D(x.get("closedPnl", "0"))
                    cnt += 1
                    if x["feeToken"] == "USDC":
                        fees += D(x["fee"])
            fund = ZERO
            for r in funding:
                if r["delta"]["coin"] == c and lo <= int(r["time"]) < hi:
                    fund += D(str(r["delta"]["usdc"]))
            us, ue = unreal[c].get(lo), unreal[c].get(hi)
            du = (ue - us) if (us is not None and ue is not None) else ZERO
            hours.append(dict(h=h, realized=realized, du=du, funding=fund, fees=fees,
                              total=realized + du + fund - fees, n=cnt))
        legs[c] = hours
    return legs


# ── table renderer (house box-drawing style) ───────────────────────────
def render(title, cols, data, left_idx):
    w = [max(len(cols[i]), *(len(r[i]) for r in data)) if data else len(cols[i])
         for i in range(len(cols))]

    def bar(a, m, c):
        return a + m.join("─" * (w[i] + 2) for i in range(len(w))) + c

    def line(cs, center=False):
        return "│" + "│".join(
            " " + (cs[i].center(w[i]) if center else
                   (cs[i].ljust(w[i]) if i in left_idx else cs[i].rjust(w[i]))) + " "
            for i in range(len(cs))) + "│"

    print("\n" + title)
    print(bar("┌", "┬", "┐"))
    print(line(cols, True))
    print(bar("├", "┼", "┤"))
    for r in data:
        print(line(r))
    print(bar("└", "┴", "┘"))


# ── main ───────────────────────────────────────────────────────────────
def main():
    bnds = hour_bounds(COB)
    print(f"Portfolio 8041 HOURLY PnL — COB {COB} (00:00–24:00 UTC, 24 buckets)")
    print("Pulling Binance SPCX fills/funding, HL fills/funding, hourly marks...")

    bin_ev = binance_spcx_events()
    bin_fund = binance_funding_events()
    hl_ev = hl_spcxd_events()

    mark_src = _args.mark_source
    marks = binance_mark_klines(_args.symbol, bnds) if mark_src == "binance" else {}
    if len([b for b in bnds if b in marks]) < len(bnds):
        pg_marks = pg_index_marks(bnds)
        for b in bnds:
            marks.setdefault(b, pg_marks.get(b))
        have = sum(1 for b in bnds if marks.get(b) is not None)
        src_lbl = "Binance markPriceKlines (1h) + PG index_price fill-in" if mark_src == "binance" \
            else "PG index_price snap (1h)"
        print(f"  marks: {src_lbl} ({have}/{len(bnds)} boundaries)")
    else:
        print(f"  marks: Binance markPriceKlines (1h), {_args.symbol} "
              f"({len(bnds)}/{len(bnds)} boundaries)")
    marks = {b: marks.get(b) for b in bnds}
    print("  hourly marks: " + " ".join(
        f"{_dt(bnds[h]).strftime('%H')}h={f(marks[bnds[h]])}" for h in range(0, 24, 3)))

    bin_rows = walk_hourly(bin_ev, marks, bnds)
    hl_rows = walk_hourly(hl_ev, marks, bnds)
    perp_legs = hl_perp_hourly(bnds)

    # binance funding bucketed by hour
    bfund_h = [ZERO] * 24
    for t, inc in bin_fund:
        if bnds[0] <= t < bnds[24]:
            bfund_h[int((t - bnds[0]) // 3_600_000)] += inc

    def _sgt(h):
        return f"{(h + 8) % 24:02d}h"      # Singapore = UTC+8

    # ── SPCX pair hourly detail ──
    pair_cols = ["UTC", "SGT", "perp_real", "perp_dU", "perp_fund", "perp_fee",
                 "spot_real", "spot_dU", "spot_fee", "mark", "PAIR hr", "CUM"]
    pair_data, cum = [], ZERO
    pair_tot = dict(pr=ZERO, pd=ZERO, pfn=ZERO, pf=ZERO, sr=ZERO, sd=ZERO, sf=ZERO, tot=ZERO)
    for h in range(24):
        b, hl = bin_rows[h], hl_rows[h]
        perp_leg = b["total"] + bfund_h[h]
        pair = perp_leg + hl["total"]
        cum += pair
        pair_tot["pr"] += b["realized"]
        pair_tot["pd"] += b["du"]
        pair_tot["pfn"] += bfund_h[h]
        pair_tot["pf"] += b["fees"]
        pair_tot["sr"] += hl["realized"]
        pair_tot["sd"] += hl["du"]
        pair_tot["sf"] += hl["fees"]
        pair_tot["tot"] += pair
        pair_data.append([f"{h:02d}h", _sgt(h), f(b["realized"]), f(b["du"]), f(bfund_h[h]),
                          f(b["fees"]), f(hl["realized"]), f(hl["du"]), f(hl["fees"]),
                          f(marks[bnds[h + 1]]), f(pair), f(cum)])
    pair_data.append(["TOTAL", "", f(pair_tot["pr"]), f(pair_tot["pd"]), f(pair_tot["pfn"]),
                      f(pair_tot["pf"]), f(pair_tot["sr"]), f(pair_tot["sd"]), f(pair_tot["sf"]),
                      "", f(pair_tot["tot"]), ""])
    render(f"SPCX DELTA-NEUTRAL PAIR — HOURLY — COB {COB}", pair_cols, pair_data, {0, 1})

    # ── HL perps hourly (aggregated across coins) ──
    perp_book = [ZERO] * 24
    if perp_legs:
        pcols = ["UTC", "SGT", "realized", "dUnreal", "funding", "fees", "HL-perp hr", "CUM"]
        pdata, cump = [], ZERO
        ptot = dict(r=ZERO, d=ZERO, fn=ZERO, fe=ZERO, t=ZERO)
        for h in range(24):
            r = d = fn = fe = ZERO
            for c in perp_legs:
                hh = perp_legs[c][h]
                r += hh["realized"]
                d += hh["du"]
                fn += hh["funding"]
                fe += hh["fees"]
            tot = r + d + fn - fe
            perp_book[h] = tot
            cump += tot
            ptot["r"] += r
            ptot["d"] += d
            ptot["fn"] += fn
            ptot["fe"] += fe
            ptot["t"] += tot
            pdata.append([f"{h:02d}h", _sgt(h), f(r), f(d), f(fn), f(fe), f(tot), f(cump)])
        pdata.append(["TOTAL", "", f(ptot["r"]), f(ptot["d"]), f(ptot["fn"]), f(ptot["fe"]),
                      f(ptot["t"]), ""])
        render(f"HL PERP LEGS ({', '.join(perp_legs)}) — HOURLY — COB {COB}", pcols, pdata, {0, 1})

    # ── book total per hour ──
    bcols = ["UTC", "SGT", "SPCX pair", "HL perps", "BOOK hr", "CUM book"]
    bdata, cumb = [], ZERO
    btot_pair = btot_perp = btot = ZERO
    for h in range(24):
        b, hl = bin_rows[h], hl_rows[h]
        pair = b["total"] + bfund_h[h] + hl["total"]
        book = pair + perp_book[h]
        cumb += book
        btot_pair += pair
        btot_perp += perp_book[h]
        btot += book
        bdata.append([f"{h:02d}h", _sgt(h), f(pair), f(perp_book[h]), f(book), f(cumb)])
    bdata.append(["TOTAL", "", f(btot_pair), f(btot_perp), f(btot), ""])
    render(f"PORTFOLIO 8041 — HOURLY BOOK PnL — COB {COB}", bcols, bdata, {0, 1})

    # ── daily roll-up tie-out (sum of hours == daily run) ──
    print(f"\nDAILY ROLL-UP (Σ hours)  COB {COB}:")
    print(f"  SPCX pair   = {f(btot_pair)} USD   "
          f"(perp {f(pair_tot['pr']+pair_tot['pd']+pair_tot['pfn']-pair_tot['pf'])} "
          f"+ spot {f(pair_tot['sr']+pair_tot['sd']-pair_tot['sf'])})")
    print(f"  HL perps    = {f(btot_perp)} USD")
    print(f"  BOOK total  = {f(btot)} USD")

    # ── CSV artifact ──
    dd = COB.split("-")[2]
    out_csv = REPO / f"8041_pnl_cob{dd}_hourly.csv"
    cols = ["hour_utc", "hour_sgt", "leg", "venue", "account", "instrument", "realized_pnl",
            "d_unreal", "funding", "fees", "total", "n_trades", "eod_qty", "mark"]
    import csv as _csv
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        wr = _csv.writer(fh)
        wr.writerow(cols)
        for h in range(24):
            hu = _dt(bnds[h]).strftime("%Y-%m-%d %H:00")
            hs = (_dt(bnds[h]) + timedelta(hours=8)).strftime("%Y-%m-%d %H:00")   # SGT = UTC+8
            b, hl = bin_rows[h], hl_rows[h]
            wr.writerow([hu, hs, "BINANCE_SPCX_PERP_SHORT", ar.venue_of(BIN_FUT), BIN_FUT,
                         "SPCX-P/USDT@BINANCE_USDT_FUTURE", f(b["realized"], 4), f(b["du"], 4),
                         f(bfund_h[h], 4), f(b["fees"], 4), f(b["total"] + bfund_h[h], 4),
                         b["n"], f(b["qty"], 4), f(marks[bnds[h + 1]], 6)])
            wr.writerow([hu, hs, "HL_SPCXD_SPOT_LONG", ar.venue_of(HLS_ACCT), HLS_ACCT,
                         "SPCXD/USDC@HYPERLIQUID_SPOT", f(hl["realized"], 4), f(hl["du"], 4),
                         "0", f(hl["fees"], 4), f(hl["total"], 4), hl["n"], f(hl["qty"], 4),
                         f(marks[bnds[h + 1]], 6)])
            for c in perp_legs:
                hh = perp_legs[c][h]
                wr.writerow([hu, hs, "HL_PERP:" + c, ar.venue_of(HLF_ACCT), HLF_ACCT, c,
                             f(hh["realized"], 4), f(hh["du"], 4), f(hh["funding"], 4),
                             f(hh["fees"], 4), f(hh["total"], 4), hh["n"], "", ""])
            book = b["total"] + bfund_h[h] + hl["total"] + perp_book[h]
            wr.writerow([hu, hs, "BOOK", "", "", "", "", "", "", "", f(book, 4), "", "", ""])
    print(f"\nWROTE hourly CSV -> {out_csv}")


if __name__ == "__main__":
    main()
