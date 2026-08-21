"""The standardized 8041 daily cycle: ingest everything, then rebuild.

Replaces the hand-copied `_run_cycle_<DDMM>.bat` files. Two properties those
did not have:

  SELF-DATING   dates come from UTC now, so there is nothing to edit each day
                and no risk of running yesterday's window twice.

  NOTHING SILENTLY DROPPED
                snapshot jobs are driven by the account_sources registry, and
                every SELF-owned account MUST have a recipe here. Add an
                account to the registry without wiring its job and this script
                refuses to run rather than quietly leaving it unfed — which is
                precisely how WALLET_CRB_EVM_04_ETHEREUM lost 57 hours.

Stages are independent: one failing is reported and the cycle continues, so a
GoldRush hiccup cannot cost you the whole day's ingest. The summary at the end
is the record of what actually happened.

  python daily_cycle.py                 # yesterday's COB, full cycle
  python daily_cycle.py --date 2026-07-30
  python daily_cycle.py --no-rebuild    # ingest only
  python daily_cycle.py --rebuild-only
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import account_sources

REPO = Path(__file__).resolve().parent
PY = sys.executable
WINDOW_START = "2026-06-09"     # dashboard history floor

# How each SELF-owned snapshot job is invoked. Keys MUST cover
# account_sources.jobs() — see _check_recipes().
JOB_CMDS = {
    "eth_goldrush_snaps": [
        ("snaps", ["eth_goldrush_snaps.py", "3"]),
    ],
    "dinari_goldrush_snaps": [
        ("snaps", ["dinari_goldrush_snaps.py", "3"]),
    ],
    "evm_custody_wallets": [
        ("transfers", ["evm_custody_wallets.py", "transfers", "{since}"]),
        # --dense over a SHORT window: history is ~99% filled, and the sparse
        # default would re-open gaps at the tip every day. {tip} keeps the
        # paid-call count to a couple of days, not the whole window.
        ("snaps", ["evm_custody_wallets.py", "snaps", "{tip}", "--dense"]),
    ],
}


def _check_recipes():
    missing = [j for j in account_sources.jobs() if j not in JOB_CMDS]
    if missing:
        raise SystemExit(
            "account_sources lists SELF-owned jobs with no recipe in "
            f"JOB_CMDS: {missing}\nWire them here or the accounts go unfed.")


def _last_fill_date(venue):
    """Date (YYYY-MM-DD) of the newest stored fill for a venue, or None."""
    import avgcost_db
    conn = avgcost_db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT max(trade_date) FROM trades_spot_avgcost "
                        "WHERE venue = %s", (venue,))
            row = cur.fetchone()[0]
        return row.strftime("%Y-%m-%d") if row else None
    except Exception:
        return None
    finally:
        conn.close()


def _ingest_lag():
    """Hours the newest stored fill trails the newest balance snapshot.

    The recon explains a snapshot delta with fills; if snapshots are hours
    fresher than the store, those hours break by construction and the numbers
    look alarming while nothing is wrong. Worth stating out loud — an
    unexplained six-figure break on the open day is exactly the thing someone
    chases for an hour before noticing the ingest simply hadn't run."""
    import avgcost_db
    conn = avgcost_db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT max(trade_date) FROM trades_spot_avgcost")
            fill = cur.fetchone()[0]
            cur.execute("SELECT max(sync_ts) FROM tq_hist_balance_mo")
            snap = cur.fetchone()[0]
        if not fill or not snap:
            return 0.0
        fill = fill.replace(tzinfo=None)
        return max(0.0, (snap - fill).total_seconds() / 3600)
    except Exception:
        return 0.0
    finally:
        conn.close()


