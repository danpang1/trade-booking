"""Hourly trade-buildup vs balance-snapshot recon dashboard.

Reconciles, hour by hour, the position/cash build-up implied by our recorded
trades (trades_spot_avgcost) + venue flows (papi income, universal transfers,
sub-account transfers) against hourly balance snapshots, for:

    TK810@BINANCE_SPOT              (B-tokens + stables + BNB)   [tq_hist_balance]
    TK810@BINANCE_USDT_FUTURE       (UM perps + margin cash)     [tq_hist_balance]
    TK810@BINANCE_PORTFOLIO_MARGIN  (PM cash)                    [tq_hist_balance]
    MOON-TOKKA@BITSTAMP             (tokenized equities + USD)   [PROD MO DB
                                     tq_hist_balance_mo, acct ..@BITSTAMP_SPOT]

Bitstamp has NO transfer feed: token mints in / USD funding moves surface as
breaks in the hour they land (attributable, not noise). Its EOD position Break
is the day's INCREMENTAL unexplained (snap delta minus day fills) because
tokens transit the account (mint -> sell -> withdraw) and cumulative build vs
custody differs structurally. Equity marks via equity_marks.py (EOD-level).

Identity per hour window (window edges = the actual snap record_ts, so fills
racing a boundary land on the correct side):

    snap(h) - snap(h-1)  =  fills(h) + cash/pnl flows(h) + transfers(h)
                            [+ unrealized delta(h) for FUT margin cash --
                             the snapshot's UM cash figure includes unreal]

Anything unexplained is the hour's break, shown in qty and USD (hour-close
marks: ClickHouse production.midprice by default — last mid tick per hour,
one query for all symbols — with venue klines (fapi markPriceKlines / spot
klines) as fallback or via --marks venue; $1 stables).

Output: self-contained static HTML (embedded JSON, no server).

Usage:
    python recon_dashboard.py --days 4 [--out binance810_recon.html]
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path

import avgcost_db

REPO = Path(__file__).resolve().parent
ZERO = D("0")

BIN_SPOT = "TK810@BINANCE_SPOT"
BIN_FUT = "TK810@BINANCE_USDT_FUTURE"
BIN_PM = "TK810@BINANCE_PORTFOLIO_MARGIN"
BS_MOON = "MOON-TOKKA@BITSTAMP"
RH_ACCT = "WALLET_CRB_EVM_02_ROBINHOOD"
ETH_ACCT = "WALLET_CRB_EVM_04_ETHEREUM"
HL_FUT = "TRADING_06@HYPERLIQUID_FUTURES"
HL_SPOT = "TRADING_06@HYPERLIQUID_SPOT"
# Dinari primary-market treasury (HyperEVM). Pure custody column: its trades
# are already booked as venue=DINARI fills folded into the HL SPCXD leg, so
# this account carries NO fills — every chain movement is a transfer and the
# identity is snap-delta = transfers.
DIN_ACCT = "TOKKA_TREASURY_EVM_01_DINARI"
# Native Core: B-token/USDT spot legs from the canonical Native-API ingest;
# hourly snaps from our own streamer (UAT tq_hist_balance_mo). Credit-line
# top-ups are NOT ingested as transfers yet — they surface as USDT/USD
# balance breaks (classified, not hidden).
NAT_ACCT = "TRADING_01@NATIVECORE"
# second RH-chain RFQ wallet (GME MM, active 07-23+; refdata cross-check)
RH05_ACCT = "WALLET_CRB_EVM_05_ROBINHOOD"
# plain-custody CRB wallets (no trading — snap delta = transfers) and the
# dormant Paxos venue; all four added 2026-07-31 for full refdata coverage
EVM01_ACCT = "WALLET_CRB_EVM_01_BSC"
EVM02_ACCT = "WALLET_CRB_EVM_02_ETHEREUM"
EVM03_ACCT = "WALLET_CRB_EVM_03_BSC"
PAX_ACCT = "MOON-TK@PAXOS_SPOT"
CUSTODY_ACCTS = (EVM01_ACCT, EVM02_ACCT, EVM03_ACCT)
ACCOUNTS = (BIN_SPOT, BIN_FUT, BIN_PM, BS_MOON, PAX_ACCT, RH_ACCT, RH05_ACCT,
            ETH_ACCT, EVM01_ACCT, EVM02_ACCT, EVM03_ACCT,
            HL_FUT, HL_SPOT, DIN_ACCT, NAT_ACCT)
# column labels = the canonical account names as recorded in the Postgres
# snapshot refdata (tq_hist_balance / tq_hist_balance_mo account_name)
COL_LABEL = {a: a for a in ACCOUNTS}
COL_LABEL[BS_MOON] = "MOON-TOKKA@BITSTAMP_SPOT"
STORE_VENUES = ("BINANCE", "BITSTAMP", "ROBINHOOD", "ETHEREUM",
                "HYPERLIQUID", "NATIVE CORE", "PAXOS")
# cash asset(s) recon'd in the stables flow table, per account
# 2026-07-25 00:00 UTC: HL flipped xyz (HIP-3) funding from a daily 00:00
# reporting batch (accrues in position unrealized, NOT cash) to true hourly
# cash settlement (480 events/day). Before this instant xyz funding events
# must NOT be counted as expected cash — see the HL_FUT branch.
HL_XYZ_FUNDING_CASH_MS = 1784937600000

CASH_ASSETS = {BIN_SPOT: ("USDT", "USDC"), BIN_FUT: ("USDT", "USDC"),
               BIN_PM: ("USDT", "USDC"), BS_MOON: ("USD", "USDC", "USDG"),
               RH_ACCT: ("USDG",), RH05_ACCT: ("USDG",),
               ETH_ACCT: ("USDC", "USDT"),
               HL_FUT: ("USDC", "xyz:USDC"), HL_SPOT: ("USDC",),
               DIN_ACCT: ("USDC", "USDT0"), NAT_ACCT: ("USDT",),
               EVM01_ACCT: ("USDT", "USDC"), EVM02_ACCT: ("USDC", "USDT"),
               EVM03_ACCT: ("USDT", "USDC"),
               # Paxos holds all three: USD arrives (CUBIX_DEPOSIT), converts
               # to USDG/USDC, and leaves as CRYPTO_WITHDRAWAL. Listing only
               # USD left the other two out of the cash recon entirely.
               PAX_ACCT: ("USD", "USDC", "USDG")}
# perp accounts: positions move only via fills -> cumulative position recon
PERP_SUFFIX = {BIN_FUT: "@BINANCE_USDT_FUTURE",
               HL_FUT: "@HYPERLIQUID_FUTURES"}
# accounts whose snapshots may be absent (build-side still renders)
NO_SNAP_OK = (BS_MOON, RH_ACCT, RH05_ACCT, ETH_ACCT, DIN_ACCT, NAT_ACCT,
              PAX_ACCT) + CUSTODY_ACCTS
# crypto marks for non-equity RFQ bases: asset -> marks-dict key
CRYPTO_MARK = {"WETH": "ETH", "ETH": "ETH", "WBTC": "BTC", "CBBTC": "BTC",
               "HYPE": "HYPE", "BTC": "BTC"}


def hl_base(inst):
    """'xyz:AAPL-P/USD@HYPERLIQUID_FUTURES' -> 'AAPL'; 'HYPE-P/...' -> 'HYPE'."""
    return inst.split("-P/")[0].replace("xyz:", "")

# USD-eq break thresholds per asset row (abs): below OK, then warn, then bad
TH_OK = 1.0
TH_WARN = 50.0
TH_BAD = 500.0


def env(key):
    for line in (REPO / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return None


# ── signed venue GETs (same conventions as account_recon.py) ───────────
def _signed(base, path, params, timeout=25):
    k, s = env("810.BINANCE_API_KEY"), env("810.BINANCE_API_SECRET")
    p = dict(params)
    p["timestamp"] = int(time.time() * 1000)
    p["recvWindow"] = 60000
    qs = urllib.parse.urlencode(p)
    sig = hmac.new(s.encode(), qs.encode(), hashlib.sha256).hexdigest()
    return json.loads(urllib.request.urlopen(urllib.request.Request(
        base + path + "?" + qs + "&signature=" + sig,
        headers={"X-MBX-APIKEY": k}), timeout=timeout).read())


def _papi(path, params):
    return _signed("https://papi.binance.com", path, params)


def _sapi(path, params):
    return _signed("https://api.binance.com", path, params)


def _public(base, path, params):
    qs = urllib.parse.urlencode(params)
    return json.loads(urllib.request.urlopen(
        base + path + "?" + qs, timeout=20).read())


# ── postgres balance/position snapshots ────────────────────────────────
def _prod_mo():
    """PROD MO DB read-only (sg-ro-postgres) — `#PROD MO DB RO` block in
    nxgenmo/.env. Hosts tq_hist_balance_mo (Bitstamp Moon hourly snaps)."""
    import psycopg2
    envp = REPO.parent.parent / "nxgenmo" / ".env"
    creds, in_block = {}, False
    for ln in envp.read_text(encoding="utf-8", errors="replace").splitlines():
        st = ln.strip()
        if st.startswith("#") and "PROD MO DB RO" in st.upper():
            in_block = True
            continue
        if not in_block:
            continue
        if st.startswith("#"):
            break
        if not st:
            continue
        idxs = [i for i in (st.find(":"), st.find("=")) if i >= 0]
        i = min(idxs)
        creds[st[:i].strip().upper()] = st[i + 1:].strip().strip('"')
    return psycopg2.connect(
        host=creds["MO_DB_HOST"], port=int(creds.get("MO_DB_PORT", "5432")),
        dbname=creds["MO_DB_DATABASE"], user=creds["MO_DB_USERNAME"],
        password=creds["MO_DB_PASSWORD"], connect_timeout=15)


def _pg():
    import psycopg2
    from pg import PG_HOST, PG_PORT, PG_USER, PG_PASS, PG_DB
    return psycopg2.connect(host=PG_HOST, port=PG_PORT, user=PG_USER,
                            password=PG_PASS, database=PG_DB, connect_timeout=15)


def fetch_snaps(t0, t1):
    """{account: {hour_iso: {'ts': epoch_ms, 'bal': {inst: signed_qty}}}}.

    A snap batch fired at H:59 represents end-of-hour H — but the streamer
    sometimes lands seconds late (H+1:00:0x), so bucketing subtracts 5 minutes
    first. If several batches land in one bucket the LAST one wins.
    """
    pg = _pg()
    out = {a: {} for a in ACCOUNTS}
    try:
        cur = pg.cursor()
        cur.execute("""
            SELECT account_name, instrument, instrument_type, side, total_qty,
                   sync_ts
            FROM tq_hist_balance
            WHERE (account_name = ANY(%s)
                   OR account_name LIKE 'MOON-TOKKA@BITSTAMP%%')
              AND sync_ts >= %s AND sync_ts < %s
            ORDER BY account_name, sync_ts
        """, (list(ACCOUNTS), t0, t1))
        batches = defaultdict(dict)   # (acct, hour) -> {sync_ts: {inst: qty}}
        for a, inst, it, side, q, ts in cur.fetchall():
            if a.startswith(BS_MOON):
                a = BS_MOON
            sq = D(str(q))
            if "PERP" in str(it or "").upper() and (side or "").lower() == "short":
                sq = -abs(sq)
            hour = (ts - timedelta(minutes=5)).replace(minute=0, second=0,
                                                       microsecond=0)
            batches[(a, hour)].setdefault(ts, {})[inst] = \
                batches[(a, hour)].get(ts, {}).get(inst, ZERO) + sq
        for (a, hour), by_ts in batches.items():
            ts = max(by_ts)
            bal = dict(by_ts[ts])
            # a snap batch can FRACTURE across two writes seconds apart
            # (07-17 03:00: 13+9 rows instead of 22) — last-wins then reads
            # the missing instruments as position 0 and fabricates giant
            # reversing TIMING pairs. Fill instruments absent from the chosen
            # batch from the next-most-recent batch in the same hour bucket.
            for ots in sorted(by_ts, reverse=True):
                if ots == ts:
                    continue
                for inst, q in by_ts[ots].items():
                    bal.setdefault(inst, q)
            out[a][hour.isoformat()] = {
                "ts": int(ts.replace(tzinfo=timezone.utc).timestamp() * 1000),
                "bal": bal,
                "src": "postgres · tq_hist_balance (official feed)"}
    finally:
        pg.close()

    # Accounts whose OFFICIAL hourly snapshot feed is ClickHouse
    # production.account_balance_snapshot (hourly at :00, plain-symbol
    # instruments, sync_ts in ms). These are free and authoritative — always
    # prefer them over a GoldRush reconstruction:
    #   WALLET_CRB_EVM_02_ROBINHOOD  460532  since 2026-07-06
    #   WALLET_CRB_EVM_05_ROBINHOOD  489532  since 2026-07-23
    #   MOON-TK@PAXOS_SPOT           217001  since 2026-06-30 (USD/USDG/USDC)
    # Paxos has NO other feed at all — it is absent from prod tq_hist_balance
    # and from GoldRush (it is a custodian account, not a chain address), so
    # without this branch the column is permanently empty.
    # The UAT streamer branch below only fills gaps these leave.
    try:
        t0_ms = int(t0.replace(tzinfo=timezone.utc).timestamp() * 1000)
        t1_ms = int(t1.replace(tzinfo=timezone.utc).timestamp() * 1000)
        ch_accts = [RH_ACCT, RH05_ACCT, PAX_ACCT]
        names = ",".join("'" + a.replace("'", "''") + "'" for a in ch_accts)
        sql = f"""
            SELECT account_name, instrument, side, toString(total_qty), sync_ts
            FROM production.account_balance_snapshot
            WHERE account_name IN ({names})
              AND sync_ts >= {t0_ms} AND sync_ts < {t1_ms}
            ORDER BY sync_ts
            FORMAT TSV"""
        cbatches = defaultdict(dict)
        for line in _ch(sql).splitlines():
            acct, inst, side, q, ts_ms = line.split("\t")
            sq = D(q)
            if side.lower() == "short":
                sq = -abs(sq)
            ts = datetime.utcfromtimestamp(int(ts_ms) / 1000)
            hour = (ts - timedelta(minutes=5)).replace(minute=0, second=0,
                                                       microsecond=0)
            b = cbatches[(acct, hour)].setdefault(ts, {})
            b[inst] = b.get(inst, ZERO) + sq
        got = defaultdict(int)
        for (acct, hour), by_ts in cbatches.items():
            ts = max(by_ts)
            out[acct][hour.isoformat()] = {
                "ts": int(ts.replace(tzinfo=timezone.utc).timestamp() * 1000),
                "bal": by_ts[ts],
                "src": "clickhouse · account_balance_snapshot"}
            got[acct] += 1
        print("[recon] CH snaps: " + ", ".join(
            f"{a.split('@')[0]}={got[a]}h" for a in ch_accts))
    except Exception as e:
        print(f"[recon] WARNING: ClickHouse snaps failed ({e})")

    # Interim fallback: hourly snaps from UAT tq_hist_balance_mo (our own
    # stream_robinhood_balance.py collector; instrument "{SYM}@ROBINHOOD").
    try:
        conn = avgcost_db.connect()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT account_name, instrument, total_qty, sync_ts, side
                    FROM tq_hist_balance_mo
                    WHERE account_name = ANY(%s)
                      AND sync_ts >= %s AND sync_ts < %s
                    ORDER BY sync_ts
                """, ([RH_ACCT, RH05_ACCT, ETH_ACCT, DIN_ACCT, NAT_ACCT]
                      + list(CUSTODY_ACCTS), t0, t1))
                rbatches = defaultdict(dict)
                for acct_name, inst, q, ts, side in cur.fetchall():
                    asset = inst.split("@")[0]
                    if acct_name == NAT_ACCT and asset == "USD":
                        # venue-computed credit-line valuation (~100k figure
                        # oscillating with marks), not a custody balance —
                        # unreconcilable by flows, excluded from the column
                        continue
                    if acct_name == ETH_ACCT and asset == "WETH":
                        asset = "ETH"        # leg folds WETH+native ETH
                    sq = D(str(q))
                    # Native streamer signs balances via side: short = owed
                    # USDT / short B-token inventory (RH/ETH are always long)
                    if (side or "").lower() == "short":
                        sq = -abs(sq)
                    hour = (ts - timedelta(minutes=5)).replace(
                        minute=0, second=0, microsecond=0)
                    b = rbatches[(acct_name, hour)].setdefault(ts, {})
                    b[asset] = b.get(asset, ZERO) + sq
                for (acct_name, hour), by_ts in rbatches.items():
                    ts = max(by_ts)
                    hour_iso = hour.isoformat()
                    if hour_iso in out[acct_name]:
                        # official feed hour exists — OVERLAY any asset it
                        # does not carry at all (e.g. WETH: absent from the
                        # ClickHouse snapshot feed, filled from GoldRush)
                        cell = out[acct_name][hour_iso]
                        added = [a2 for a2, q2 in by_ts[ts].items()
                                 if a2 not in cell["bal"]]
                        for a2 in added:
                            cell["bal"][a2] = by_ts[ts][a2]
                        if added and "goldrush" not in cell["src"]:
                            cell["src"] += (" + " + "/".join(sorted(added))
                                            + ": goldrush balances-at-block")
                        continue
                    out[acct_name][hour_iso] = {
                        "ts": int(ts.replace(tzinfo=timezone.utc)
                                  .timestamp() * 1000),
                        "bal": by_ts[ts],
                        "src": ("reconstructed · live GoldRush anchor − "
                                "Σ chain transfers (UAT)"
                                if acct_name == DIN_ACCT else
                                "native streamer · tq_hist_balance_mo (UAT)"
                                if acct_name == NAT_ACCT else
                                "goldrush balances-at-block · "
                                "tq_hist_balance_mo (UAT)")}
        finally:
            conn.close()
    except Exception as e:
        print(f"[recon] WARNING: Robinhood snaps unavailable ({e})")

    # Bitstamp Moon: hourly snaps live in PROD MO DB tq_hist_balance_mo
    # (account MOON-TOKKA@BITSTAMP_SPOT, instrument "{X}@BITSTAMP_SPOT").
    try:
        mo = _prod_mo()
    except Exception as e:
        print(f"[recon] WARNING: PROD MO DB unreachable ({e}) — "
              "Bitstamp snaps skipped")
        return out
    try:
        cur = mo.cursor()
        cur.execute("""
            SELECT instrument, side, total_qty, sync_ts
            FROM tq_hist_balance_mo
            WHERE account_name LIKE 'MOON-TOKKA@BITSTAMP%%'
              AND sync_ts >= %s AND sync_ts < %s
            ORDER BY sync_ts
        """, (t0, t1))
        bbatches = defaultdict(dict)
        for inst, side, q, ts in cur.fetchall():
            asset = inst.split("@")[0]
            sq = D(str(q))
            if (side or "").lower() == "short":
                sq = -abs(sq)
            hour = (ts - timedelta(minutes=5)).replace(minute=0, second=0,
                                                       microsecond=0)
            bbatches[hour].setdefault(ts, {})[asset] =                 bbatches[hour].get(ts, {}).get(asset, ZERO) + sq
        for hour, by_ts in bbatches.items():
            ts = max(by_ts)
            out[BS_MOON][hour.isoformat()] = {
                "ts": int(ts.replace(tzinfo=timezone.utc).timestamp() * 1000),
                "bal": by_ts[ts],
                "src": "postgres · tq_hist_balance_mo (PROD MO DB)"}
    finally:
        mo.close()
    return out


