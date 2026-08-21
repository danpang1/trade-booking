"""One registry of truth for how every 8041 dashboard account is fed.

Written after WALLET_CRB_EVM_04_ETHEREUM silently stopped snapshotting on
2026-07-29 and lost 57 hours before anyone noticed. The failure was not
technical — GoldRush worked fine — it was that each account's plumbing lived
in its own script and its own line of a hand-maintained .bat, so an account
could be dropped from the daily cycle and nothing would say so.

The distinction that matters here is OWNERSHIP:

  fill=SELF   we fetch these snapshots ourselves (GoldRush). If they go stale
              it is OUR bug and the daily cycle can fix it by running the job.
  fill=FEED   an external collector streams them (venue collectors into prod
              tq_hist_balance, the MO streamers, ClickHouse). We cannot repair
              these — but we must NOTICE, because a dead feed looks exactly
              like a quiet account on the board.

`check()` reports both and is the control that would have caught EVM_04.

  python account_sources.py            # coverage report, exit 1 if stale
  python account_sources.py --jobs     # just list the SELF-filled jobs
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

import avgcost_db

SELF, FEED = "SELF", "FEED"


@dataclass
class Src:
    snaps: str                 # human description of where balances come from
    owner: str                 # SELF (we fetch) | FEED (someone streams)
    store: str                 # which table/system check() must query
    inception: str             # first date the account can have data
    max_stale_h: int = 6       # alert threshold
    job: str = ""              # module to run when owner == SELF
    notes: str = ""


# store keys understood by check()
UAT = "uat.tq_hist_balance_mo"
PROD = "prod.tq_hist_balance"
PRODMO = "prodmo.tq_hist_balance_mo"
CH = "clickhouse.account_balance_snapshot"

SOURCES: dict[str, Src] = {
    "TK810@BINANCE_SPOT": Src(
        "venue collector", FEED, PROD, "2026-06-09"),
    "TK810@BINANCE_USDT_FUTURE": Src(
        "venue collector", FEED, PROD, "2026-06-09"),
    "TK810@BINANCE_PORTFOLIO_MARGIN": Src(
        "venue collector", FEED, PROD, "2026-06-09"),
    "TRADING_06@HYPERLIQUID_FUTURES": Src(
        "venue collector (+ tq_hist_position for unrealized)",
        FEED, PROD, "2026-06-09"),
    "TRADING_06@HYPERLIQUID_SPOT": Src(
        "venue collector", FEED, PROD, "2026-06-09"),
    "MOON-TOKKA@BITSTAMP_SPOT": Src(
        "MO streamer", FEED, PRODMO, "2026-06-23"),
    "MOON-TK@PAXOS_SPOT": Src(
        "ClickHouse account_balance_snapshot (217001)", FEED, CH,
        "2026-06-30",
        notes="custodian account, not a chain address — ClickHouse is the "
              "ONLY possible source; no GoldRush fallback exists"),
    "WALLET_CRB_EVM_02_ROBINHOOD": Src(
        "ClickHouse (460532), GoldRush overlay for assets the feed omits",
        FEED, CH, "2026-07-06",
        notes="GoldRush also backfills 06-29..07-06, before the feed existed"),
    "WALLET_CRB_EVM_05_ROBINHOOD": Src(
        "ClickHouse (489532)", FEED, CH, "2026-07-23"),
    "TRADING_01@NATIVECORE": Src(
        "MO streamer (side=short means owed)", FEED, UAT, "2026-06-10"),
    "WALLET_CRB_EVM_04_ETHEREUM": Src(
        "GoldRush balances-at-block", SELF, UAT, "2026-07-10",
        job="eth_goldrush_snaps",
        notes="no venue feed of any kind — absent from ClickHouse AND prod "
              "tq_hist_balance. Stranded 07-29..08-01 when the cycle set "
              "RECON_SKIP_GOLDRUSH=1 without an explicit job line."),
    "TOKKA_TREASURY_EVM_01_DINARI": Src(
        "RECONSTRUCTED forward from the transfer stream", SELF, UAT,
        "2026-06-12", job="dinari_goldrush_snaps",
        notes="NOT a balance read: GoldRush historical_balances 501s on "
              "hyperevm-mainnet, so balance(B) = sum of transfers before B. "
              "The hourly identity snap-delta = transfers therefore ties BY "
              "CONSTRUCTION — this column's zero breaks are NOT evidence of "
              "correctness. The only real check is ensure_snaps' drift "
              "report vs the live wallet. Transfers come from "
              "dinari_transfers.py (GoldRush); hyperscan.com stopped serving "
              "a Blockscout API 2026-08-03. Missing transfers hide silently "
              "here: 5 were found 2026-08-03, incl ~450k USDC on 06-16."),
    "WALLET_CRB_EVM_01_BSC": Src(
        "GoldRush balances-at-block", SELF, UAT, "2026-06-09",
        job="evm_custody_wallets"),
    "WALLET_CRB_EVM_02_ETHEREUM": Src(
        "GoldRush balances-at-block", SELF, UAT, "2026-06-24",
        job="evm_custody_wallets"),
    "WALLET_CRB_EVM_03_BSC": Src(
        "GoldRush balances-at-block", SELF, UAT, "2026-06-29",
        job="evm_custody_wallets"),
}


def _last_uat(names):
    conn = avgcost_db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT account_name, max(sync_ts),
                       count(DISTINCT date_trunc('hour',
                             sync_ts + interval '5 minutes'))
                FROM tq_hist_balance_mo WHERE account_name = ANY(%s)
                GROUP BY 1""", (list(names),))
            return {a: (t, n) for a, t, n in cur.fetchall()}
    finally:
        conn.close()