class Cycle:
    def __init__(self):
        self.results = []

    def run(self, label, argv, timeout=7200):
        print(f"\n=== {label} ===", flush=True)
        t0 = time.time()
        # Inherit stdout rather than capture: a captured stage prints nothing
        # until it EXITS, so a multi-hour rebuild would run in total silence
        # and be indistinguishable from a hang. Only the return code feeds the
        # summary, so there is nothing to gain by holding the text.
        try:
            p = subprocess.run([PY, "-u"] + argv, cwd=REPO, timeout=timeout)
            ok = p.returncode == 0
            note = "" if ok else f"exit {p.returncode}"
        except subprocess.TimeoutExpired:
            ok, note = False, f"timeout after {timeout}s"
        except Exception as e:
            ok, note = False, str(e)
        self.results.append((label, ok, time.time() - t0, note))
        return ok

    def summary(self):
        print("\n" + "=" * 62)
        print(f"{'stage':38} {'time':>8}  result")
        for label, ok, secs, note in self.results:
            state = "ok" if ok else f"FAILED ({note})"
            print(f"{label:38} {secs:>7.0f}s  {state}")
        bad = [r for r in self.results if not r[1]]
        print("=" * 62)
        print(f"{len(self.results) - len(bad)}/{len(self.results)} stages ok")
        return len(bad)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--date", help="COB date to ingest (default: yesterday)")
    ap.add_argument("--no-rebuild", action="store_true")
    ap.add_argument("--rebuild-only", action="store_true")
    ap.add_argument("--force-rebuild", action="store_true",
                    help="ignore the per-day cache and recompute everything")
    args = ap.parse_args()
    _check_recipes()

    now = datetime.now(timezone.utc)
    cob = (args.date or (now - timedelta(days=1)).strftime("%Y-%m-%d"))
    today = now.strftime("%Y-%m-%d")
    tip = (now - timedelta(days=2)).strftime("%Y-%m-%d")
    # GAP-AWARE: after a missed day, "yesterday..today" silently skips the
    # days in between. Stage HL from the last stored fill instead, so a
    # 2-day (or 2-week) gap is covered without anyone remembering to widen
    # the window by hand. Cheap when there is no gap: the same one day.
    hl_from = _last_fill_date("HYPERLIQUID") or cob
    if hl_from > cob:
        hl_from = cob
    gap_days = (datetime.strptime(today, "%Y-%m-%d")
                - datetime.strptime(hl_from, "%Y-%m-%d")).days
    since = min(hl_from, (now - timedelta(days=7)).strftime("%Y-%m-%d"))
    print(f"[cycle] {now:%Y-%m-%d %H:%M} UTC — COB {cob}, tip {today}")
    # a normal daily run has gap_days == 1 (newest fill = yesterday), so
    # anything beyond that IS a missed day and must be announced
    if gap_days > 1:
        print(f"[cycle] GAP: newest stored HL fill is {hl_from} — staging "
              f"{gap_days} days, and transfers back to {since}.\n"
              "  After a multi-day gap also cross-check ClickHouse for NEW "
              "symbols over the WHOLE gap\n  (BIN_UM_SYMBOLS / "
              "BIN_SPOT_SYMBOLS are hardcoded lists and fail silently).")

    c = Cycle()
    if not args.rebuild_only:
        # 1. Hyperliquid: the venue API retains only ~10k fills, so the tip is
        #    topped up from ClickHouse through the staged repair path.
        c.run("HL staged tip repair",
              ["staged_repair.py", "--tag", f"tip-{today}",
               "--stage-ch-hl", hl_from, today, "--verify", "--promote"])
        # 1b. REAL fees for the fills just staged from ClickHouse. CH has no
        #     fee column, so every CH-sourced row lands at fee 0 — ~131k rows
        #     and thousands of dollars of unrecorded cost accumulated before
        #     this ran. Pull the S3 day, then update fees in place and refold.
        c.run("HL S3 day pull",
              ["hl_s3_recover.py", "--workers", "8", "--dates", cob, today])
        c.run("HL fee update", ["hl_fee_backfill.py"])
        # 1c. funding, recorded rather than only fetched live (userFills'
        #     retention silently hid 1,338 fills; do not repeat that with
        #     funding). Excluded from the transfer sum in fetch_wallet_transfers
        #     so it cannot double-count against the live API figure.
        c.run("HL funding store", ["hl_funding_store.py", "--days", "3"])
        # 2. every venue's fills into trades_spot_avgcost (incremental)
        c.run("all-venue ingest",
              ["pnl_8041_daily.py", "--date", cob, "--ingest-only"])
        # 2b. Native self-heal: the streamer (primary, 8-min API window) can
        #     die silently — it did 07-30..08-03 and lost 4 days of QQQB to
        #     everywhere except ClickHouse. Top up any CH tx the store lacks
        #     (tx-level dedup makes this safe alongside the streamer) and
        #     WARN when the newest stored fill is stale.
        c.run("native CH top-up", ["native_ch_topup.py"])
        # 3. Robinhood chain fills land late; re-sweep the previous day
        c.run("robinhood late arrivals",
              ["rh_ch_repair.py",
               (datetime.strptime(cob, "%Y-%m-%d")
                - timedelta(days=1)).strftime("%Y-%m-%d")])
        # 4. on-chain transfer legs for the RFQ wallets (Blockscout walks)
        c.run("chain transfers",
              ["-c", "import chain_transfers as ct; print(ct.sync())"])
        # 4b. Dinari treasury transfers — DISABLED 2026-08-03, do not re-enable
        #     until dinari_transfers.py filters swap legs.
        #     hyperscan.com (the old source) stopped serving a Blockscout API,
        #     so this GoldRush replacement was written — but it records BOTH
        #     sides of Dinari's primary-market swaps as transfers. Its
        #     already-booked-as-fill guard never matches, because Dinari fills
        #     carry MO deal-ref ids (MFX...), not tx hashes.
        #     Effect when it ran: +449,843 USDC of phantom deposits and a
        #     NEGATIVE SPCX balance, against a live wallet holding ~0 USDC.
        #     Dinari snapshots are RECONSTRUCTED from this stream, so bad
        #     transfers corrupt the balances too — the only tell is the tip
        #     drift printed by dinari_goldrush_snaps.
        # c.run("dinari transfers (goldrush)", ["dinari_transfers.py"])
        # 4c. Paxos deposits/withdrawals (v2 /transfer/transfers). Paxos is a
        #     cash conduit — without these every movement is an unexplained
        #     break, and the in/out pairs get buried as timing artifacts.
        c.run("paxos transfers", ["paxos_transfers.py"])
        # 5. registry-driven snapshot jobs — SELF-owned accounts only
        for job in account_sources.jobs():
            for label, cmd in JOB_CMDS[job]:
                argv = [a.replace("{since}", since).replace("{tip}", tip)
                        for a in cmd]
                c.run(f"{job} {label}", argv)
        # 6. anything new appearing on an untracked account
        c.run("watchlist", ["account_watchlist.py"])
        # 6b. the GATE: qty-only hourly identity over the recent window — a
        #     fast "are the entries correct?" answer BEFORE the expensive
        #     board build. Exit 1 = day-level breaks exist; the cycle
        #     continues (the board shows them honestly), but the summary
        #     line is the tell that an ingest source needs fixing.
        c.run("entry check", ["recon_check.py", "--days", "3"])

    # 7. the control: every account's snapshot freshness AND coverage
    print("\n=== snapshot coverage ===", flush=True)
    stale = account_sources.check()
    lag = _ingest_lag()
    if lag > 1.5:
        print(f"\nWARNING: newest ingested fill is {lag:.1f}h behind the "
              "newest snapshot.\n  The open day WILL show large phantom "
              "breaks — balances moved on fills\n  the store does not have "
              "yet. This is ingest lag, not risk. Re-run\n  without "
              "--rebuild-only to clear it.")
    if stale:
        print(f"\n{len(stale)} account(s) need attention "
              "(rebuild continues — the board shows 'no snap' honestly)")

    if not args.no_rebuild:
        cmd = ["recon_dashboard.py", "--start", WINDOW_START, "--no-ingest"]
        if args.force_rebuild:
            cmd.append("--force")
        c.run("rebuild dashboard", cmd, timeout=28800)

    failed = c.summary()
    if stale:
        print(f"snapshot coverage: {len(stale)} account(s) stale/gappy")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
