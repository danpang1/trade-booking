"""Native Core (TRADING_01@NATIVECORE) — snapshot mark-to-market PnL for a COB day.

WHY THIS EXISTS (read the caveats — this is NOT a trade-based PnL):
Native's `userFills` only covers the most recent ~10k blocks and there is no
stored fill history or cost basis anywhere (see native_common.py). So for any
PAST day we cannot fold avg-cost. What we DO have is the hourly position-qty
snapshot history (tq_hist_position_mo) plus a mark source — the matching HL
`xyz:` perp index price (tq_hist_position). This script marks those snapshots to
market and reports the price-driven PnL for the COB day.

Three views, because the book was being BUILT during the day (qty changes a lot,
and we have no per-trade entry price):
  * SOD-carry MTM  = qty_SOD x (mark_EOD - mark_SOD)         — price move on the
                     start-of-day book only (ignores intraday adds).
  * Time-wtd MTM   = sum over hourly steps of qty(t) x dmark — marks the held
                     position through each hour, so it captures the growing book's
                     exposure. Best price-only estimate from snapshots.
  * NAV change     = d(sum qty x mark) + d(USDT)             — total economic move
                     incl. book-building and fees; muddied by any external
                     capital transfer into/out of the credit account.

None of these include fees/funding broken out, exact realized, or trade slippage
(no fills). Treat as an MTM estimate, not the booked PnL.

    python native_pnl_snapshot.py --date 2026-06-22
"""
from __future__ import annotations
import argparse
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
import avgcost_db as adb            # noqa: E402  (MO DB UAT — Native snapshots)
from pg import PG_HOST, PG_PORT, PG_USER, PG_PASS, PG_DB  # noqa: E402  (balance DB — HL marks)
from native_common import (ACCOUNT_NAME, INSTR_VENUE, SYMBOL_TO_HL,  # noqa: E402
                           CASH_SYMBOLS, hl_instrument_for, D)

ZERO = Decimal("0")
# Snapshots land a few seconds after each hour boundary. Keep the tail tight so
# the EOD anchor is the day1 00:00 boundary snap, not the following 01:00 one.
BUF_MIN = 15


def _bal_conn():
    import psycopg2
    return psycopg2.connect(host=PG_HOST, port=PG_PORT, user=PG_USER, password=PG_PASS,
                            database=PG_DB, connect_timeout=15)


def native_hourly(conn, day0, day1):
    """{symbol -> [(record_ts, signed_qty), ...]} one snap per hour over
    [day0, day1] inclusive of the day1 00:00 EOD boundary, signed by side."""
    out: dict[str, list] = {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT ON (instrument, date_trunc('hour', record_ts)) "
            "  instrument, side, pos_qty, record_ts "
            "FROM tq_hist_position_mo "
            "WHERE account_name = %s AND record_ts >= %s "
            "  AND record_ts < %s + INTERVAL '%s minutes' "
            "ORDER BY instrument, date_trunc('hour', record_ts), record_ts",
            (ACCOUNT_NAME, day0, day1, BUF_MIN),
        )
        for inst, side, qty, ts in cur.fetchall():
            sym = inst.split("@")[0].upper()
            sq = -abs(D(qty)) if (side or "").lower() == "short" else abs(D(qty))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            out.setdefault(sym, []).append((ts, sq))
    for sym in out:
        out[sym].sort(key=lambda r: r[0])
    return out


def hl_marks_hourly(conn, hl_insts, day0, day1):
    """{hl_instrument -> [(record_ts, index_price), ...]} one mark per hour."""
    out: dict[str, list] = {}
    if not hl_insts:
        return out
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT ON (instrument, date_trunc('hour', record_ts)) "
            "  instrument, index_price, record_ts "
            "FROM tq_hist_position "
            "WHERE account_name = 'TRADING_06@HYPERLIQUID_FUTURES' "
            "  AND instrument = ANY(%s) AND record_ts >= %s "
            "  AND record_ts < %s + INTERVAL '%s minutes' "
            "ORDER BY instrument, date_trunc('hour', record_ts), record_ts",
            (list(hl_insts), day0, day1, BUF_MIN),
        )
        for inst, px, ts in cur.fetchall():
            if px is not None:
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                out.setdefault(inst, []).append((ts, D(px)))
    for inst in out:
        out[inst].sort(key=lambda r: r[0])
    return out


def _asof(series, ts):
    """Latest value in a [(ts, v), ...] series at-or-before ts (else earliest)."""
    val = series[0][1] if series else None
    for t, v in series:
        if t <= ts:
            val = v
        else:
            break
    return val


def _boundary(series, target_ts, day0):
    """Value of a series at the snapshot closest to target_ts (within the day)."""
    if not series:
        return None
    best = min(series, key=lambda r: abs((r[0] - target_ts).total_seconds()))
    return best[1]


def f(x, dp=2):
    return "—" if x is None else f"{float(x):,.{dp}f}"