def fetch_unreal(t0, t1):
    """{acct: {hour_iso: {margin_asset: sum unsettled_pnl}}} for the perp
    accounts — their cash snapshots include unrealized, so hourly deltas must
    be offset by the position snapshot's unsettled_pnl delta. Margin asset:
    Binance by quote (/USDC@ vs USDT), Hyperliquid by dex pool (xyz: prefix)."""
    pg = _pg()
    out = {a: defaultdict(lambda: defaultdict(lambda: ZERO))
           for a in PERP_SUFFIX}
    try:
        cur = pg.cursor()
        cur.execute("""
            SELECT account_name, instrument, unsettled_pnl, sync_ts
            FROM tq_hist_position
            WHERE account_name = ANY(%s) AND sync_ts >= %s AND sync_ts < %s
        """, (list(PERP_SUFFIX), t0, t1))
        batches = defaultdict(dict)   # (acct, hour) -> {sync_ts: {inst: pnl}}
        for acct, inst, u, ts in cur.fetchall():
            hour = (ts - timedelta(minutes=5)).replace(minute=0, second=0,
                                                       microsecond=0)
            batches[(acct, hour)].setdefault(ts, {})[inst] = D(str(u or 0))
        for (acct, hour), by_ts in batches.items():
            ts = max(by_ts)
            merged = dict(by_ts[ts])
            # same fractured-batch guard as fetch_snaps: a partial position
            # batch would drop instruments' unsettled_pnl from the pool sum
            for ots in sorted(by_ts, reverse=True):
                if ots == ts:
                    continue
                for inst, u in by_ts[ots].items():
                    merged.setdefault(inst, u)
            for inst, u in merged.items():
                if acct == HL_FUT:
                    asset = "xyz:USDC" if inst.startswith("xyz:") else "USDC"
                else:
                    asset = "USDC" if "/USDC@" in inst else "USDT"
                out[acct][hour.isoformat()][asset] += u
    finally:
        pg.close()
    return out


# ── our recorded trades (the book being reconciled) ────────────────────
def fetch_store_fills(t0, t1):
    """Store fills for the window: perp legs (qty only — perp cash moves via
    income) and spot legs (qty + quote cash + commission legs)."""
    conn = avgcost_db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT instrument, direction, base_amount, price,
                       fee_asset, fee_amount, realized, trade_date, venue,
                       account
                FROM trades_spot_avgcost
                WHERE venue = ANY(%s) AND trade_date >= %s AND trade_date < %s
                ORDER BY trade_date
            """, (list(STORE_VENUES), t0, t1))
            rows = cur.fetchall()
    finally:
        conn.close()
    fills = []
    for inst, direction, qty, px, fa, fee, realized, td, venue, acct in rows:
        sq = D(str(qty)) * (D(1) if direction == "LONG" else D(-1))
        fills.append({"inst": inst, "qty": sq, "px": D(str(px)),
                      "fee_asset": fa, "fee": D(str(fee or 0)),
                      "realized": D(str(realized or 0)),
                      "venue": venue, "account": acct,
                      "t": int(td.timestamp() * 1000)})
    return fills


def fetch_wallet_transfers(t0, t1):
    """Transfer activity for every account with a venue_transfers feed:
    {account: [{'t': ms, 'asset', 'qty'}]} signed +in/-out. Rows tagged
    FUNDING rows are excluded too: hl_funding_store.py records them for
    durability (the venue endpoint could grow a retention limit the way
    userFills did), but the HL_FUT branch already adds funding from the LIVE
    API into `cash`. Counting the stored copy as a transfer as well would
    double it.
    SETTLEMENT_BOOKED are excluded — their acquisition is already booked as
    cost-basis fills, counting both would double-explain."""
    conn = avgcost_db.connect()
    out = {}
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT account, asset, qty, event_time, transfer_type
                FROM venue_transfers
                WHERE account = ANY(%s)
                  AND COALESCE(transfer_type, '')
                      NOT IN ('SETTLEMENT_BOOKED', 'FUNDING')
                  AND event_time >= %s AND event_time < %s
            """, ([BS_MOON, RH_ACCT, RH05_ACCT, ETH_ACCT, HL_FUT, HL_SPOT,
                   DIN_ACCT, NAT_ACCT, PAX_ACCT]
                  + list(CUSTODY_ACCTS), t0, t1))
            for acct, a, q, ts, ty in cur.fetchall():
                if acct == ETH_ACCT and a in ("WETH", "ETH-NATIVE"):
                    a = "ETH"
                out.setdefault(acct, []).append(
                    {"asset": a, "qty": D(str(q)),
                     "t": int(ts.timestamp() * 1000),
                     "type": ty or ""})
        return out
    finally:
        conn.close()