def _last_prod(names):
    import recon_dashboard as rd
    pg = rd._pg()
    try:
        cur = pg.cursor()
        cur.execute("""
            SELECT account_name, max(sync_ts),
                   count(DISTINCT date_trunc('hour',
                         sync_ts + interval '5 minutes'))
            FROM tq_hist_balance WHERE account_name = ANY(%s)
              AND sync_ts >= '2026-06-09'
            GROUP BY 1""", (list(names),))
        return {a: (t, n) for a, t, n in cur.fetchall()}
    finally:
        pg.close()


def _last_prodmo(names):
    import recon_dashboard as rd
    mo = rd._prod_mo()
    try:
        cur = mo.cursor()
        cur.execute("""
            SELECT max(sync_ts), count(DISTINCT date_trunc('hour',
                   sync_ts + interval '5 minutes'))
            FROM tq_hist_balance_mo
            WHERE account_name LIKE 'MOON-TOKKA@BITSTAMP%%'
              AND sync_ts >= '2026-06-09'""")
        t, n = cur.fetchone()
        return {names[0]: (t, n)} if t else {}
    finally:
        mo.close()


def _last_ch(names):
    import urllib.parse
    import recon_dashboard as rd
    quoted = ",".join("'" + a.replace("'", "''") + "'" for a in names)
    sql = (f"SELECT account_name, max(sync_ts), uniqExact(intDiv(sync_ts + "
           f"300000, 3600000)) FROM production.account_balance_snapshot "
           f"WHERE account_name IN ({quoted}) GROUP BY 1 FORMAT TSV")
    out = {}
    for line in rd._ch(sql).splitlines():
        a, ts, n = line.split("\t")
        out[a] = (datetime.utcfromtimestamp(int(ts) / 1000), int(n))
    return out


def check(verbose=True):
    """Per-account snapshot freshness. Returns list of (acct, hours_stale)."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    by_store: dict[str, list] = {}
    for a, s in SOURCES.items():
        by_store.setdefault(s.store, []).append(a)
    seen: dict[str, tuple] = {}
    for store, names in by_store.items():
        fn = {UAT: _last_uat, PROD: _last_prod, PRODMO: _last_prodmo,
              CH: _last_ch}[store]
        try:
            seen.update(fn(names))
        except Exception as e:
            print(f"  WARNING: {store} unreachable ({e})")
    stale = []
    if verbose:
        print(f"{'account':34} {'own':4} {'hours':>6} {'cov':>6} "
              f"{'last snap':>17} {'age':>7}  state")
    for a, s in SOURCES.items():
        last, n = seen.get(a, (None, 0))
        age = (now - last).total_seconds() / 3600 if last else None
        # coverage against hours ELAPSED SINCE INCEPTION, not since the window
        # start — otherwise a wallet that opened last week always looks broken.
        # Freshness alone misses a hole in the MIDDLE of history, which is
        # exactly the shape of the EVM_04 outage.
        born = datetime.strptime(s.inception, "%Y-%m-%d")
        want = max(1, int((now - born).total_seconds() // 3600))
        cov = 100.0 * n / want
        if age is None:
            state = "NO DATA"
        elif age > s.max_stale_h:
            state = "STALE" + (" (run job)" if s.owner == SELF
                               else " (feed down)")
        elif cov < 90:
            state = f"GAPPY ({want - n}h missing)"
        else:
            state = "ok"
        if state != "ok":
            stale.append((a, age))
        if verbose:
            print(f"{a:34} {s.owner:4} {n:>6} {cov:>5.0f}% "
                  f"{(str(last)[:16] if last else '-'):>17} "
                  f"{(f'{age:.1f}h' if age is not None else '-'):>7}  "
                  f"{state}")
    return stale


def jobs():
    """Modules to run each cycle to keep SELF-owned snapshots current."""
    out = []
    for s in SOURCES.values():
        if s.owner == SELF and s.job and s.job not in out:
            out.append(s.job)
    return out


if __name__ == "__main__":
    if "--jobs" in sys.argv:
        for j in jobs():
            print(j)
        sys.exit(0)
    bad = check()
    if bad:
        print(f"\n{len(bad)} account(s) need attention")
        sys.exit(1)
    print("\nall accounts fresh")
