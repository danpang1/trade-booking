"""Fast entry check: does every snapshot move have a booked explanation?

Runs the SAME hourly identity as the dashboard —

    snapshot delta == fills + cash + transfers + unrealized delta

— but in QUANTITY terms only, over a short window, read-only. No marks, no
GoldRush snap-filling, no EOD summaries, no publish. The point is a ~1-minute
answer to "are trades / trading fees / funding / transfers all recorded?"
BEFORE spending an hour on the full board build.

Day-level netting is deliberate: hourly timing artifacts (fill lands in the
snapshot race window) cancel within the day, so what survives here is a real
missing or wrong entry, not noise.

Read-only by design — it checks what is STORED. Syncing belongs to the ingest
stages in daily_cycle.py, not here.

  python recon_check.py                 # last 3 days
  python recon_check.py --days 7
  python recon_check.py --start 2026-07-28
  python recon_check.py --eps 0.01      # ignore |break qty| below this
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import recon_dashboard as rd

ZERO = D(0)


def collect(start, now):
    """One fetch pass over the window; returns everything the identity needs."""
    t0 = start - timedelta(hours=2)               # anchor hour before day 1
    w0_ms = int(t0.replace(tzinfo=timezone.utc).timestamp() * 1000)
    w1_ms = int(now.replace(tzinfo=timezone.utc).timestamp() * 1000)
    snaps = rd.fetch_snaps(t0, now)
    unreal = rd.fetch_unreal(t0, now)
    fills = rd.fetch_store_fills(t0, now)
    income = rd.fetch_income(w0_ms, w1_ms)
    uni = rd.fetch_uni_transfers(w0_ms, w1_ms)
    sub = rd.fetch_sub_transfers(w0_ms, w1_ms) \
        + rd.fetch_chain_deposits(w0_ms, w1_ms)
    pm_int = rd.fetch_pm_interest(w0_ms, w1_ms)
    bs_xf = rd.fetch_wallet_transfers(t0, now)
    try:
        import hl_flows
        hl_fund = hl_flows.funding(w0_ms, w1_ms)
    except Exception as e:
        print(f"[check] WARNING: HL funding fetch failed ({e})")
        hl_fund = []
    return snaps, unreal, fills, income, uni, sub, pm_int, bs_xf, hl_fund


def run(start, now, eps):
    end = now.replace(minute=0, second=0, microsecond=0)
    print(f"[check] window {start:%Y-%m-%d} .. {end} UTC (entries only)")
    t_fetch = time.time()
    (snaps, unreal, fills, income, uni, sub, pm_int, bs_xf,
     hl_fund) = collect(start, now)
    print(f"[check] fetched in {time.time() - t_fetch:.0f}s — "
          f"{len(fills)} fills")

    # per (day, acct, asset): net break qty over the day's snapshot-bounded
    # hourly windows; timing pairs cancel here by construction
    day_brk = defaultdict(lambda: ZERO)
    brk_hours = defaultdict(int)
    ok_hours = defaultdict(int)
    no_snap = defaultdict(int)

    hour = start
    while hour < end:
        hour_iso = hour.isoformat()
        prev_iso = (hour - timedelta(hours=1)).isoformat()
        day_iso = hour.date().isoformat()
        for acct in rd.ACCOUNTS:
            s1 = snaps[acct].get(hour_iso)
            s0 = snaps[acct].get(prev_iso)
            if not s1 or not s0:
                no_snap[acct] += 1
                continue
            ok_hours[acct] += 1
            ex = rd._expected_for(acct, s0["ts"], s1["ts"], fills, income,
                                  uni, sub, pm_int, bs_xf, [], hl_fund)
            un1 = unreal.get(acct, {}).get(hour_iso, {})
            un0 = unreal.get(acct, {}).get(prev_iso, {})
            for a in set(s1["bal"]) | set(s0["bal"]) | set(ex):
                bal_d = s1["bal"].get(a, ZERO) - s0["bal"].get(a, ZERO)
                e = ex.get(a, {"fills": ZERO, "cash": ZERO,
                               "transfers": ZERO})
                ud = ZERO
                if (acct in rd.PERP_SUFFIX
                        and a in rd.CASH_ASSETS.get(acct, ())):
                    ud = un1.get(a, ZERO) - un0.get(a, ZERO)
                brk = bal_d - (e["fills"] + e["cash"] + e["transfers"] + ud)
                if brk != 0:
                    day_brk[(day_iso, acct, a)] += brk
                    brk_hours[(day_iso, acct, a)] += 1
        hour += timedelta(hours=1)

    # ---- report ----
    print(f"\n{'account':44} {'ok hrs':>7} {'no snap':>8}")
    for acct in rd.ACCOUNTS:
        flag = "  <-- gaps" if no_snap[acct] > 2 else ""
        print(f"{acct:44} {ok_hours[acct]:>7} {no_snap[acct]:>8}{flag}")

    bad = [(k, v) for k, v in day_brk.items() if abs(v) > D(str(eps))]
    bad.sort(key=lambda kv: (kv[0][0], -abs(kv[1])))
    if not bad:
        print(f"\nCLEAN: every snapshot move is explained by stored entries "
              f"(|net day break| <= {eps} qty everywhere)")
        return 0
    print(f"\n{len(bad)} day-level break(s) above {eps} qty "
          "(hourly timing already netted out):")
    print(f"{'day':>10}  {'account':40} {'asset':10} "
          f"{'net break qty':>16} {'hrs':>4}")
    cur_day = None
    for (day, acct, a), v in bad:
        d_lbl = day if day != cur_day else ""
        cur_day = day
        print(f"{d_lbl:>10}  {acct.split('@')[0]:40} {a:10} "
              f"{v:>16,.6f} {brk_hours[(day, acct, a)]:>4}")
    print("\nfix the entries (ingest stage for that source), re-run this, "
          "and only then rebuild the board")
    return 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--start", help="YYYY-MM-DD (overrides --days)")
    ap.add_argument("--eps", type=float, default=1e-6,
                    help="ignore day-net breaks at or below this qty")
    args = ap.parse_args()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if args.start:
        start = datetime.strptime(args.start, "%Y-%m-%d")
    else:
        start = (now - timedelta(days=args.days)).replace(
            hour=0, minute=0, second=0, microsecond=0)
    sys.exit(run(start, now, args.eps))


if __name__ == "__main__":
    main()
