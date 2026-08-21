"""8041 month-to-date PnL, split into three groups, with a daily breakdown.

  python mtd_split.py --date 2026-06-24

  Dinari PnL    = TK810@BINANCE_USDT_FUTURE (Binance SPCX perp)
                + TRADING_06@HYPERLIQUID_SPOT (HL SPCXD spot)
  Native PnL    = TRADING_01@NATIVECORE trades (avg-cost store; canonical
                  since 2026-07-02) + TRADING_06@HYPERLIQUID_FUTURES (HL
                  xyz:* / HYPE perps). Snapshot NAV Δ shown as cross-check
                  only — NOT in the totals (it would double count).
  Robinhood PnL = WALLET_CRB_EVM_02_ROBINHOOD (chain RFQ maker, {TICKER}/USDG
                  legs; marks via the daily table's xyz/Yahoo resolver)

Each day's per-instrument net is computed with the SAME avg-cost logic as
pnl_8041_daily.py (realized + ΔUnreal + funding − fees), read from the stored
trades in trades_spot_avgcost (no re-pull). Marks/funding sources are identical
to the daily script. Days run from INCEPTION to --date; Day Total + MTD tie to
the daily script's "ALL-TRADES + NATIVE MTM" line.
"""
from __future__ import annotations
import argparse, hashlib, hmac, json, sys, time, urllib.parse, urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")   # box-drawing chars on Windows cp1252
except Exception:
    pass

import avgcost_db as adb
import account_recon as ar
import equity_marks as eqm
import native_pnl_snapshot as nps
from engine import Position, unrealized, D, ZERO
from native_common import ACCOUNT_NAME as NTV_ACCT, SYMBOL_TO_HL
from asset_map import std_asset

INCEPTION = "2026-06-12"
PINNED_MARKS = {"2026-06-14": "168.01", "2026-06-15": "199.82"}
BIN_ACCT = "TK810@BINANCE_USDT_FUTURE"
BIN_SPOT_ACCT = "TK810@BINANCE_SPOT"
HLS_ACCT = "TRADING_06@HYPERLIQUID_SPOT"
HLF_ACCT = "TRADING_06@HYPERLIQUID_FUTURES"
RH_ACCT = "WALLET_CRB_EVM_02_ROBINHOOD"
ETH_RFQ_ACCT = "WALLET_CRB_EVM_04_ETHEREUM"
DINARI_ACCTS = {BIN_ACCT, HLS_ACCT}

_ap = argparse.ArgumentParser(description="8041 MTD PnL split: Dinari vs Native")
_ap.add_argument("--date", default="2026-06-24", help="COB day YYYY-MM-DD (MTD end)")
_ap.add_argument("--inception", default=INCEPTION, help="MTD start YYYY-MM-DD")
_ap.add_argument("--by-account", action="store_true",
                 help="one column per account instead of Dinari/Native buckets "
                      "(skips the NAV-Δ cross-check pull)")
_args, _ = _ap.parse_known_args()
COB = _args.date
INCEPTION = _args.inception
BY_ACCOUNT = _args.by_account


def drange(a, b):
    da, db = datetime.strptime(a, "%Y-%m-%d"), datetime.strptime(b, "%Y-%m-%d")
    out, d = [], da
    while d <= db:
        out.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return out