def fetch_latest_positions(as_of_ms):
    """Memoized avg-cost state per Binance leg AS OF a snapshot instant:
    {instrument: {'qty', 'avg', 'last_trade'}}. Trades newer than the snap
    must not enter the build or the comparison shows phantom drift."""
    as_of = datetime.fromtimestamp(as_of_ms / 1000, tz=timezone.utc)
    conn = avgcost_db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT ON (instrument)
                       instrument, pos_qty_after, avg_cost_after, trade_date
                FROM trades_spot_avgcost
                WHERE venue = ANY(%s) AND trade_date <= %s
                ORDER BY instrument, trade_date DESC, id DESC
            """, (list(STORE_VENUES), as_of))
            return {inst: {"qty": D(str(q or 0)), "avg": D(str(a or 0)),
                           "last_trade": td.isoformat()}
                    for inst, q, a, td in cur.fetchall()}
    finally:
        conn.close()


def store_instruments_ever():
    conn = avgcost_db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT instrument FROM trades_spot_avgcost "
                        "WHERE venue = ANY(%s)", (list(STORE_VENUES),))
            return {r[0] for r in cur.fetchall()}
    finally:
        conn.close()


# ── venue flows ────────────────────────────────────────────────────────
def fetch_income(w0, w1):
    """papi UM income rows in [w0, w1) ms: [{'t', 'asset', 'type', 'amt'}].

    A full 1,000-row page can cut MID-MILLISECOND (fill bursts share one ms
    timestamp; commissions land per fill) — stepping past max(time) silently
    drops that ms's remaining rows (undercounted 07-10 10:00 commissions by
    ~$289, found 2026-07-30). The boundary ms is re-fetched and rows deduped
    by (tranId, type, symbol, time, amount)."""
    rows, cur, seen = [], w0, set()
    while True:
        b = _papi("/papi/v1/um/income",
                  {"startTime": cur, "endTime": w1, "limit": 1000})
        if not b:
            break
        fresh = 0
        for r in b:
            k = (r.get("tranId"), str(r.get("incomeType")),
                 str(r.get("symbol")), int(r["time"]), str(r["income"]))
            if k in seen:
                continue
            seen.add(k)
            rows.append(r)
            fresh += 1
        if len(b) < 1000:
            break
        mx = max(int(r["time"]) for r in b)
        if mx > cur and fresh:
            cur = mx              # re-fetch the boundary ms in full
        else:
            cur = mx + 1          # single-ms page / all dupes: step past
    return [{"t": int(r["time"]), "asset": str(r.get("asset")),
             "type": str(r.get("incomeType", "")).upper(),
             "amt": D(str(r["income"]))}
            for r in rows if w0 <= int(r["time"]) < w1]


def fetch_uni_transfers(w0, w1):
    """Universal transfers touching MAIN/PM/FUNDING, all assets, deduped by
    tranId: [{'t', 'asset', 'wallet_deltas': {MAIN: ±, PORTFOLIO_MARGIN: ±}}]."""
    PAIRS = [("MAIN_PORTFOLIO_MARGIN", "MAIN", "PORTFOLIO_MARGIN"),
             ("PORTFOLIO_MARGIN_MAIN", "PORTFOLIO_MARGIN", "MAIN"),
             ("MAIN_FUNDING", "MAIN", "FUNDING"),
             ("FUNDING_MAIN", "FUNDING", "MAIN")]
    out, seen = [], set()
    for t, frm, to in PAIRS:
        try:
            r = _sapi("/sapi/v1/asset/transfer",
                      {"type": t, "startTime": w0, "endTime": w1, "size": 100})
        except Exception:
            continue
        for x in (r.get("rows", []) if isinstance(r, dict) else r):
            if x.get("tranId") in seen:
                continue
            seen.add(x.get("tranId"))
            amt = D(str(x["amount"]))
            out.append({"t": int(x["timestamp"]), "asset": str(x["asset"]),
                        "deltas": {frm: -amt, to: amt}})
    return out


def fetch_sub_transfers(w0, w1):
    """Master<->sub transfers into/out of the sub's SPOT wallet, per asset:
    [{'t', 'asset', 'qty'}] (+in / -out)."""
    out = []
    for ty, sign in ((1, D(1)), (2, D(-1))):
        try:
            r = _sapi("/sapi/v1/sub-account/transfer/subUserHistory",
                      {"type": ty, "startTime": w0, "endTime": w1, "limit": 500})
        except Exception:
            continue
        for x in (r if isinstance(r, list) else r.get("rows", [])):
            wallet = x.get("toAccountType") if ty == 1 else x.get("fromAccountType")
            if wallet == "SPOT":
                out.append({"t": int(x["time"]), "asset": str(x.get("asset")),
                            "qty": sign * D(str(x["qty"]))})
    return out


def fetch_chain_deposits(w0, w1):
    """On-chain deposits (+) and withdrawals (-) of the SPOT wallet:
    [{'t', 'asset', 'qty'}]. Found 2026-07-30: a 99,999.8 USDC Arbitrum
    deposit (07-06 06:12, HL->Binance funding leg) was invisible to
    uni/sub transfer endpoints and stood as a +100k recon break. Both
    endpoints cap the query range at 90 days — chunked."""
    out = []
    CHUNK = 80 * 24 * 3600 * 1000
    lo = w0
    while lo < w1:
        hi = min(lo + CHUNK, w1)
        try:
            for x in _sapi("/sapi/v1/capital/deposit/hisrec",
                           {"startTime": lo, "endTime": hi, "limit": 1000}):
                if int(x.get("status", 0)) == 1:
                    out.append({"t": int(x.get("completeTime")
                                         or x["insertTime"]),
                                "asset": str(x["coin"]),
                                "qty": D(str(x["amount"]))})
        except Exception as e:
            print(f"[recon] WARNING: deposit history failed ({e})")
        try:
            for x in _sapi("/sapi/v1/capital/withdraw/history",
                           {"startTime": lo, "endTime": hi, "limit": 1000}):
                if int(x.get("status", -1)) == 6:      # 6 = completed
                    amt = D(str(x["amount"])) + D(str(x.get(
                        "transactionFee", 0) or 0))
                    out.append({"t": int(datetime.strptime(
                        x["completeTime"], "%Y-%m-%d %H:%M:%S")
                        .replace(tzinfo=timezone.utc).timestamp() * 1000)
                        if isinstance(x.get("completeTime"), str)
                        else int(x.get("applyTime", 0)),
                        "asset": str(x["coin"]), "qty": -amt})
        except Exception as e:
            print(f"[recon] WARNING: withdraw history failed ({e})")
        lo = hi
    return out


def fetch_pm_interest(w0, w1):
    """PM negative-balance interest rows: [{'t', 'asset', 'amt'}] (amt < 0 =
    interest charged). Endpoint may be absent for some accounts — best effort."""
    try:
        r = _papi("/papi/v1/portfolio/interest-history",
                  {"startTime": w0, "endTime": w1, "size": 100})
    except Exception:
        return []
    rows = r if isinstance(r, list) else r.get("rows", [])
    out = []
    for x in rows:
        t = (x.get("interestAccuredTime") or x.get("interestAccruedTime")
             or x.get("time"))
        if t is None or "interest" not in x:
            continue
        out.append({"t": int(t), "asset": str(x.get("asset", "USDT")),
                    "amt": -D(str(x["interest"]))})
    return out


# ── hourly marks ───────────────────────────────────────────────────────
CH_URL = ("https://jp-clickhouse-api.internal.tokkalabs.com:443/"
          "?user=prod_ro&password=scCtp%21Ez8%233h%23LK8")


def _ch(sql):
    req = urllib.request.Request(CH_URL, data=sql.encode())
    return urllib.request.urlopen(req, timeout=30).read().decode()


def fetch_marks_ch(perp_syms, spot_assets, w0, w1):
    """Hourly marks from ClickHouse production.midprice (order-book mid, all
    venues' collectors): hour close = last mid tick of each hour. Same dict
    shape as fetch_marks: {key: {hour_open_ms: close}}, key = UM symbol for
    perps / snapshot asset for spot. ts_first_seen is in MICROseconds."""
    spot_sym = {("ETHUSDC" if a == "ETH" else a + "USDT"): a
                for a in spot_assets if a not in ("USDT", "USDC")}
    linear = sorted(perp_syms)
    syms = sorted(set(linear) | set(spot_sym))
    if not syms:
        return {}
    in_list = ",".join(f"'{s}'" for s in syms)
    sql = f"""
        SELECT exchange, raw_symbol,
               toUnixTimestamp(toStartOfHour(
                   toDateTime(intDiv(ts_first_seen, 1000000)))) * 1000 AS h,
               toFloat64(argMax((best_bid + best_ask) / 2, ts_first_seen)) AS px
        FROM production.midprice
        WHERE exchange IN ('binance-linear', 'binance-spot')
          AND raw_symbol IN ({in_list})
          AND ts_first_seen >= {w0 * 1000} AND ts_first_seen < {w1 * 1000}
        GROUP BY exchange, raw_symbol, h
        FORMAT TSV"""
    marks = defaultdict(dict)
    for line in _ch(sql).splitlines():
        exch, sym, h, px = line.split("\t")
        if exch == "binance-linear" and sym in perp_syms:
            marks[sym][int(h)] = float(px)
        elif exch == "binance-spot" and sym in spot_sym:
            marks[spot_sym[sym]][int(h)] = float(px)
    return dict(marks)


def _klines(base, path, symbol, w0, w1):
    out, cur = {}, w0
    while cur < w1:
        try:
            b = _public(base, path, {"symbol": symbol, "interval": "1h",
                                     "startTime": cur, "endTime": w1,
                                     "limit": 500})
        except Exception:
            return out
        if not b:
            break
        for k in b:
            out[int(k[0])] = float(k[4])          # open-time -> close
        last = int(b[-1][0])
        if len(b) < 500 or last + 3600_000 >= w1:
            break
        cur = last + 3600_000
    return out


def fetch_marks(perp_syms, spot_assets, w0, w1, source="clickhouse"):
    """{key: {hour_open_ms: close}} — key = UM symbol or spot asset.

    source='clickhouse' (default): production.midprice hourly closes, one
    query for all symbols; any symbol CH lacks falls back to venue klines.
    source='venue': fapi markPriceKlines (perps) / spot klines directly."""
    marks = {}
    if source == "clickhouse":
        try:
            marks = fetch_marks_ch(perp_syms, spot_assets, w0, w1)
        except Exception as e:
            print(f"[recon] WARNING: ClickHouse marks failed ({e}) — "
                  "falling back to venue klines")
    for sym in sorted(perp_syms):
        if not marks.get(sym):
            marks[sym] = _klines("https://fapi.binance.com",
                                 "/fapi/v1/markPriceKlines", sym, w0, w1)
    for a in sorted(spot_assets):
        if a in ("USDT", "USDC") or marks.get(a):
            continue
        sym = "ETHUSDC" if a == "ETH" else a + "USDT"
        marks[a] = _klines("https://api.binance.com", "/api/v3/klines",
                           sym, w0, w1)
    return marks


def mark_at(marks, key, hour_ms):
    if key in ("USDT", "USDC"):
        return 1.0
    m = marks.get(key) or {}
    if hour_ms in m:
        return m[hour_ms]
    older = [t for t in m if t <= hour_ms]
    return m[max(older)] if older else 0.0


# ── recon engine ───────────────────────────────────────────────────────
def _slice(rows, w0, w1):
    return [r for r in rows if w0 <= r["t"] < w1]


def _expected_for(acct, w0, w1, fills, income, uni, sub, pm_int,
                  bs_xf=(), hl_fills=(), hl_fund=()):
    """{asset_key: {'fills', 'cash', 'transfers'}} expected deltas for one
    account over one window. asset_key = snapshot instrument label."""
    ex = defaultdict(lambda: {"fills": ZERO, "cash": ZERO, "transfers": ZERO})

    if acct == BIN_FUT:
        for f in _slice(fills, w0, w1):
            if f["inst"].endswith("@BINANCE_USDT_FUTURE"):
                ex[f["inst"]]["fills"] += f["qty"]
        for r in _slice(income, w0, w1):
            slot = "transfers" if "TRANSFER" in r["type"] else "cash"
            ex[r["asset"]][slot] += r["amt"]

    elif acct == BIN_SPOT:
        for f in _slice(fills, w0, w1):
            # cross-leg fold: fills booked on another account's leg but
            # EXECUTED on Binance (venue tag) settled their cash HERE —
            # e.g. the 07-10 ETHUSDC buys folded into ETH/USDC@ETHEREUM_RFQ
            # as cost basis (their USDC left the Binance spot wallet)
            if (f.get("venue") == "BINANCE"
                    and not f["inst"].endswith("@BINANCE_SPOT")
                    and not f["inst"].endswith("@BINANCE_USDT_FUTURE")):
                base, quote = f["inst"].split("@")[0].split("/")
                # BOTH legs transited Binance: the base arrived from the
                # trade (its exit is the recorded on-chain withdrawal), the
                # quote cash left the spot wallet
                ex[base]["fills"] += f["qty"]
                ex[quote]["cash"] -= f["qty"] * f["px"] + f["fee"]
                continue
            if not f["inst"].endswith("@BINANCE_SPOT"):
                continue
            base, quote = f["inst"].split("@")[0].split("/")
            ex[base]["fills"] += f["qty"]
            ex[quote]["cash"] -= f["qty"] * f["px"]
            if f["fee"]:
                if f["fee_asset"] == base:
                    ex[base]["cash"] -= f["fee"]
                elif f["fee_asset"] == quote:
                    ex[quote]["cash"] -= f["fee"]
                elif f["fee_asset"]:
                    ex[f["fee_asset"]]["cash"] -= f["fee"]
        for r in _slice(uni, w0, w1):
            d = r["deltas"].get("MAIN")
            if d:
                ex[r["asset"]]["transfers"] += d
        for r in _slice(sub, w0, w1):
            ex[r["asset"]]["transfers"] += r["qty"]

    elif acct == BIN_PM:
        for r in _slice(uni, w0, w1):
            d = r["deltas"].get("PORTFOLIO_MARGIN")
            if d:
                ex[r["asset"]]["transfers"] += d
        # UM income TRANSFER moves cash UM<->PM: +into UM = -out of PM
        for r in _slice(income, w0, w1):
            if "TRANSFER" in r["type"]:
                ex[r["asset"]]["transfers"] -= r["amt"]
        for r in _slice(pm_int, w0, w1):
            ex[r["asset"]]["cash"] += r["amt"]

    elif acct in (RH_ACCT, RH05_ACCT):
        for f in _slice(fills, w0, w1):
            # two RH-chain wallets share the @ROBINHOOD instrument suffix —
            # fills are scoped to their own account's column
            if (not f["inst"].endswith("@ROBINHOOD")
                    or f.get("account") != acct):
                continue
            base, quote = f["inst"].split("@")[0].split("/")
            ex[base]["fills"] += f["qty"]
            ex[quote]["cash"] -= f["qty"] * f["px"]
        for r in _slice(bs_xf.get(acct, []), w0, w1):
            ex[r["asset"]]["transfers"] += r["qty"]

    elif acct in CUSTODY_ACCTS:
        # plain custody: no trading on these wallets, every move is a transfer
        for r in _slice(bs_xf.get(acct, []), w0, w1):
            ex[r["asset"]]["transfers"] += r["qty"]

    elif acct == PAX_ACCT:
        for f in _slice(fills, w0, w1):
            if not f["inst"].endswith("@PAXOS"):
                continue
            base, quote = f["inst"].split("@")[0].split("/")
            ex[base]["fills"] += f["qty"]
            ex[quote]["cash"] -= f["qty"] * f["px"] + f["fee"]
        # Paxos is a CASH CONDUIT: USD in (CUBIX_DEPOSIT) -> convert -> USDG
        # out (CRYPTO_WITHDRAWAL) to our own Robinhood wallet, all within the
        # hour. Without these rows every movement broke, and because the pairs
        # cancel, _tag_snap_gaps buried ~$2.3M of real flow as "timing".
        for r in _slice(bs_xf.get(PAX_ACCT, []), w0, w1):
            # stablecoin CONVERSIONS are trades (sell USD / buy USDG), not
            # movements in or out — classify their legs as FILLS so the cell
            # reads like the swap it is; deposits/withdrawals stay transfers
            slot = ("fills" if r.get("type") == "CONVERSION"
                    else "transfers")
            ex[r["asset"]][slot] += r["qty"]

    elif acct == DIN_ACCT:
        # pure custody: no fills (trades live on the HL SPCXD fold) — every
        # chain movement incl. SPCX<->SPCX.dw wraps arrives as transfers
        for r in _slice(bs_xf.get(DIN_ACCT, []), w0, w1):
            ex[r["asset"]]["transfers"] += r["qty"]

    elif acct == NAT_ACCT:
        # withdrawals/deposits between Native and our own BSC wallet
        # (WALLET_CRB_EVM_03) — booked from the chain walk, timestamped to
        # the Native-side snapshot window
        for r in _slice(bs_xf.get(NAT_ACCT, []), w0, w1):
            ex[r["asset"]]["transfers"] += r["qty"]
        # B-token/USDT spot legs; fees settle in USDT or in-kind (base)
        for f in _slice(fills, w0, w1):
            if not f["inst"].endswith("@NATIVECORE"):
                continue
            base, quote = f["inst"].split("@")[0].split("/")
            ex[base]["fills"] += f["qty"]
            ex[quote]["cash"] -= f["qty"] * f["px"]
            if f["fee"]:
                if f["fee_asset"] == base:
                    ex[base]["cash"] -= f["fee"]
                elif f["fee_asset"] == quote:
                    ex[quote]["cash"] -= f["fee"]
                elif f["fee_asset"]:
                    ex[f["fee_asset"]]["cash"] -= f["fee"]

    elif acct == HL_FUT:
        # perp qty from store fills; pool cash = engine realized - fees from
        # the STORE (complete history — the venue fills API only retains the
        # most recent ~10k fills, so it is blank beyond ~a day and every
        # earlier hour would lose its realized/fee cash) + funding (venue
        # API, full history) + transfers (venue_transfers). HL uses
        # avg-entry-price accounting, same basis as the store's engine.
        for f in _slice(fills, w0, w1):
            if f["inst"].endswith("@HYPERLIQUID_FUTURES"):
                ex[f["inst"]]["fills"] += f["qty"]
                pool = ("xyz:USDC" if f["inst"].startswith("xyz:")
                        else "USDC")
                ex[pool]["cash"] += f["realized"] - f["fee"]
        for f in _slice(list(hl_fund), w0, w1):
            # xyz (HIP-3) funding before 2026-07-25 was a daily 00:00
            # REPORTING batch, not a cash settlement: the hourly charges
            # accrued inside the position's unrealized (balance trace
            # 06-18 h23: bal_d = fees + unreal exactly, no room for the
            # +8.73 batch), so counting the batch double-counts and printed
            # -batch breaks at h23 all through June/July. From 07-25 HL
            # settles xyz funding hourly INTO CASH (480 events/day, and
            # 08-02 absorbed +$941 with only $31 drift) — count those.
            # Main-dex USDC funding was always hourly cash.
            if (f["pool"] == "xyz:USDC"
                    and f["t"] < HL_XYZ_FUNDING_CASH_MS):
                continue
            ex[f["pool"]]["cash"] += f["usdc"]
        for r in _slice(bs_xf.get(HL_FUT, []), w0, w1):
            ex[r["asset"]]["transfers"] += r["qty"]

    elif acct == HL_SPOT:
        # HL core spot pool: SPCXD inventory from store fills (qty + USDC
        # notional/fee cash); transfers pool-scoped via venue_transfers.
        # Off-venue folds (Dinari) never enter — STORE_VENUES filter — their
        # tokens arrive as bridge-deposit transfer rows instead.
        for f in _slice(fills, w0, w1):
            if not f["inst"].endswith("@HYPERLIQUID_SPOT"):
                continue
            base = f["inst"].split("/")[0]
            ex[base]["fills"] += f["qty"]
            if f.get("venue") != "HYPERLIQUID":
                continue
            ex["USDC"]["cash"] -= f["qty"] * f["px"]
            # HL spot charges the fee in the RECEIVED token: a BUY pays fee in
            # base, a SELL pays it in USDC. Booking every fee against USDC
            # left the base position overstated by the fee (0.193 HYPE,
            # 0.509 SPCXD) — small, but it is a permanent unexplained break.
            if f.get("fee_asset") == base:
                ex[base]["fills"] -= f["fee"]
            else:
                ex["USDC"]["cash"] -= f["fee"]
        for r in _slice(bs_xf.get(HL_SPOT, []), w0, w1):
            ex[r["asset"]]["transfers"] += r["qty"]

    elif acct == ETH_ACCT:
        for f in _slice(fills, w0, w1):
            if not f["inst"].endswith("@ETHEREUM_RFQ"):
                continue
            base, quote = f["inst"].split("@")[0].split("/")
            ex[base]["fills"] += f["qty"]
            if f.get("venue") != "ETHEREUM":
                # cost-basis fold: executed elsewhere (e.g. Binance), cash
                # settled on the EXECUTION venue's column — only the
                # inventory qty belongs to this wallet
                continue
            ex[quote]["cash"] -= f["qty"] * f["px"]
        for r in _slice(bs_xf.get(ETH_ACCT, []), w0, w1):
            ex[r["asset"]]["transfers"] += r["qty"]

    elif acct == BS_MOON:
        # tokenized-equity spot: token qty from booked fills, USD cash from
        # notional + fees. No transfer feed — deposits land in the break.
        for f in _slice(fills, w0, w1):
            if not f["inst"].endswith("@BITSTAMP"):
                continue
            base, quote = f["inst"].split("@")[0].split("/")
            ex[base]["fills"] += f["qty"]
            ex[quote]["cash"] -= f["qty"] * f["px"]
            if f["fee"] and f["fee_asset"]:
                ex[f["fee_asset"]]["cash"] -= f["fee"]
        for r in _slice(bs_xf.get(BS_MOON, []), w0, w1):
            ex[r["asset"]]["transfers"] += r["qty"]

    return ex


def run_ingest():
    """Top up trades_spot_avgcost with the latest Binance fills so the live
    edge of the recon isn't stale (fills between the last ingest and the
    newest snap would otherwise show as phantom breaks)."""
    import subprocess
    import sys
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for only in ("BINANCE", "BITSTAMP", "ROBINHOOD", "ETHEREUM",
                 "HYPERLIQUID"):
        print(f"[recon] ingesting latest {only} fills "
              "(pnl_8041_daily --ingest-only)...")
        # --date bounds the booked-trades pull (Bitstamp legs); without it the
        # script's default COB date silently no-ops the top-up
        r = subprocess.run([sys.executable, str(REPO / "pnl_8041_daily.py"),
                            "--ingest-only", "--only", only, "--date", today],
                           capture_output=True, text=True, cwd=str(REPO))
        if r.returncode != 0:
            print(f"[recon] WARNING: {only} ingest failed — recon runs on "
                  "stored fills only")
            print((r.stderr or r.stdout or "").strip()[-600:])


def build(days, mark_source="clickhouse", progress=None, end_date=None):
    # end_date (exclusive, midnight): compute a HISTORICAL window instead of
    # one ending now — this is what lets recon_patch_day.py recompute a single
    # past day without touching the rest of the board. `now` keeps its real
    # value for pending/is-latest logic; only the data fetches narrow to fe.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    end = (end_date if end_date is not None
           else now.replace(minute=0, second=0, microsecond=0))
    start = (end - timedelta(days=days)).replace(hour=0)
    t0 = start - timedelta(hours=2)          # anchor hour before day 1
    # fetch upper bound: +10min past the window so the -5min hour bucketing
    # still sees a snapshot batch that lands just after midnight — hour 23's
    # completing batch at 00:01 belongs to THIS window, and cutting it off
    # manufactured a -100k fractured-batch break on 06-19
    fe = min(now, end + timedelta(minutes=10))
    w0_ms = int(t0.replace(tzinfo=timezone.utc).timestamp() * 1000)
    w1_ms = int(fe.replace(tzinfo=timezone.utc).timestamp() * 1000)

    print(f"[recon] window {start} .. {end} UTC ({days} days)")
    # ETH RFQ wallet has no venue/collector feed — hourly snapshots are
    # reconstructed on demand from GoldRush balances-at-block (self-healing:
    # only missing hours are fetched, so routine runs cost ~1 hour's calls)
    import os
    if os.environ.get("RECON_SKIP_GOLDRUSH"):
        print("[recon] GoldRush snap fill SKIPPED (RECON_SKIP_GOLDRUSH)")
        _skip_gr = True
    else:
        _skip_gr = False
    try:
        if _skip_gr:
            raise RuntimeError("skipped")
        import eth_goldrush_snaps
        _eth_floor = datetime(2026, 7, 10)     # wallet inception
        n = eth_goldrush_snaps.ensure_snaps(max(t0, _eth_floor), fe,
                                    max_hours=500)
        # Robinhood pre-ClickHouse week: account_balance_snapshot starts
        # 2026-07-06; GoldRush fills 06-29 (first trading day) -> 07-06
        try:
            import rh_goldrush_snaps
            n += rh_goldrush_snaps.ensure_snaps(
                max(t0, datetime(2026, 6, 29)),
                min(fe, datetime(2026, 7, 6, 12)), max_hours=500)
        except Exception as e:
            print(f"[recon] WARNING: RH GoldRush snap fill failed ({e})")
        # Dinari treasury (HyperEVM): no official feed at all — GoldRush is
        # the only snap source, first activity 2026-06-12
        try:
            import dinari_goldrush_snaps
            n += dinari_goldrush_snaps.ensure_snaps(
                max(t0, datetime(2026, 6, 12)), fe, max_hours=500)
        except Exception as e:
            print(f"[recon] WARNING: Dinari GoldRush snap fill failed ({e})")
        if n:
            print(f"[recon] GoldRush: filled {n} missing ETH snapshot hours")
    except Exception as e:
        if not _skip_gr:
            print(f"[recon] WARNING: GoldRush ETH snap fill failed ({e})")
    print("[recon] snaps...")
    snaps = fetch_snaps(t0, fe)
    unreal = fetch_unreal(t0, fe)
    print(f"[recon] snaps: " + ", ".join(
        f"{a.split('@')[-1]}={len(snaps[a])}h" for a in ACCOUNTS))

    print("[recon] store fills...")
    fills = fetch_store_fills(t0, fe)
    print(f"[recon] {len(fills)} store fills")

    print("[recon] venue flows (income / transfers / interest)...")
    income = fetch_income(w0_ms, w1_ms)
    uni = fetch_uni_transfers(w0_ms, w1_ms)
    sub = fetch_sub_transfers(w0_ms, w1_ms)
    # on-chain deposits/withdrawals land in the SPOT wallet — same row shape
    # as sub transfers, so they route into BIN_SPOT transfers directly
    sub = sub + fetch_chain_deposits(w0_ms, w1_ms)
    pm_int = fetch_pm_interest(w0_ms, w1_ms)
    try:
        import bitstamp_source
        xf, _ = bitstamp_source.fetch_activity()
        bitstamp_source.sync_transfers(xf)
    except Exception as e:
        print(f"[recon] WARNING: Bitstamp transfer sync failed ({e}) — "
              "using stored venue_transfers rows")
    try:
        import chain_transfers
        chain_transfers.sync(venues=("ROBINHOOD", "ETHEREUM"))
    except Exception as e:
        print(f"[recon] WARNING: ETH transfer sync failed ({e})")
    # hl_fills no longer fetched: realized/fee cash now comes from the store
    # (venue fills API only retains ~10k most-recent fills — useless beyond
    # ~a day of history); funding + ledger transfers stay on the venue API
    hl_fills, hl_fund = [], []
    try:
        import hl_flows
        hl_flows.sync_transfers(w0_ms, w1_ms)
        hl_fund = hl_flows.funding(w0_ms, w1_ms)
        print(f"[recon] HL flows: {len(hl_fund)} funding events "
              "(fills cash from store)")
    except Exception as e:
        print(f"[recon] WARNING: HL flows failed ({e})")
    bs_xf = fetch_wallet_transfers(t0, fe)
    print(f"[recon] income={len(income)} uni_xfer={len(uni)} "
          f"sub_xfer={len(sub)} pm_interest={len(pm_int)}")

    # untracked warning: snapshot perp/token instruments with no store leg ever
    store_insts = store_instruments_ever()
    untracked = set()
    for a in (BIN_FUT, BIN_SPOT):
        for h in snaps[a].values():
            for inst in h["bal"]:
                if a == BIN_FUT and inst.endswith("@BINANCE_USDT_FUTURE"):
                    if inst not in store_insts:
                        untracked.add(inst)
                elif (a == BIN_SPOT and inst.endswith("B")
                      and len(inst) <= 6 and inst != "BNB"):
                    if not any(s.startswith(inst + "/") for s in store_insts):
                        untracked.add(inst + " (spot)")

    print(f"[recon] marks ({mark_source})...")
    perp_syms = set()
    spot_assets = set()
    for h in snaps[BIN_FUT].values():
        for inst in h["bal"]:
            if inst.endswith("@BINANCE_USDT_FUTURE"):
                base, rest = inst.split("-P/", 1)
                perp_syms.add(base + rest.split("@")[0])
    for h in snaps[BIN_SPOT].values():
        spot_assets.update(h["bal"])
    spot_assets.add("ETH")    # WETH legs (Robinhood/ETH RFQ) price off ETH
    spot_assets.add("BTC")    # WBTC/CBBTC legs price off BTC
    spot_assets.add("HYPE")   # HL main-dex perp prices off HYPE spot
    spot_assets.add("BNB")    # gas balances on the BSC custody wallets
    spot_assets.add("PAXG")   # Paxos gold leg
    marks = fetch_marks(perp_syms, spot_assets, w0_ms, w1_ms,
                        source=mark_source)

    def mark_key(acct, inst):
        if acct == BIN_FUT and "-P/" in inst:
            base, rest = inst.split("-P/", 1)
            return base + rest.split("@")[0]
        return inst

    def perp_mark(acct, inst, day_iso, at_ms, is_cob):
        """Mark for a perp instrument row (EOD or hourly)."""
        if acct == HL_FUT:
            base = hl_base(inst)
            if base in CRYPTO_MARK:
                return mark_at(marks, CRYPTO_MARK[base], at_ms)
            return eq_mark(base, day_iso, is_cob)
        return mark_at(marks, mark_key(acct, inst), at_ms)

    _eq_cache = {}

    def eq_mark(ticker, day_iso, is_cob):
        """EOD equity mark (equity_marks.py: Yahoo EOD close / HL xyz
        oracle). Weekends/holidays have no close — walk back up to 3 days to
        the last trading day, else a Saturday break values at $0 and hides
        (NVDA +100 contracts on Sat 07-18 rendered as OK, found 2026-07-31).
        0.0 = no mark at all (carry at cost)."""
        k = (ticker, day_iso)
        if k not in _eq_cache:
            m = None
            try:
                import equity_marks
                d0 = datetime.strptime(day_iso, "%Y-%m-%d").date()
                for back in range(4):
                    di = (d0 - timedelta(days=back)).isoformat()
                    m = equity_marks.resolve_mark(ticker, di,
                                                  is_cob=is_cob and back == 0)
                    if m:
                        break
            except Exception:
                m = None
            _eq_cache[k] = float(m) if m else 0.0
        return _eq_cache[k]

    def asset_day_mark(acct, asset, day_iso, at_ms, is_cob):
        """EOD mark for one inventory row (venue-appropriate source)."""
        if asset in ("USDT", "USDC", "USD", "USDG", "USDT0"):
            return 1.0
        if acct == DIN_ACCT:
            if asset in ("SPCX", "SPCX.DW"):
                return eq_mark("SPCX", day_iso, is_cob)
            if asset == "HYPE":
                return mark_at(marks, "HYPE", at_ms)
            return eq_mark(asset, day_iso, is_cob)
        if acct in CUSTODY_ACCTS or acct == PAX_ACCT:
            if asset in ("BNB", "ETH", "WETH", "PAXG"):
                return mark_at(marks, CRYPTO_MARK.get(asset, asset), at_ms)
            if asset.endswith("B"):
                return eq_mark(asset[:-1], day_iso, is_cob)
            return 0.0
        if acct == NAT_ACCT:
            if asset.endswith("B"):
                return eq_mark(asset[:-1], day_iso, is_cob)
            return 0.0
        if acct in (BS_MOON, RH_ACCT, RH05_ACCT):
            if asset == "WETH":
                return mark_at(marks, "ETH", at_ms)
            return eq_mark(asset, day_iso, is_cob)
        if acct == ETH_ACCT:
            return mark_at(marks, CRYPTO_MARK.get(asset, asset), at_ms)
        return mark_at(marks, mark_key(acct, asset), at_ms)

    def _cum_transfers(acct, until_dt):
        """{asset: cumulative net transferred qty} up to a cutoff instant."""
        try:
            conn = avgcost_db.connect()
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT asset, COALESCE(sum(qty), 0)
                        FROM venue_transfers
                        WHERE account = %s AND event_time <= %s
                          AND COALESCE(transfer_type, '')
                              <> 'SETTLEMENT_BOOKED'
                        GROUP BY asset
                    """, (acct, until_dt))
                    out = defaultdict(lambda: ZERO)
                    for a, q in cur.fetchall():
                        if acct == ETH_ACCT and a in ("WETH", "ETH-NATIVE"):
                            a = "ETH"
                        out[a] += D(str(q))
                    return out
            finally:
                conn.close()
        except Exception:
            return defaultdict(lambda: ZERO)

    def positions_at_cutoff(day_dt):
        """EOD summary for one day, split by instrument mechanics:

        - positions (perps only, Binance USD-M): cumulative build vs venue
          position - perp positions move ONLY via fills, so the level ties.
        - inventory (every spot asset, tokens AND cash): DAILY-WINDOW recon:
          prev EOD + trades + transfers (+ unreal for FUT margin cash) = EOD.
          Spot balances are custody inventory; transfers move them, so the
          window identity is the honest control. Mark/Value/uPnL are
          informational columns.
        - off-book: cumulative level gap per token (custody - book build -
          cumulative transfers): standing inventory the book does not carry
          (e.g. unbooked cost-basis deposits), shown once, not daily.
        Pending while the day is open."""
        day_end = day_dt + timedelta(days=1)
        cutoff_label = day_end.strftime("%d %b %Y 00:00 UTC (08:00 SGT)")
        if now < day_end:
            return {"status": "pending", "cutoff": cutoff_label}
        cutoff_hour = (day_end - timedelta(hours=1)).isoformat()
        prev_cutoff = (day_dt - timedelta(hours=1)).isoformat()
        prev_floor = (day_dt - timedelta(days=1)).isoformat()
        day_start = day_dt.isoformat()
        day_iso_str = day_dt.date().isoformat()
        is_latest_day = day_dt.date() == (now.date() - timedelta(days=1))
        CASH = ("USDT", "USDC", "USD", "USDG")
        out = []
        for acct in (BIN_FUT, HL_FUT, HL_SPOT, BIN_SPOT, BIN_PM, BS_MOON,
                     RH_ACCT, RH05_ACCT,
                     ETH_ACCT, DIN_ACCT, NAT_ACCT, PAX_ACCT) + CUSTODY_ACCTS:
            eligible = [h for h in snaps[acct] if day_start <= h <= cutoff_hour]
            latest_iso = max(eligible) if eligible else None
            no_snap = latest_iso is None
            if no_snap:
                latest = {"bal": {}}
                latest_ms = int(day_end.replace(
                    tzinfo=timezone.utc).timestamp() * 1000)
            else:
                latest = snaps[acct][latest_iso]
                latest_ms = latest["ts"]
            built = fetch_latest_positions(latest_ms)

            suffix = {BIN_FUT: "@BINANCE_USDT_FUTURE",
                      BIN_SPOT: "@BINANCE_SPOT",
                      BS_MOON: "@BITSTAMP",
                      RH_ACCT: "@ROBINHOOD",
                      ETH_ACCT: "@ETHEREUM_RFQ",
                      NAT_ACCT: "@NATIVECORE",
                      PAX_ACCT: "@PAXOS",
                      HL_FUT: "@HYPERLIQUID_FUTURES"}.get(acct)

            # book state per base (uPnL info + off-book level check)
            book = {}
            if suffix:
                for inst, st in built.items():
                    if not inst.endswith(suffix):
                        continue
                    base = (inst if acct in PERP_SUFFIX
                            else inst.split("/")[0])
                    if acct not in PERP_SUFFIX and base in CASH:
                        continue
                    b = book.setdefault(base, {"qty": ZERO, "cost": ZERO,
                                               "last": st["last_trade"]})
                    b["qty"] += st["qty"]
                    b["cost"] += st["qty"] * st["avg"]
                    b["last"] = max(b["last"], st["last_trade"])

            # ---- positions: perps only ----
            rows = []
            if acct in PERP_SUFFIX:
                keys = set(book) | {k for k in latest["bal"]
                                    if k.endswith(PERP_SUFFIX[acct])}
                for inst in keys:
                    st = book.get(inst, {"qty": ZERO, "cost": ZERO,
                                         "last": "-"})
                    sq = latest["bal"].get(inst, ZERO)
                    if st["qty"] == 0 and sq == 0:
                        continue
                    mk = perp_mark(acct, inst, day_iso_str, latest_ms,
                                   is_latest_day)
                    avg = float(st["cost"] / st["qty"]) if st["qty"] else 0.0
                    dq = None if no_snap else sq - st["qty"]
                    rows.append({
                        "inst": inst.split("@")[0], "qty": float(st["qty"]),
                        "avg": avg,
                        "snap": None if no_snap else float(sq),
                        "dq": None if no_snap else float(dq), "mark": mk,
                        "usd": float(st["qty"]) * mk,
                        "dusd": 0.0 if no_snap else float(dq) * mk,
                        "upnl": (mk - avg) * float(st["qty"]) if mk else 0.0,
                        "last_trade": str(st["last"])[:16].replace("T", " ")})
                rows.sort(key=lambda r: -abs(r["usd"]))

            # ---- inventory: all spot assets, daily window ----
            inv = []
            prev_cands = [h for h in snaps[acct]
                          if prev_floor <= h <= prev_cutoff]
            if prev_cands and not no_snap:
                prev_iso = max(prev_cands)
                s0 = snaps[acct][prev_iso]
                ex = _expected_for(acct, s0["ts"], latest_ms, fills, income,
                                   uni, sub, pm_int, bs_xf,
                                   hl_fills, hl_fund)
                assets = {k for k in
                          (set(s0["bal"]) | set(latest["bal"]) | set(ex))
                          if not (acct in PERP_SUFFIX
                                  and k.endswith(PERP_SUFFIX[acct]))}
                for a in sorted(assets):
                    b0 = s0["bal"].get(a, ZERO)
                    b1 = latest["bal"].get(a, ZERO)
                    e = ex.get(a, {"fills": ZERO, "cash": ZERO,
                                   "transfers": ZERO})
                    ud = ZERO
                    if acct in PERP_SUFFIX and a in CASH_ASSETS.get(acct, ()):
                        ua = unreal.get(acct, {})
                        ud = (ua.get(latest_iso, {}).get(a, ZERO)
                              - ua.get(prev_iso, {}).get(a, ZERO))
                    trades = e["fills"] + e["cash"]
                    brk = (b1 - b0) - (trades + e["transfers"] + ud)
                    if (b0 == 0 and b1 == 0 and trades == 0
                            and e["transfers"] == 0):
                        continue
                    mk = asset_day_mark(acct, a, day_iso_str, latest_ms,
                                        is_latest_day)
                    st = book.get(a)
                    upnl = ((mk - float(st["cost"] / st["qty"]))
                            * float(st["qty"])
                            if st and st["qty"] and mk else 0.0)
                    inv.append({
                        "asset": a, "b0": float(b0), "b1": float(b1),
                        "trades": float(trades),
                        "xfer": float(e["transfers"]), "unreal": float(ud),
                        "brk": float(brk), "brk_usd": float(brk) * mk,
                        "mark": mk, "value": float(b1) * mk, "upnl": upnl})
                inv.sort(key=lambda r: -abs(r["value"]))

            # ---- cumulative off-book level gap (tokens with book legs) ----
            offbook = []
            if not no_snap and acct not in PERP_SUFFIX:
                cum_x = _cum_transfers(acct, datetime.utcfromtimestamp(
                    latest_ms / 1000))
                for a, st in book.items():
                    sq = latest["bal"].get(a, ZERO)
                    gap = sq - st["qty"] - cum_x.get(a, ZERO)
                    mk = asset_day_mark(acct, a, day_iso_str, latest_ms,
                                        is_latest_day)
                    if abs(float(gap) * (mk or 1.0)) >= TH_WARN:
                        offbook.append({"asset": a, "gap": float(gap),
                                        "usd": float(gap) * mk})
                offbook.sort(key=lambda r: -abs(r["usd"]))

            out.append({"acct": acct, "label": COL_LABEL[acct],
                        "snap_iso": latest_iso, "rows": rows,
                        "inventory": inv, "offbook": offbook})
        return {"status": "ok", "cutoff": cutoff_label, "accounts": out}

    # per-day fill counts by source (clickhouse / chain / api / manual) —
    # day-by-day data-provenance view since the first trading day
    fill_sources = defaultdict(lambda: defaultdict(dict))
    try:
        conn = avgcost_db.connect()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT date(trade_date), account, source, count(*)
                    FROM trades_spot_avgcost
                    WHERE venue = ANY(%s) AND trade_date >= %s
                    GROUP BY 1, 2, 3
                """, (list(STORE_VENUES), start))
                for dt, acct, src, n in cur.fetchall():
                    fill_sources[dt.isoformat()][acct][src] = n
        finally:
            conn.close()
    except Exception as e:
        print(f"[recon] WARNING: fill-source counts failed ({e})")

    # per-hour ingest counts: trades by source + transfer rows, per column
    # (clock-hour buckets — display only, the recon windows stay snap-bounded)
    _COL_OF = {}    # store accounts now map 1:1 to dashboard columns
    hour_src = defaultdict(dict)
    hour_xf = defaultdict(int)
    try:
        conn = avgcost_db.connect()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT date_trunc('hour', trade_date), account, source,
                           count(*)
                    FROM trades_spot_avgcost
                    WHERE venue = ANY(%s) AND trade_date >= %s
                    GROUP BY 1, 2, 3
                """, (list(STORE_VENUES), start))
                for hdt, acct, src, n in cur.fetchall():
                    key = (hdt.astimezone(timezone.utc).replace(tzinfo=None)
                           .isoformat(), _COL_OF.get(acct, acct))
                    hour_src[key][src] = hour_src[key].get(src, 0) + n
                cur.execute("""
                    SELECT date_trunc('hour', event_time), account, count(*)
                    FROM venue_transfers
                    WHERE event_time >= %s
                      AND transfer_type <> 'SETTLEMENT_BOOKED'
                    GROUP BY 1, 2
                """, (start,))
                for hdt, acct, n in cur.fetchall():
                    key = (hdt.astimezone(timezone.utc).replace(tzinfo=None)
                           .isoformat(), _COL_OF.get(acct, acct))
                    hour_xf[key] += n
        finally:
            conn.close()
    except Exception as e:
        print(f"[recon] WARNING: per-hour ingest counts failed ({e})")

    # per-day, per-hour grid — PASS 1: hourly recon, streamed as computed
    days_out = []
    day_dts = []
    d = start
    while d < end:
        day_iso = d.date().isoformat()
        hours_out = []
        for hh in range(24):
            hour = d + timedelta(hours=hh)
            if hour >= end:
                break
            hour_iso = hour.isoformat()
            prev_iso = (hour - timedelta(hours=1)).isoformat()
            hour_ms = int(hour.replace(tzinfo=timezone.utc).timestamp() * 1000)
            cols = {}
            for acct in ACCOUNTS:
                _nf = hour_src.get((hour_iso, acct), {})
                _nx = hour_xf.get((hour_iso, acct), 0)
                s1 = snaps[acct].get(hour_iso)
                s0 = snaps[acct].get(prev_iso)
                if not s1 or not s0:
                    cols[acct] = {"status": "no_snap",
                                  "missing": "this hour" if not s1
                                  else "prev hour",
                                  "nf": _nf, "nx": _nx}
                    continue
                w0, w1 = s0["ts"], s1["ts"]
                ex = _expected_for(acct, w0, w1, fills, income,
                                   uni, sub, pm_int, bs_xf,
                                   hl_fills, hl_fund)
                un1 = unreal.get(acct, {}).get(hour_iso, {})
                un0 = unreal.get(acct, {}).get(prev_iso, {})
                assets = sorted(set(s1["bal"]) | set(s0["bal"]) | set(ex))
                rows, gross, net, nbrk = [], 0.0, 0.0, 0
                for a in assets:
                    b1 = s1["bal"].get(a, ZERO)
                    b0 = s0["bal"].get(a, ZERO)
                    bal_d = b1 - b0
                    e = ex.get(a, {"fills": ZERO, "cash": ZERO,
                                   "transfers": ZERO})
                    ud = ZERO
                    if acct in PERP_SUFFIX and a in CASH_ASSETS.get(acct, ()):
                        ud = un1.get(a, ZERO) - un0.get(a, ZERO)
                    expected = e["fills"] + e["cash"] + e["transfers"] + ud
                    brk = bal_d - expected
                    if acct == HL_FUT:
                        mk = (1.0 if a in ("USDC", "xyz:USDC")
                              else perp_mark(acct, a, day_iso, hour_ms,
                                             d.date() >= now.date()
                                             - timedelta(days=1)))
                    elif acct == ETH_ACCT:
                        mk = (1.0 if a in ("USDC", "USDT")
                              else mark_at(marks,
                                           CRYPTO_MARK.get(a, a), hour_ms))
                    elif acct == HL_SPOT:
                        mk = (1.0 if a == "USDC"
                              else eq_mark("SPCX", day_iso,
                                           d.date() >= now.date()
                                           - timedelta(days=1))
                              if a == "SPCXD"
                              else mark_at(marks, "HYPE", hour_ms)
                              if a == "HYPE" else 0.0)
                    elif acct == DIN_ACCT:
                        fresh = d.date() >= now.date() - timedelta(days=1)
                        mk = (1.0 if a in ("USDC", "USDT0")
                              else eq_mark("SPCX", day_iso, fresh)
                              if a in ("SPCX", "SPCX.DW")
                              else mark_at(marks, "HYPE", hour_ms)
                              if a == "HYPE"
                              else eq_mark(a, day_iso, fresh))
                    elif acct in CUSTODY_ACCTS or acct == PAX_ACCT:
                        # USDG included: without it a 166k USDG break on the
                        # Paxos column priced at $0 and vanished from the board
                        mk = (1.0 if a in ("USDT", "USDC", "USD", "USDG")
                              else mark_at(marks, CRYPTO_MARK.get(a, a),
                                           hour_ms)
                              if a in ("BNB", "ETH", "WETH", "PAXG")
                              else eq_mark(a[:-1], day_iso,
                                           d.date() >= now.date()
                                           - timedelta(days=1))
                              if a.endswith("B") else 0.0)
                    elif acct == NAT_ACCT:
                        # B-tokens mark at the underlying equity
                        mk = (1.0 if a in ("USDT", "USD")
                              else eq_mark(a[:-1], day_iso,
                                           d.date() >= now.date()
                                           - timedelta(days=1))
                              if a.endswith("B") else 0.0)
                    elif acct in (BS_MOON, RH_ACCT, RH05_ACCT):
                        mk = (1.0 if a in ("USD", "USDC", "USDG")
                              else mark_at(marks, "ETH", hour_ms)
                              if a == "WETH"
                              else eq_mark(a, day_iso,
                                           d.date() >= now.date()
                                           - timedelta(days=1)))
                    else:
                        mk = mark_at(marks, mark_key(acct, a), hour_ms)
                    usd = float(brk) * mk
                    if (abs(usd) < TH_OK and bal_d == 0 and expected == 0
                            and b1 == 0):
                        continue
                    gross += abs(usd)
                    net += usd
                    if abs(usd) >= TH_OK:
                        nbrk += 1
                    rows.append({
                        "asset": a.split("@")[0], "b0": float(b0),
                        "b1": float(b1), "bal_d": float(bal_d),
                        "fills": float(e["fills"]), "cash": float(e["cash"]),
                        "xfer": float(e["transfers"]), "unreal": float(ud),
                        "brk": float(brk), "mark": mk, "usd": usd,
                        "gap": False})
                rows.sort(key=lambda r: -abs(r["usd"]))
                cols[acct] = {"status": "ok", "gross": gross, "net": net,
                              "nbrk": nbrk, "snap_ts": w1, "rows": rows,
                              "nf": _nf, "nx": _nx,
                              "src0": s0.get("src", "?"),
                              "src1": s1.get("src", "?")}
            hours_out.append({"hour": hh, "iso": hour_iso, "cols": cols})
        days_out.append({"day": day_iso, "hours": hours_out,
                         "fill_sources": fill_sources.get(day_iso, {}),
                         "positions": {"status": "building",
                                       "cutoff": (d + timedelta(days=1))
                                       .strftime("%d %b %Y 00:00 UTC "
                                                 "(08:00 SGT)")}})
        day_dts.append(d)
        if progress:
            try:
                progress(days_out)
            except Exception as e:
                print(f"[recon] WARNING: progressive publish failed ({e})")
        print(f"[recon] hours published: {day_iso}")
        d += timedelta(days=1)

    _tag_snap_gaps(days_out)
    if progress:
        try:
            progress(days_out)     # republish with timing pairs tagged
        except Exception:
            pass

    # PASS 2: EOD summaries, streamed day by day (equity marks are the slow
    # part — hourly recon above is already fully available)
    for i, dd in enumerate(day_dts):
        days_out[i]["positions"] = positions_at_cutoff(dd)
        if progress:
            try:
                progress(days_out)
            except Exception as e:
                print(f"[recon] WARNING: progressive publish failed ({e})")
        print(f"[recon] EOD published: {days_out[i]['day']}")

    return {"generated": now.isoformat(timespec="seconds") + "Z",
            "accounts": [{"id": a, "label": COL_LABEL[a]} for a in ACCOUNTS],
            "thresholds": {"ok": TH_OK, "warn": TH_WARN, "bad": TH_BAD},
            "untracked": sorted(untracked),
            "days": days_out}