def compute_totals(date_iso):
    """Mark the COB day's Native snapshots; return (rows, soc_total, twm_total,
    nav_total) or None if there are no snapshots to mark."""
    day0 = datetime.strptime(date_iso, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    day1 = day0 + timedelta(days=1)
    mo = adb.connect()
    try:
        nat = native_hourly(mo, day0, day1)
    finally:
        mo.close()
    if not nat:
        return None

    hl_insts = {hl_instrument_for(s) for s in nat if hl_instrument_for(s)}
    bal = _bal_conn()
    try:
        marks = hl_marks_hourly(bal, hl_insts, day0, day1)
    finally:
        bal.close()

    # per-symbol mark series (USDT/cash -> flat 1.0 over the day's hours)
    def mark_series(sym):
        hl = hl_instrument_for(sym)
        if hl:
            return marks.get(hl, [])
        if sym in CASH_SYMBOLS:
            hours = [t for t, _ in nat[sym]]
            return [(t, Decimal("1")) for t in hours]
        return []

    rows, twm_total, soc_total, nav_total = [], ZERO, ZERO, ZERO
    for sym in sorted(nat, key=lambda s: (s in CASH_SYMBOLS, s)):
        qser = nat[sym]
        mser = mark_series(sym)
        sod_q, eod_q = qser[0][1], qser[-1][1]
        sod_m = _boundary(mser, day0, day0) if mser else None
        eod_m = _boundary(mser, day1, day0) if mser else None
        # SOD-carry: start-of-day position carried at the day's price move
        soc = (sod_q * (eod_m - sod_m)) if (sod_m is not None and eod_m is not None) else None
        # Time-weighted: mark the held qty through each hourly step
        twm = ZERO if mser else None
        if mser:
            ticks = sorted({t for t, _ in qser} | {t for t, _ in mser})
            for a, b in zip(ticks, ticks[1:]):
                q = _asof(qser, a)
                ma, mb = _asof(mser, a), _asof(mser, b)
                if q is not None and ma is not None and mb is not None:
                    twm += q * (mb - ma)
        # NAV contribution: change in marked value of this leg
        nav = None
        if sod_m is not None and eod_m is not None:
            nav = eod_q * eod_m - sod_q * sod_m
        rows.append([sym, sod_q, eod_q, sod_m, eod_m,
                     (eod_m - sod_m) if (sod_m is not None and eod_m is not None) else None,
                     soc, twm, nav])
        if soc is not None:
            soc_total += soc
        if twm is not None:
            twm_total += twm
        if nav is not None:
            nav_total += nav
    return rows, soc_total, twm_total, nav_total


def nav_delta(date_iso):
    """Native NAV change (incl. book-building/transfers) for the COB day, or
    None if there are no snapshots. Lets pnl_8041_daily print the combined
    ALL-TRADES + NATIVE MTM line right under its ALL-TRADES NET PnL line."""
    res = compute_totals(date_iso)
    return None if res is None else res[3]


def run(date_iso):
    res = compute_totals(date_iso)
    if res is None:
        print(f"No Native snapshots for {date_iso} — nothing to mark.")
        return
    rows, soc_total, twm_total, nav_total = res

    cols = ["symbol", "SOD qty", "EOD qty", "SOD mark", "EOD mark", "Δmark",
            "SOD-carry MTM", "Time-wtd MTM", "NAV Δ"]
    data = [[r[0], f(r[1], 4), f(r[2], 4), f(r[3], 4), f(r[4], 4), f(r[5], 4),
             f(r[6]), f(r[7]), f(r[8])] for r in rows]
    data.append(["TOTAL", "", "", "", "", "", f(soc_total), f(twm_total), f(nav_total)])
    w = [max(len(cols[i]), *(len(r[i]) for r in data)) for i in range(len(cols))]

    def bar(a, m, c):
        return a + m.join("─" * (w[i] + 2) for i in range(len(w))) + c

    def line(cs, center=False):
        return "│" + "│".join(" " + (cs[i].center(w[i]) if center else
               (cs[i].ljust(w[i]) if i == 0 else cs[i].rjust(w[i]))) + " "
               for i in range(len(cs))) + "│"

    print(f"\n{'='*100}")
    print(f"NATIVE CORE ({ACCOUNT_NAME}) — SNAPSHOT MARK-TO-MARKET — COB {date_iso}")
    print("marks: matching HL xyz: perp index price (tq_hist_position); USDT@1.00")
    print(bar("┌", "┬", "┐"))
    print(line(cols, True))
    print(bar("├", "┼", "┤"))
    for r in data:
        print(line(r))
    print(bar("└", "┴", "┘"))
    print("MTM ESTIMATE ONLY — no fills/cost basis available for Native, so no")
    print("realized/fees/funding split and intraday adds are priced at snapshot")
    print("marks, not actual entry. NAV Δ also moves with any external capital")
    print("transfer into/out of the credit account (not separable from snapshots).")
    print(f"\n  Price-only (time-weighted) MTM ≈ {f(twm_total)} USD")
    print(f"  NAV change (incl. book-building/fees/transfers) ≈ {f(nav_total)} USD")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Native Core snapshot MTM PnL for a COB day")
    ap.add_argument("--date", default="2026-06-22", help="COB day YYYY-MM-DD")
    a = ap.parse_args()
    run(a.date)
