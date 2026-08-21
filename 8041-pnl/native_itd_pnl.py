"""Native Core ITD (inception-to-date) PnL from the stored avg-cost trades.

  python native_itd_pnl.py --date 2026-07-01

Per {SYM}/USDT@NATIVECORE leg, over ALL stored trades up to the COB EOD
boundary (--date 23:59:59 UTC):
  realized   = avg-cost engine realized, summed
  unreal     = EOD position x (EOD mark - avg cost); mark = matching HL `xyz:`
               perp index at the EOD boundary (the agreed Native mark source)
  fees       = fee_usd summed (in-kind fees valued at fill price)
  ITD total  = realized + unreal - fees          (spot: no funding)
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
import avgcost_db as adb  # noqa: E402
from native_common import ACCOUNT_NAME, SYMBOL_TO_HL  # noqa: E402

ZERO = Decimal(0)


def eod_mark(hl_instrument, boundary):
    """HL xyz perp index_price at the EOD boundary snap (first snap within
    60 min after it), from tq_hist_position — same source as the daily table."""
    import psycopg2
    from pg import PG_HOST, PG_PORT, PG_USER, PG_PASS, PG_DB
    coin = hl_instrument.split("-P/")[0]
    conn = psycopg2.connect(host=PG_HOST, port=PG_PORT, user=PG_USER,
                            password=PG_PASS, database=PG_DB, connect_timeout=15)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT index_price FROM tq_hist_position
            WHERE account_name = 'TRADING_06@HYPERLIQUID_FUTURES'
              AND instrument ILIKE %s
              AND record_ts >= %s AND record_ts < %s
            ORDER BY record_ts LIMIT 1
        """, (coin + "%", boundary, boundary + timedelta(minutes=60)))
        r = cur.fetchone()
        return Decimal(str(r[0])) if r and r[0] is not None else None
    finally:
        conn.close()


def f(x, dp=2):
    return "—" if x is None else f"{float(x):,.{dp}f}"


def main():
    ap = argparse.ArgumentParser(description="Native ITD PnL from stored trades")
    ap.add_argument("--date", default="2026-07-01", help="COB day YYYY-MM-DD")
    a = ap.parse_args()
    w0 = datetime(2026, 6, 1, tzinfo=timezone.utc)          # before inception
    w1 = (datetime.strptime(a.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
          + timedelta(days=1))
    boundary = w1.replace(tzinfo=None)

    conn = adb.connect()
    rows = []
    try:
        for inst, acct, prod, quote in adb.distinct_instruments(conn):
            if acct != ACCOUNT_NAME or "@NATIVECORE" not in inst:
                continue
            sym = inst.split("/")[0]
            realized, fee_usd, n_api, n_man = adb.window_agg(conn, inst, w0, w1)
            eq, ea = adb.pos_at(conn, inst, w1)
            eq, ea = Decimal(str(eq)), Decimal(str(ea))
            hl = SYMBOL_TO_HL.get(sym)
            mark = eod_mark(hl, boundary) if hl else None
            unreal = (mark - ea) * eq if (mark is not None and eq != 0) else ZERO
            total = Decimal(str(realized)) + unreal - Decimal(str(fee_usd))
            rows.append([inst, n_api + n_man, eq, ea, mark,
                         Decimal(str(realized)), unreal, Decimal(str(fee_usd)), total])
    finally:
        conn.close()

    cols = ["instrument", "trades", "EOD qty", "avg cost", "EOD mark",
            "realized", "unreal", "fees", "ITD total"]
    data = [[r[0], str(r[1]), f(r[2], 4), f(r[3], 4), f(r[4], 4),
             f(r[5]), f(r[6]), f(r[7]), f(r[8])] for r in rows]
    tot = [sum((r[i] for r in rows), ZERO) for i in (5, 6, 7, 8)]
    data.append(["TOTAL", "", "", "", "", f(tot[0]), f(tot[1]), f(tot[2]), f(tot[3])])
    w = [max(len(cols[i]), *(len(d[i]) for d in data)) for i in range(len(cols))]

    def bar(a_, m, c):
        return a_ + m.join("─" * (w[i] + 2) for i in range(len(w))) + c

    def line(cs, center=False):
        return "│" + "│".join(" " + (cs[i].center(w[i]) if center else
                                     (cs[i].ljust(w[i]) if i == 0 else cs[i].rjust(w[i]))) + " "
                              for i in range(len(cs))) + "│"

    print(f"\nNATIVE CORE — ITD PnL (ALL stored trades) — inception -> COB {a.date} 23:59:59 UTC")
    print(f"  account {ACCOUNT_NAME}; marks = HL xyz: perp index at the EOD boundary; USDT@1")
    print(bar("┌", "┬", "┐"))
    print(line(cols, True))
    print(bar("├", "┼", "┤"))
    for d in data:
        print(line(d))
    print(bar("└", "┴", "┘"))


if __name__ == "__main__":
    main()