def _tag_snap_gaps(days_out):
    """Tag adjacent-hour break pairs that cancel on qty as snapshot gaps.

    The balance/position streamer occasionally drops rows from one hourly
    batch; the balance 'vanishes' for an hour and returns, producing two
    equal-and-opposite phantom breaks. A pair of consecutive-hour breaks in
    the same (account, asset) whose break QTYs cancel (within 2%) is such a
    gap, not real risk — tag both rows and re-total their hours without them.
    Bitstamp settlement lag produces the same signature up to ~2-3h apart
    (venue stamps the event before balances move), so pairs cancel within a
    3-hour window. (Real one-sided problems — a missing trade, an untracked
    symbol — do not cancel and keep their break status.)
    """
    seq = defaultdict(list)   # (acct, asset) -> [(iso, row, col)]
    recompute = []
    for day in days_out:
        for h in day["hours"]:
            for acct, c in h["cols"].items():
                if c.get("status") != "ok":
                    continue
                recompute.append(c)
                for r in c["rows"]:
                    seq[(acct, r["asset"])].append((h["iso"], r))
    for (acct, asset), items in seq.items():
        items.sort(key=lambda x: x[0])
        i = 0
        while i < len(items):
            iso0, r0 = items[i]
            if r0["gap"] or abs(r0["usd"]) < TH_OK:
                i += 1
                continue
            # accumulate breaks forward (settlement batches can be N-to-1);
            # if the running qty sum returns to ~0 within the window, the
            # whole group is a timing artifact
            acc, group = 0.0, []
            for j in range(i, len(items)):
                iso1, r1 = items[j]
                if (datetime.fromisoformat(iso1)
                        - datetime.fromisoformat(iso0)) > timedelta(hours=4):
                    break
                if r1["gap"]:
                    continue
                acc += r1["brk"]
                group.append(r1)
                if (len(group) >= 2
                        and abs(acc) <= max(1e-9, 0.02 * max(
                            abs(g["brk"]) for g in group))):
                    for g in group:
                        g["gap"] = True
                    break
            i += 1
    for c in recompute:
        live = [r for r in c["rows"] if not r["gap"]]
        c["gross"] = sum(abs(r["usd"]) for r in live)
        c["net"] = sum(r["usd"] for r in live)
        c["nbrk"] = sum(1 for r in live if abs(r["usd"]) >= TH_OK)