DAYS = drange(INCEPTION, COB)
CUTOFFS = [(datetime.strptime(INCEPTION, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")] + DAYS


def f(x, dp=2):
    return "—" if x is None else f"{float(x):,.{dp}f}"


def day_of(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def marks_for(account, inst_like, cutoffs, _retry=True):
    """EOD index mark per cutoff day for (account, instrument) — tq_hist_position
    at each day's ~00:0x boundary. Identical to pnl_8041_daily.marks_for.
    One retry on a dropped connection (fresh conn per call; transient drops
    otherwise kill a long MTD run)."""
    import psycopg2
    from pg import PG_HOST, PG_PORT, PG_USER, PG_PASS, PG_DB
    try:
        conn = psycopg2.connect(host=PG_HOST, port=PG_PORT, user=PG_USER,
                                password=PG_PASS, database=PG_DB, connect_timeout=15)
        out = {}
        try:
            cur = conn.cursor()
            for d in cutoffs:
                bnd = datetime.strptime(d, "%Y-%m-%d") + timedelta(days=1)
                cur.execute("""
                    SELECT index_price FROM tq_hist_position
                    WHERE account_name = %s AND instrument ILIKE %s
                      AND record_ts >= %s AND record_ts < %s
                    ORDER BY record_ts LIMIT 1
                """, (account, inst_like, bnd, bnd + timedelta(minutes=60)))
                r = cur.fetchone()
                if r and r[0] is not None:
                    out[d] = D(str(r[0]))
        finally:
            conn.close()
        return out
    except psycopg2.OperationalError:
        if not _retry:
            raise
        time.sleep(2)
        return marks_for(account, inst_like, cutoffs, _retry=False)


def bin_funding_by_day():
    """Signed FUNDING_FEE income per (day, symbol) — Binance UM, all symbols."""
    key, secret = ar.env("810.BINANCE_API_KEY"), ar.env("810.BINANCE_API_SECRET")

    def sget(params):
        p = dict(params); p["timestamp"] = int(time.time() * 1000); p["recvWindow"] = 60000
        qs = urllib.parse.urlencode(p)
        sig = hmac.new(secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
        r = urllib.request.urlopen(urllib.request.Request(
            "https://papi.binance.com/papi/v1/um/income?" + qs + "&signature=" + sig,
            headers={"X-MBX-APIKEY": key}), timeout=20)
        return json.loads(r.read())

    by_day, cursor = defaultdict(lambda: ZERO), 1781000000000
    while True:
        batch = sget({"incomeType": "FUNDING_FEE", "startTime": cursor, "limit": 1000})
        if not batch:
            break
        for r in batch:
            by_day[(day_of(int(r["time"])), str(r.get("symbol", "")))] += D(str(r["income"]))
        if len(batch) < 1000:
            break
        cursor = max(int(r["time"]) for r in batch) + 1
    return by_day


# ── precompute marks + funding once ──
bin_fund = bin_funding_by_day()
hl_fund = defaultdict(lambda: ZERO)            # (day, coin) -> usdc
for r in ar.hl_funding():
    hl_fund[(day_of(int(r["time"])), r["delta"]["coin"])] += D(str(r["delta"]["usdc"]))

spcx_marks = marks_for(BIN_ACCT, "%SPCX%", CUTOFFS)
for _d, _m in PINNED_MARKS.items():
    spcx_marks.setdefault(_d, D(_m))

conn = adb.connect()
INSTS = [(i, a, p) for i, a, p, _q in adb.distinct_instruments(conn)]


def _native_hl_coin(inst):
    """SPCXB/USDT@NATIVECORE -> 'xyz:SPCX' (its HL mark coin), or None (USDT)."""
    hl = SYMBOL_TO_HL.get(inst.split("/")[0])
    return hl.split("-P/")[0] if hl else None


# per-coin HL perp marks (non-SPCX) cached once
coin_marks = {}
for inst, acct, prod in INSTS:
    macct = HLF_ACCT
    if "@NATIVECORE" in inst:
        coin = _native_hl_coin(inst)
    elif "SPCX" in inst or "@ROBINHOOD" in inst or "@BITSTAMP" in inst \
            or "@BINANCE_SPOT" in inst:        # B-tokens mark via _eq_mark
        continue
    elif "@ETHEREUM_RFQ" in inst:              # ETH inventory -> tk810 ETH index
        coin, macct = "ETH", BIN_ACCT
    elif "@BINANCE" in inst:                   # non-SPCX Binance UM perp
        coin, macct = inst.split("-P/")[0], BIN_ACCT
    else:
        coin = inst.split("-P/")[0]
    if coin and coin not in coin_marks:
        coin_marks[coin] = marks_for(macct, coin + "%", CUTOFFS)


_eq_mark_cache = {}


def _eq_mark(ticker, day):
    """Tokenized-equity mark (same resolver as the daily table): HL xyz
    historical EOD index where 8041 holds the perp, Yahoo for ETFs, live xyz
    oracle for the report COB only. Memoized — the MTD loop hits every
    (ticker, day) twice (SOD + EOD)."""
    k = (ticker, day)
    if k not in _eq_mark_cache:
        _eq_mark_cache[k] = eqm.resolve_mark(
            ticker, day, is_cob=(day == COB),
            hist_fn=lambda t, d: marks_for(HLF_ACCT, "xyz:" + t + "%", [d]).get(d))
    return _eq_mark_cache[k]


def mark_for(inst, day):
    if "@NATIVECORE" in inst:              # before 'SPCX' — SPCXB contains SPCX
        coin = _native_hl_coin(inst)
        return coin_marks[coin].get(day) if coin else None
    if "@ROBINHOOD" in inst or "@BITSTAMP" in inst:
        return _eq_mark(inst.split("/")[0], day)
    if "SPCX" in inst:
        return spcx_marks.get(day)
    if "@BINANCE_SPOT" in inst:                # B-token -> underlying's eq mark
        return _eq_mark(std_asset(inst.split("/")[0]), day)
    if "@ETHEREUM_RFQ" in inst:
        return coin_marks["ETH"].get(day)
    return coin_marks[inst.split("-P/")[0]].get(day)


def day_net_by_account(day):
    """{account -> net PnL} for the single COB day, all-trades instruments."""
    w0 = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    w1 = w0 + timedelta(days=1)
    sod_day = (w0 - timedelta(days=1)).strftime("%Y-%m-%d")
    by_acct = defaultdict(lambda: ZERO)
    for inst, acct, prod in INSTS:
        realized, fee_usd, _na, _nm = adb.window_agg(conn, inst, w0, w1)
        sod_q, sod_a = adb.pos_at(conn, inst, w0)
        eod_q, eod_a = adb.pos_at(conn, inst, w1)
        em, sm = mark_for(inst, day), mark_for(inst, sod_day)
        sod_pos, eod_pos = Position(D(str(sod_q)), D(str(sod_a))), Position(D(str(eod_q)), D(str(eod_a)))
        su = unrealized(sod_pos, sm) if (sm and sod_pos.qty != 0) else ZERO
        eu = unrealized(eod_pos, em) if (em and eod_pos.qty != 0) else ZERO
        du = eu - su
        if "@BINANCE" in inst and "-P/" in inst:  # UM perps only (spot: no funding)
            fnd = bin_fund.get((day, inst.split("-P/")[0]
                                + inst.split("-P/")[1].split("@")[0]), ZERO)
        elif prod == "PERP":
            fnd = hl_fund.get((day, inst.split("-P/")[0]), ZERO)
        else:
            fnd = ZERO
        by_acct[acct] += D(str(realized)) + du + fnd - D(str(fee_usd))
    return by_acct


if BY_ACCOUNT:
    BITSTAMP_ACCT = "MOON-TOKKA@BITSTAMP"
    ACCTS = [(BIN_ACCT, "BINANCE 810"), (BIN_SPOT_ACCT, "BIN SPOT"),
             (HLS_ACCT, "HL SPOT"), (HLF_ACCT, "HL FUT"),
             (NTV_ACCT, "NATIVE"), (BITSTAMP_ACCT, "BITSTAMP"), (RH_ACCT, "ROBINHOOD"),
             (ETH_RFQ_ACCT, "ETH RFQ")]
    # Manually supplied venue day-PnL overlays — venues with NO trades in the
    # avg-cost store yet. Provided by the user 2026-07-02.
    MANUAL = {
        "IBKR*": {"2026-06-30": D("-20473.5"), "2026-07-01": D("56628.31"),
                  "2026-07-02": D("58476"),
                  # 07-03..05 combined lump (user ITD@07-05 = 56,299.00)
                  "2026-07-05": D("-38331.81"),
                  # user ITD@07-06 = 64,919.00
                  "2026-07-06": D("8620"),
                  # user ITD@07-07 = 143,004 (balance 693,004 − 550k funding)
                  "2026-07-07": D("78085"),
                  # user ITD@07-08 = 114,228
                  "2026-07-08": D("-28776"),
                  # user ITD@07-09 = 51,322
                  "2026-07-09": D("-62906"),
                  # 07-10..12 combined lump (user ITD@07-12 = 32,881)
                  "2026-07-12": D("-18441"),
                  # user ITD@07-13 = 128,712
                  "2026-07-13": D("95831"),
                  # user ITD@07-14 = 57,967.78
                  "2026-07-14": D("-70744.22"),
                  # user ITD@07-15 = 86,701.42
                  "2026-07-15": D("28733.64")},
    }
    print(f"\nPORTFOLIO 8041 — DAILY + ITD PnL BY ACCOUNT — {INCEPTION} -> COB {COB}")
    print("  per-day net = realized + ΔUnreal + funding − fees per account "
          "(avg-cost store; marks as the daily table)")
    print("  * = manually supplied day figures (no trades in the store)")
    labels = [lbl for _, lbl in ACCTS] + list(MANUAL)
    cols = ["COB Day"] + labels + ["Day Total", "ITD"]
    data, itd = [], ZERO
    try:
        for day in DAYS:
            by_acct = day_net_by_account(day)
            vals = [by_acct.get(a, ZERO) for a, _ in ACCTS]
            unmapped = sum(by_acct.values(), ZERO) - sum(vals, ZERO)
            if abs(unmapped) > D("0.005"):
                print(f"  (WARNING {day}: {f(unmapped)} USD in accounts outside the "
                      "column list)")
            vals += [m.get(day, ZERO) for m in MANUAL.values()]
            total = sum(vals, ZERO)
            itd += total
            data.append([day] + [f(v) for v in vals] + [f(total), f(itd)])
    finally:
        conn.close()
    sums = [sum((D(r[i + 1].replace(",", "")) for r in data), ZERO)
            for i in range(len(labels))]
    data.append(["ITD TOTAL"] + [f(s) for s in sums] + ["", f(itd)])

    pw = [max(len(cols[i]), *(len(r[i]) for r in data)) for i in range(len(cols))]

    def _bar(a, m, c):
        return a + m.join("─" * (pw[i] + 2) for i in range(len(pw))) + c

    def _line(cs, center=False):
        return "│" + "│".join(" " + (cs[i].center(pw[i]) if center else
               (cs[i].ljust(pw[i]) if i == 0 else cs[i].rjust(pw[i]))) + " "
               for i in range(len(cs))) + "│"

    print(_bar("┌", "┬", "┐"))
    print(_line(cols, True))
    print(_bar("├", "┼", "┤"))
    for r in data:
        print(_line(r))
    print(_bar("└", "┴", "┘"))
    print("  ".join(f"{lbl} {f(s)}" for lbl, s in zip(labels, sums))
          + f"  =  {f(itd)} USD ITD")
    sys.exit(0)

print(f"\nPORTFOLIO 8041 — DAILY + MTD PnL, split DINARI vs NATIVE vs ROBINHOOD — {INCEPTION} -> COB {COB}")
print("  Dinari = Binance SPCX perp + HL SPCXD spot   |   "
      "Native = Native Core TRADES (avg-cost store) + HL xyz:/HYPE perps   |   "
      "Robinhood = chain RFQ maker (WALLET_CRB_EVM_02)")
print("  Native NAV Δ = snapshot mark-to-market, CROSS-CHECK ONLY (not in totals; "
      "trades are canonical since 2026-07-02)")
cols = ["COB Day", "Dinari Net", "Native Trades", "HL futures Net", "Native Net",
        "NAV Δ (chk)", "Robinhood Net", "Day Total", "MTD"]
data, mtd = [], ZERO
try:
    for day in DAYS:
        by_acct = day_net_by_account(day)
        dinari = sum((v for a, v in by_acct.items() if a in DINARI_ACCTS), ZERO)
        hl_fut = by_acct.get(HLF_ACCT, ZERO)
        ntv = by_acct.get(NTV_ACCT, ZERO)
        navd = nps.nav_delta(day)
        navd = navd if navd is not None else ZERO
        native = hl_fut + ntv
        rh = by_acct.get(RH_ACCT, ZERO)
        total = dinari + native + rh
        mtd += total
        data.append([day, f(dinari), f(ntv), f(hl_fut), f(native), f(navd), f(rh),
                     f(total), f(mtd)])
finally:
    conn.close()

mtd_dinari = sum((D(r[1].replace(",", "")) for r in data), ZERO)
mtd_native = sum((D(r[4].replace(",", "")) for r in data), ZERO)
mtd_rh = sum((D(r[6].replace(",", "")) for r in data), ZERO)
data.append(["MTD TOTAL", f(mtd_dinari), "", "", f(mtd_native), "", f(mtd_rh), "", f(mtd)])

pw = [max(len(cols[i]), *(len(r[i]) for r in data)) for i in range(len(cols))]


def bar(a, m, c):
    return a + m.join("─" * (pw[i] + 2) for i in range(len(pw))) + c


def line(cs, center=False):
    return "│" + "│".join(" " + (cs[i].center(pw[i]) if center else
           (cs[i].ljust(pw[i]) if i == 0 else cs[i].rjust(pw[i]))) + " "
           for i in range(len(cs))) + "│"


print(bar("┌", "┬", "┐"))
print(line(cols, True))
print(bar("├", "┼", "┤"))
for r in data:
    print(line(r))
print(bar("└", "┴", "┘"))
print(f"MTD Dinari {f(mtd_dinari)} + MTD Native (trades) {f(mtd_native)} "
      f"+ MTD Robinhood {f(mtd_rh)} = {f(mtd)} USD")