# ── html ───────────────────────────────────────────────────────────────
def publish_db(data, run_id=None):
    """Persist the run payload to UAT middle_office.recon_runs (the React
    dashboard's API serves the latest row). With run_id, UPDATE in place —
    used for progressive day-by-day publishing while a build is running."""
    conn = avgcost_db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS recon_runs (
                    id           BIGSERIAL PRIMARY KEY,
                    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    payload      JSONB NOT NULL
                )""")
            if run_id is None:
                cur.execute("INSERT INTO recon_runs (payload) VALUES (%s) "
                            "RETURNING id", (json.dumps(data),))
                run_id = cur.fetchone()[0]
            else:
                cur.execute("UPDATE recon_runs SET payload = %s, "
                            "generated_at = now() WHERE id = %s",
                            (json.dumps(data), run_id))
        conn.commit()
        return run_id
    finally:
        conn.close()


def emit_html(data, out_path):
    payload = json.dumps(data, separators=(",", ":"))
    html = HTML_TEMPLATE.replace("/*__DATA__*/null", payload)
    out_path.write_text(html, encoding="utf-8")
    print(f"[recon] wrote {out_path}")


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Binance 810 · Hourly Recon</title>
<style>
:root {
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --line: #e4e3de;
  --ink: #0b0b0b; --ink2: #52514e; --ink3: #8a887f;
  --good: #0ca30c; --warn: #b47500; --bad: #d03b3b;
  --good-bg: #0ca30c14; --warn-bg: #fab21922; --bad-bg: #d03b3b14;
  --hover: #00000008;
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --line: #2e2d2b;
  --ink: #ffffff; --ink2: #c3c2b7; --ink3: #807f76;
  --warn: #fab219;
  --good-bg: #0ca30c22; --warn-bg: #fab21918; --bad-bg: #d03b3b26;
  --hover: #ffffff0a;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --line: #2e2d2b;
    --ink: #ffffff; --ink2: #c3c2b7; --ink3: #807f76;
    --warn: #fab219;
    --good-bg: #0ca30c22; --warn-bg: #fab21918; --bad-bg: #d03b3b26;
    --hover: #ffffff0a;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--page); color: var(--ink);
  font: 14px/1.45 Inter, "Segoe UI", system-ui, sans-serif;
}
.num { font-variant-numeric: tabular-nums; }
.wrap { max-width: 1180px; margin: 0 auto; padding: 20px 20px 60px; }
header { display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap;
         margin-bottom: 6px; }
h1 { font-size: 19px; margin: 0; font-weight: 650; }
.sub { color: var(--ink3); font-size: 12.5px; }
#themeBtn { margin-left: auto; background: none; border: 1px solid var(--line);
  border-radius: 7px; color: var(--ink2); padding: 4px 10px; cursor: pointer;
  font: inherit; font-size: 12.5px; }
.banner { background: var(--warn-bg); border: 1px solid var(--warn);
  border-radius: 9px; padding: 9px 13px; margin: 12px 0; font-size: 13px; }
.banner b { color: var(--warn); }
.daytabs { display: flex; gap: 6px; margin: 16px 0 12px; flex-wrap: wrap; }
.daytabs button { font: inherit; font-size: 13px; padding: 5px 13px;
  border: 1px solid var(--line); background: var(--surface); color: var(--ink2);
  border-radius: 8px; cursor: pointer; }
.daytabs button.on { color: var(--ink); border-color: var(--ink2);
  font-weight: 600; }
.daytabs button .dot { display: inline-block; width: 7px; height: 7px;
  border-radius: 50%; margin-right: 6px; vertical-align: 1px; }
.daytabs .d-ok .dot { background: var(--good); }
.daytabs .d-warn .dot { background: var(--warn); }
.daytabs .d-bad .dot { background: var(--bad); }
.daytabs .d-pending .dot { background: var(--ink3); }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 10px;
  margin-bottom: 14px; }
.tile { background: var(--surface); border: 1px solid var(--line);
  border-radius: 10px; padding: 11px 14px; }
.tile .t { font-size: 12px; color: var(--ink3); margin-bottom: 3px; }
.tile .v { font-size: 21px; font-weight: 650; }
.tile .d { font-size: 11.5px; color: var(--ink3); margin-top: 2px; }
.gridbox { background: var(--surface); border: 1px solid var(--line);
  border-radius: 10px; overflow-x: auto; }
table { border-collapse: collapse; width: 100%; min-width: 760px; }
th { text-align: right; font-size: 11.5px; text-transform: uppercase;
  letter-spacing: .04em; color: var(--ink3); font-weight: 600;
  padding: 9px 14px 7px; border-bottom: 1px solid var(--line); }
th:first-child { text-align: left; }
td { padding: 6px 14px; border-bottom: 1px solid var(--line);
  text-align: right; font-size: 13.5px; }
td:first-child { text-align: left; color: var(--ink2); white-space: nowrap; }
tr.hr { cursor: pointer; }
tr.hr:hover td { background: var(--hover); }
tr:last-child td { border-bottom: none; }
.cell { display: inline-flex; align-items: center; gap: 7px;
  justify-content: flex-end; }
.dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
.st-ok .dot { background: var(--good); }
.st-warn .dot { background: var(--warn); }
.st-bad .dot { background: var(--bad); }
.st-ok { color: var(--ink2); }
.st-warn { color: var(--warn); font-weight: 600; }
.st-bad { color: var(--bad); font-weight: 650; }
.nb { font-size: 11px; color: var(--ink3); background: var(--hover);
  border: 1px solid var(--line); padding: 0 6px; border-radius: 8px; }
.nosnap { color: var(--ink3); font-size: 12.5px; font-style: italic; }
.chev { display: inline-block; width: 14px; color: var(--ink3);
  transition: transform .12s; }
tr.open .chev { transform: rotate(90deg); }
.detail td { background: var(--page); padding: 10px 14px 16px; }
.dt { width: 100%; min-width: 0; margin-top: 4px; }
.dt caption { text-align: left; font-size: 12px; color: var(--ink2);
  font-weight: 600; padding: 8px 0 4px; }
.dt th { font-size: 10.5px; padding: 4px 9px; border-bottom: 1px solid var(--line); }
.dt td { font-size: 12.5px; padding: 3.5px 9px; border-bottom: none; }
.dt tr.brk-warn td { background: var(--warn-bg); }
.dt tr.brk-bad td { background: var(--bad-bg); }
.dt .lbl { display: inline-flex; gap: 6px; align-items: center; }
.badge { font-size: 10px; font-weight: 700; letter-spacing: .05em;
  padding: 1px 6px; border-radius: 7px; }
.badge.ok { color: var(--good); background: var(--good-bg); }
.badge.warn { color: var(--warn); background: var(--warn-bg); }
.badge.bad { color: var(--bad); background: var(--bad-bg); }
.badge.gap { color: var(--ink3); background: var(--hover);
  border: 1px solid var(--line); }
.dt tr.gaprow td { color: var(--ink3); }
.muted { color: var(--ink3); }
footer { margin-top: 18px; color: var(--ink3); font-size: 12px; }
.posbox { margin: 2px 0 12px; }
.posbox details { background: var(--surface); border: 1px solid var(--line);
  border-radius: 10px; padding: 0; }
.posbox summary { cursor: pointer; padding: 10px 14px; font-weight: 600;
  font-size: 14px; list-style: none; display: flex; gap: 10px;
  align-items: baseline; }
.posbox summary::before { content: "▸"; color: var(--ink3); font-size: 12px; }
.posbox details[open] summary::before { content: "▾"; }
.posbox summary .muted { font-weight: 400; font-size: 12px; }
.poscols { padding: 0 14px 12px; overflow-x: auto; }
.poscols h3 { font-size: 12.5px; margin: 8px 0 2px; color: var(--ink2); }
.poscols h3 .muted { font-weight: 400; font-size: 11px; }
.pt { width: 100%; border-collapse: collapse; }
.pt th { font-size: 10.5px; padding: 4px 8px; text-align: right;
  border-bottom: 1px solid var(--line); }
.pt th:first-child { text-align: left; }
.pt td { font-size: 12.5px; padding: 3.5px 8px; border-bottom: none;
  text-align: right; }
.pt td:first-child { text-align: left; color: var(--ink); font-weight: 550; }
.pt tr.drift td { background: var(--warn-bg); }
.pt tr.ptot td { border-top: 1px solid var(--line); font-weight: 650;
  padding-top: 5px; }
.pos { color: var(--good); } .neg { color: var(--bad); }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Binance 810 · Hourly Recon</h1>
    <span class="sub" id="gen"></span>
    <button id="themeBtn">◐ theme</button>
  </header>
  <div class="sub">snap Δ − (fills + cash/PnL + transfers + unreal Δ) per hour ·
    breaks in USD eq at hour-close marks · all times UTC</div>
  <div id="banner"></div>
  <div class="daytabs" id="daytabs"></div>
  <div class="posbox" id="posbox"></div>
  <div class="tiles" id="tiles"></div>
  <div class="gridbox"><table id="grid"></table></div>
  <footer>Sources: trades_spot_avgcost (UAT middle_office) · papi um/income ·
    universal + sub-account transfers · tq_hist_balance / tq_hist_position
    hourly snaps · marks fapi markPriceKlines &amp; spot klines.
    Row click expands per-asset detail. Thresholds: warn $<span id="thw"></span>,
    bad $<span id="thb"></span>.</footer>
</div>
<script>
const DATA = /*__DATA__*/null;
const $ = s => document.querySelector(s);
const fmtU = v => (v < 0 ? "−" : "") + "$" + Math.abs(v).toLocaleString("en-US",
  {maximumFractionDigits: Math.abs(v) >= 100 ? 0 : 2});
const fmtQ = v => {
  if (v === 0) return "0";
  const a = Math.abs(v);
  const d = a >= 1000 ? 2 : a >= 1 ? 4 : 6;
  return v.toLocaleString("en-US", {maximumFractionDigits: d});
};
const stCls = g => g < DATA.thresholds.warn ? "st-ok"
                 : g < DATA.thresholds.bad ? "st-warn" : "st-bad";
const stTxt = g => g < DATA.thresholds.warn ? "OK"
                 : g < DATA.thresholds.bad ? "CHECK" : "BREAK";
const Q = new URLSearchParams(location.search);
let dayIdx = Math.max(0, DATA.days.findIndex(d => d.day === Q.get("day")));
if (!Q.get("day")) dayIdx = DATA.days.length - 1;

function render() {
  $("#gen").textContent = "generated " + DATA.generated;
  $("#thw").textContent = DATA.thresholds.warn;
  $("#thb").textContent = DATA.thresholds.bad;
  if (DATA.untracked.length)
    $("#banner").innerHTML = '<div class="banner"><b>⚠ untracked legs:</b> ' +
      "snapshots hold positions with no recorded trades for: " +
      DATA.untracked.join(", ") + " — add to the ingest symbol lists.</div>";
  const tabs = $("#daytabs");
  tabs.innerHTML = "";
  DATA.days.forEach((d, i) => {
    const b = document.createElement("button");
    const st = dayStatus(d);
    b.innerHTML = `<span class="dot"></span>${d.day}` +
      (st.n ? ` <span class="nb">${st.n}</span>` : "");
    b.className = `d-${st.cls}` + (i === dayIdx ? " on" : "");
    b.title = st.tip;
    b.onclick = () => { dayIdx = i; render(); };
    tabs.appendChild(b);
  });
  renderPositions();
  renderTiles();
  renderGrid();
}

function renderPositions() {
  const box = $("#posbox");
  const P = DATA.days[dayIdx].positions;
  const day = DATA.days[dayIdx].day;
  if (!P || P.status === "pending") {
    box.innerHTML = `<details open><summary>EOD summary — ${day} ` +
      `<span class="muted">pending — day not ended (cutoff ` +
      `${P ? P.cutoff : "—"})</span></summary><div class="poscols">` +
      `<p class="muted" style="font-size:12.5px">The EOD summary is cut at ` +
      `midnight UTC (08:00 SGT). Re-run after the cutoff to populate this ` +
      `day.</p></div></details>`;
    return;
  }
  let inner = "";
  P.accounts.forEach(p => {
    const inv = p.inventory || [];
    if (!p.rows.length && !inv.length) return;
    const posVal = p.rows.reduce((s, r) => s + r.usd, 0);
    const posUpnl = p.rows.reduce((s, r) => s + r.upnl, 0);
    const invVal = inv.reduce((s, r) => s + r.value, 0);
    inner += `<h3>${p.label} <span class="muted">· snap ${p.snap_iso ?
        p.snap_iso.slice(0, 13) + ":59Z" : "—"}` +
      (p.rows.length ? ` · positions ${fmtU(posVal)} · uPnL ` +
        `<span class="${posUpnl >= 0 ? "pos" : "neg"}">${fmtU(posUpnl)}</span>`
        : "") +
      (inv.length ? ` · inventory ${fmtU(invVal)}` : "") +
      `</span></h3>`;

    if (p.rows.length) {
      inner += `<table class="pt num"><tr><th>Position (perp)</th>` +
        `<th>Build qty</th><th>Avg cost</th><th>Mark</th><th>Value</th>` +
        `<th>uPnL</th><th>EOD snap</th><th>Break qty</th><th>Break USD</th>` +
        `<th>Status</th><th>Last trade</th></tr>`;
      p.rows.forEach(r => {
        const noSnap = r.snap === null;
        const au = Math.abs(r.dusd);
        const drift = !noSnap && au >= DATA.thresholds.ok;
        const bcls = noSnap ? "gap" : au < DATA.thresholds.ok ? "ok" :
                     au < DATA.thresholds.bad ? "warn" : "bad";
        const btxt = noSnap ? "NO SNAP" : au < DATA.thresholds.ok ? "OK" :
                     au < DATA.thresholds.bad ? "CHECK" : "BREAK";
        inner += `<tr class="${drift ? "drift" : ""}">` +
          `<td>${r.inst}</td><td>${fmtQ(r.qty)}</td><td>${fmtQ(r.avg)}</td>` +
          `<td>${r.mark ? fmtQ(r.mark) : "—"}</td><td>${fmtU(r.usd)}</td>` +
          `<td class="${r.upnl >= 0 ? "pos" : "neg"}">${fmtU(r.upnl)}</td>` +
          `<td>${noSnap ? "—" : fmtQ(r.snap)}</td>` +
          `<td>${noSnap ? "—" : drift ? fmtQ(r.dq) : "0"}</td>` +
          `<td>${noSnap ? "—" : drift ? fmtU(r.dusd) : "$0"}</td>` +
          `<td><span class="badge ${bcls}">${btxt}</span></td>` +
          `<td class="muted">${r.last_trade}</td></tr>`;
      });
      const totDusd = p.rows.reduce((s, r) => s + r.dusd, 0);
      inner += `<tr class="ptot"><td>Total</td><td></td><td></td><td></td>` +
        `<td>${fmtU(posVal)}</td>` +
        `<td class="${posUpnl >= 0 ? "pos" : "neg"}">${fmtU(posUpnl)}</td>` +
        `<td></td><td></td><td>${fmtU(totDusd)}</td><td></td><td></td></tr>` +
        `</table>`;
    }

    if (inv.length) {
      inner += `<table class="pt num" style="margin-top:6px">` +
        `<tr><th>Cash &amp; inventory</th><th>Prev EOD</th><th>Trades</th>` +
        `<th>Transfers</th><th>Unreal Δ</th><th>EOD snap</th>` +
        `<th>Break qty</th><th>Break USD</th><th>Mark</th><th>Value</th>` +
        `<th>Status</th></tr>`;
      let tv = 0, tb = 0;
      inv.forEach(r => {
        tv += r.value; tb += r.brk_usd;
        const au = Math.abs(r.brk_usd);
        const bcls = au < DATA.thresholds.ok ? "ok" :
                     au < DATA.thresholds.bad ? "warn" : "bad";
        const btxt = au < DATA.thresholds.ok ? "OK" :
                     au < DATA.thresholds.bad ? "CHECK" : "BREAK";
        inner += `<tr class="${au >= DATA.thresholds.warn ? "drift" : ""}">` +
          `<td>${r.asset}</td><td>${fmtQ(r.b0)}</td>` +
          `<td>${fmtQ(r.trades)}</td><td>${fmtQ(r.xfer)}</td>` +
          `<td>${r.unreal ? fmtQ(r.unreal) : "0"}</td>` +
          `<td>${fmtQ(r.b1)}</td><td>${fmtQ(r.brk)}</td>` +
          `<td>${fmtU(r.brk_usd)}</td>` +
          `<td>${r.mark && r.mark !== 1 ? fmtQ(r.mark) : (r.mark ? "1" : "—")}</td>` +
          `<td>${fmtU(r.value)}</td>` +
          `<td><span class="badge ${bcls}">${btxt}</span></td></tr>`;
      });
      inner += `<tr class="ptot"><td>Total</td><td></td><td></td><td></td>` +
        `<td></td><td></td><td></td><td>${fmtU(tb)}</td><td></td>` +
        `<td>${fmtU(tv)}</td><td></td></tr></table>`;
    }

    if ((p.offbook || []).length) {
      inner += `<p class="muted" style="font-size:11.5px;margin:4px 0 2px">` +
        `⚠ off-book inventory (custody − book − transfers): ` +
        p.offbook.map(o => `${o.asset} ${fmtQ(o.gap)} (${fmtU(o.usd)})`)
          .join(" · ") +
        ` — unbooked cost-basis / transfer history predating the feed</p>`;
    }
  });
  const nDrift = P.accounts.flatMap(p =>
      (p.rows || []).map(r => Math.abs(r.dusd))
      .concat((p.inventory || []).map(r => Math.abs(r.brk_usd))))
    .filter(v => v >= DATA.thresholds.ok).length;
  box.innerHTML = `<details open><summary>EOD summary — ${day} ` +
    `<span class="muted">cutoff ${P.cutoff} · ` +
    `${nDrift ? nDrift + " breaking" : "all matching"}</span></summary>` +
    `<div class="poscols">` + inner + `</div></details>`;
}

function dayStatus(d) {
  // worst hourly gross across accounts + the EOD stables breaks for the day
  let worst = 0, n = 0;
  d.hours.forEach(h => Object.values(h.cols).forEach(c => {
    if (c && c.status === "ok" && c.gross >= DATA.thresholds.ok) {
      worst = Math.max(worst, c.gross); n += c.nbrk;
    }
  }));
  if (d.positions && d.positions.status === "ok")
    d.positions.accounts.forEach(a => (a.inventory || []).forEach(r => {
      if (Math.abs(r.brk_usd) >= DATA.thresholds.ok)
        worst = Math.max(worst, Math.abs(r.brk_usd));
    }));
  const pending = d.positions && d.positions.status === "pending";
  const cls = worst >= DATA.thresholds.bad ? "bad" :
              worst >= DATA.thresholds.warn ? "warn" :
              pending ? "pending" : "ok";
  const tip = pending ? "day open — EOD pending" :
              cls === "ok" ? "reconciled" :
              `worst break ${Math.round(worst).toLocaleString()} USD`;
  return {cls, n, tip};
}

function renderTiles() {
  const day = DATA.days[dayIdx];
  const box = $("#tiles");
  box.innerHTML = "";
  DATA.accounts.forEach(a => {
    let tot = 0, worst = null, snapped = 0;
    day.hours.forEach(h => {
      const c = h.cols[a.id];
      if (!c || c.status !== "ok") return;
      snapped++;
      tot += c.gross;
      if (!worst || c.gross > worst.g) worst = {h: h.hour, g: c.gross};
    });
    const cls = stCls(worst ? worst.g : 0);
    box.insertAdjacentHTML("beforeend",
      `<div class="tile"><div class="t">${a.label}</div>` +
      `<div class="v num ${cls}">${fmtU(tot)}</div>` +
      `<div class="d num">day gross break · worst hour ` +
      (worst ? String(worst.h).padStart(2, "0") + ":00 (" + fmtU(worst.g) + ")"
             : "—") + ` · ${snapped}h snapped</div></div>`);
  });
}

function renderGrid() {
  const day = DATA.days[dayIdx];
  const t = $("#grid");
  t.innerHTML = "<tr><th>Hour (UTC)</th>" +
    DATA.accounts.map(a => "<th>" + a.label + "</th>").join("") + "</tr>";
  day.hours.forEach(h => {
    const tr = document.createElement("tr");
    tr.className = "hr num";
    let cells = `<td><span class="chev">▸</span>` +
      String(h.hour).padStart(2, "0") + ":00</td>";
    DATA.accounts.forEach(a => {
      const c = h.cols[a.id];
      if (!c || c.status !== "ok") {
        cells += `<td><span class="nosnap">no snap (${c ? c.missing : "?"})</span></td>`;
        return;
      }
      const cls = stCls(c.gross);
      const twoSided = c.gross - Math.abs(c.net) >= DATA.thresholds.ok;
      const val = twoSided ? "±" + fmtU(c.gross).replace("−", "") : fmtU(c.net);
      cells += `<td><span class="cell ${cls}"><span class="dot"></span>` +
        `<span>${val}</span>` +
        (c.nbrk ? `<span class="nb">${c.nbrk}</span>` : "") + `</span></td>`;
    });
    tr.innerHTML = cells;
    tr.onclick = () => toggle(tr, h);
    t.appendChild(tr);
    if (Q.get("open") !== null && +Q.get("open") === h.hour) toggle(tr, h);
  });
}

function toggle(tr, h) {
  if (tr.nextSibling && tr.nextSibling.classList.contains("detail")) {
    tr.nextSibling.remove();
    tr.classList.remove("open");
    return;
  }
  tr.classList.add("open");
  const d = document.createElement("tr");
  d.className = "detail";
  let html = `<td colspan="${DATA.accounts.length + 1}">`;
  DATA.accounts.forEach(a => {
    const c = h.cols[a.id];
    if (!c || c.status !== "ok" || !c.rows.length) return;
    html += `<table class="dt num"><caption>${a.label}` +
      ` <span class="muted">· snap ${new Date(c.snap_ts).toISOString()
        .slice(11, 19)}Z</span></caption>` +
      "<tr><th style='text-align:left'>Asset</th><th>Prev</th><th>Snap</th>" +
      "<th>Δ balance</th><th>Fills</th><th>Cash/PnL</th><th>Transfers</th>" +
      "<th>Unreal Δ</th><th>Break qty</th><th>Mark</th><th>Break USD</th>" +
      "<th>Status</th></tr>";
    c.rows.forEach(r => {
      const au = Math.abs(r.usd);
      const cls = r.gap ? "gaprow" : au < DATA.thresholds.warn ? "" :
                  au < DATA.thresholds.bad ? "brk-warn" : "brk-bad";
      const bcls = r.gap ? "gap" : au < DATA.thresholds.ok ? "ok" :
                   au < DATA.thresholds.bad ? "warn" : "bad";
      const btxt = r.gap ? "TIMING" : au < DATA.thresholds.ok ? "OK" :
                   au < DATA.thresholds.bad ? "CHECK" : "BREAK";
      html += `<tr class="${cls}"><td style="text-align:left">${r.asset}</td>` +
        `<td>${fmtQ(r.b0)}</td><td>${fmtQ(r.b1)}</td>` +
        `<td>${fmtQ(r.bal_d)}</td><td>${fmtQ(r.fills)}</td>` +
        `<td>${fmtQ(r.cash)}</td><td>${fmtQ(r.xfer)}</td>` +
        `<td>${fmtQ(r.unreal)}</td><td>${fmtQ(r.brk)}</td>` +
        `<td>${r.mark ? fmtQ(r.mark) : "—"}</td><td>${fmtU(r.usd)}</td>` +
        `<td><span class="lbl"><span class="badge ${bcls}">${btxt}</span>` +
        `</span></td></tr>`;
    });
    html += "</table>";
  });
  d.innerHTML = html + "</td>";
  tr.after(d);
}

$("#themeBtn").onclick = () => {
  const r = document.documentElement;
  const dark = (r.dataset.theme || (matchMedia("(prefers-color-scheme: dark)")
    .matches ? "dark" : "light")) === "dark";
  r.dataset.theme = dark ? "light" : "dark";
};
render();
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=4)
    ap.add_argument("--start", metavar="YYYY-MM-DD",
                    help="window start date (overrides --days; e.g. "
                         "2026-06-29 = first RH trading day)")
    ap.add_argument("--out", default=str(REPO / "binance810_recon.html"))
    ap.add_argument("--marks", choices=("clickhouse", "venue"),
                    default="clickhouse",
                    help="hourly mark source (default: ClickHouse midprice, "
                         "venue klines as fallback)")
    ap.add_argument("--no-ingest", action="store_true",
                    help="skip the Binance fill top-up before reconciling")
    ap.add_argument("--force", action="store_true",
                    help="recompute every day in the window, ignoring the "
                         "per-day cache (use after a methodology change)")
    ap.add_argument("--no-cache", action="store_true",
                    help="neither read nor write the per-day cache")
    args = ap.parse_args()
    if not args.no_ingest:
        run_ingest()
    days = args.days
    if args.start:
        sd = datetime.strptime(args.start, "%Y-%m-%d").date()
        days = max(1, (datetime.now(timezone.utc).date() - sd).days + 1)

    # Incremental rebuild: recompute only the suffix that changed, then splice
    # the cached older days back in so the published payload still covers the
    # whole window (the API serves ONE row = the whole board).
    cache, carried, sig = None, [], None
    if not args.no_cache and args.start:
        try:
            import recon_cache
            cache = recon_cache
            sig = cache.code_sig()
            if args.force:
                print("[cache] --force: recomputing the full window")
            else:
                frm, why = cache.earliest_dirty(sd)
                if frm > sd:
                    carried = cache.load_before(frm)
                    days = max(1, (datetime.now(timezone.utc).date()
                                   - frm).days + 1)
                    print(f"[cache] recomputing from {frm} ({why}) — "
                          f"{len(carried)} earlier days served from cache")
                else:
                    print(f"[cache] full rebuild: {why}")
        except Exception as e:
            print(f"[recon] WARNING: day cache unavailable ({e}) — "
                  "full rebuild")
            cache, carried = None, []
    _state = {"run_id": None}

    def _meta(days_list, partial):
        return {"generated": datetime.now(timezone.utc)
                    .isoformat(timespec="seconds") + "Z",
                "accounts": [{"id": a, "label": COL_LABEL[a]}
                             for a in ACCOUNTS],
                "thresholds": {"ok": TH_OK, "warn": TH_WARN, "bad": TH_BAD},
                "untracked": [], "partial": partial, "days": days_list}

    def _merge(days_list):
        """Cached days + freshly computed ones, deduped by date.

        Merge by DATE, never by count: build() rounds its window to whole days
        from `now`, so the recomputed span can start a day earlier than asked
        and would otherwise emit that day twice."""
        have = {d["day"] for d in days_list}
        return [d for d in carried if d["day"] not in have] + days_list

    def _progress(days_list):
        # publish carried + fresh so the board keeps its full history while a
        # partial rebuild is still walking the tail
        merged = _merge(days_list)
        _state["run_id"] = publish_db(_meta(merged, True), _state["run_id"])
        print(f"[recon] progressive publish: {days_list[-1]['day']} "
              f"({len(merged)} days, {len(days_list)} recomputed)")

    data = build(days, mark_source=args.marks, progress=_progress)
    fresh = data["days"]
    if carried:
        data["days"] = _merge(fresh)
        # re-tag across the cached/fresh seam: a settlement pair straddling the
        # boundary would otherwise stay untagged on one side. Idempotent —
        # rows already marked gap=True are skipped and only totals re-derive.
        _tag_snap_gaps(data["days"])
    if cache is not None:
        try:
            if args.force:
                # a --force pass is the only chance to catch a cache that has
                # been serving stale numbers, so check before overwriting
                cache.compare(fresh)
            print(f"[cache] stored {cache.save(fresh, sig)} recomputed days")
        except Exception as e:
            print(f"[recon] WARNING: day cache write failed ({e})")
    data["partial"] = False
    emit_html(data, Path(args.out))
    try:
        publish_db(data, _state["run_id"])
        print("[recon] published payload to recon_runs")
    except Exception as e:
        print(f"[recon] WARNING: recon_runs publish failed ({e})")


if __name__ == "__main__":
    main()
