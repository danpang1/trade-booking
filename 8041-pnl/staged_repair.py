"""Staged historical repair for trades_spot_avgcost: stage -> verify -> promote.

Rationale (agreed 2026-07-30): the avg-cost engine refolds a leg's ENTIRE
history on every back-dated insert, so running several backfill batches pays
the full refold price each time. For historical work, collect ALL candidate
fills into a staging table first, verify completeness/duplicates against the
store while the data is still raw, then promote once — exactly ONE refold per
touched leg. Daily tip ingest stays incremental (appends need no refold).

Usage:
  python staged_repair.py --tag hl-jul --stage-ch-hl 2026-06-29 2026-07-28
  python staged_repair.py --tag hl-jul --stage-ch-hl 2026-08-01 2026-08-03
  python staged_repair.py --tag hl-jul --verify
  python staged_repair.py --tag hl-jul --promote
  python staged_repair.py --tag hl-jul --clear

Loaders are additive: run --stage-* as many times as needed (idempotent,
UNIQUE key dedup), then verify/promote the whole tag at once.
"""
from __future__ import annotations

import argparse
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import avgcost_db
import robinhood_ch_source as R

HL_USER = "0x45bef7096101ffe85c7e4fd0cfbfb3cb2bfa61e3"   # TRADING_06
HLF_ACCT = "TRADING_06@HYPERLIQUID_FUTURES"
HLS_ACCT = "TRADING_06@HYPERLIQUID_SPOT"
SPOT_PAIRS = {"@465": "SPCXD",
              # @107 = HYPE/USDC. Added 2026-08-03: 17 fills
              # ($44k turnover) were being refused as an unmapped
              # pair, leaving the 1.307 HYPE the venue reports on the
              # spot account with no book explanation at all.
              "@107": "HYPE"}
NAT_USER = "0xe71b2e6ddc88ffdecdcd0d750c57d0122aa586c2"   # TRADING_01
NAT_ACCT = "TRADING_01@NATIVECORE"

DDL = """
CREATE TABLE IF NOT EXISTS trades_staging (
    id                BIGSERIAL PRIMARY KEY,
    repair_tag        TEXT NOT NULL,
    venue             TEXT NOT NULL,
    account           TEXT NOT NULL,
    instrument        TEXT NOT NULL,
    product           TEXT NOT NULL,
    quote_asset       TEXT NOT NULL,
    external_trade_id TEXT NOT NULL,
    trade_date        TIMESTAMPTZ NOT NULL,
    signed_qty        NUMERIC NOT NULL,
    price             NUMERIC NOT NULL,
    fee_amount        NUMERIC NOT NULL DEFAULT 0,
    fee_asset         TEXT,
    source            TEXT NOT NULL,
    staged_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (repair_tag, account, instrument, external_trade_id)
);
"""


def _ch(sql, tries=5):
    for i in range(tries):
        try:
            req = urllib.request.Request(R.CH_URL, data=sql.encode())
            return urllib.request.urlopen(req, timeout=240).read().decode()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(8)


# ── loaders ────────────────────────────────────────────────────────────
def stage_ch_hl(conn, tag, d0, d1):
    """ClickHouse production.execution HL fills (xyz perps + core spot)
    into staging. fee 0 (CH has no fee column) — known residual."""
    n = 0
    day = d0
    while day <= d1:
        us0 = int(day.timestamp() * 1_000_000)
        us1 = int((day + timedelta(days=1)).timestamp() * 1_000_000)
        q = f"""
        SELECT exchange, raw_symbol, trade_id, side, price, quantity,
               ts_exchange_event
        FROM production.execution
        PREWHERE ts_exchange_event >= {us0} AND ts_exchange_event < {us1}
        WHERE exchange IN ('hip-xyz-perp', 'hyperliquid-spot')
          AND user_id = '{HL_USER}'
        FORMAT TSV
        """
        rows = [ln.split("\t") for ln in _ch(q).splitlines() if ln.strip()]
        tuples = []
        for exch, sym, tid, side, px, qty, ts_us in rows:
            if exch == "hip-xyz-perp":
                acct, inst, prod = (HLF_ACCT,
                                    f"{sym}-P/USD@HYPERLIQUID_FUTURES",
                                    "PERP")
            elif sym in SPOT_PAIRS:
                t = SPOT_PAIRS[sym]
                acct, inst, prod = (HLS_ACCT,
                                    f"{t}/USDC@HYPERLIQUID_SPOT", "SPOT")
            else:
                print(f"  !! unmapped spot pair {sym} tid {tid} — skipped")
                continue
            ts = datetime.fromtimestamp(int(ts_us) / 1e6, timezone.utc)
            tuples.append((tag, acct, inst, prod, str(tid), ts,
                           D(qty) * int(side), D(px)))
        from psycopg2.extras import execute_values
        with conn.cursor() as cur:
            for i in range(0, len(tuples), 2000):
                execute_values(cur, """
                    INSERT INTO trades_staging
                        (repair_tag, venue, account, instrument, product,
                         quote_asset, external_trade_id, trade_date,
                         signed_qty, price, fee_amount, fee_asset, source)
                    VALUES %s
                    ON CONFLICT (repair_tag, account, instrument,
                                 external_trade_id) DO NOTHING
                """, tuples[i:i + 2000],
                    template="(%s, 'HYPERLIQUID', %s, %s, %s, 'USDC', %s, "
                             "%s, %s, %s, 0, 'USDC', 'clickhouse')",
                    page_size=2000)
                n += cur.rowcount
        conn.commit()
        print(f"[stage ch-hl] {day:%Y-%m-%d}: {len(rows)} pulled "
              f"(running staged: {n})", flush=True)
        day += timedelta(days=1)
    return n


def stage_s3_hl(conn, tag, path):
    """HL fills from the S3 node-data archive (hl_s3_fills.py pull output).

    Strictly better than the ClickHouse loader for the same day: identical
    id-space (`tid` == the venue API's trade id, so rows dedup against the
    store and against ch-hl staging), but WITH REAL FEES. ClickHouse has no
    fee column at all, which is what leaves the xyz:USDC residue on days
    rebuilt from it.

    Fee = `fee` + `deployerFee`: the HIP-3 dex charges a deployer fee on top
    of the standard one, and both debit USDC. Summing them is what makes the
    cash leg tie; taking `fee` alone leaves the deployer portion unexplained.
    """
    import json
    from pathlib import Path
    from psycopg2.extras import execute_values
    fills = json.loads(Path(path).read_text(encoding="utf-8"))
    tuples, skipped = [], {}
    for f in fills:
        coin = f.get("coin") or ""
        # HL coin naming: 'xyz:X' = HIP-3 dex perp, '@N' = spot pair index,
        # anything else = MAIN-DEX perp (HYPE, BTC). The main-dex case was
        # previously lumped into `skipped`, which would have silently dropped
        # real fills on the tracked HYPE-P leg (4 of them on 2026-07-12,
        # found by the S3 audit). Every fill here is already filtered to our
        # user, so an unrecognised bare coin IS ours.
        if coin.startswith("xyz:"):
            acct, inst, prod = (HLF_ACCT,
                                f"{coin}-P/USD@HYPERLIQUID_FUTURES", "PERP")
        elif coin.startswith("@"):
            if coin not in SPOT_PAIRS:
                # a spot pair with no leg in our model — do NOT invent one,
                # report it and let the leg be added deliberately
                skipped[coin] = skipped.get(coin, 0) + 1
                continue
            acct, inst, prod = (HLS_ACCT,
                                f"{SPOT_PAIRS[coin]}/USDC@HYPERLIQUID_SPOT",
                                "SPOT")
        else:
            acct, inst, prod = (HLF_ACCT,
                                f"{coin}-P/USD@HYPERLIQUID_FUTURES", "PERP")
        sgn = 1 if str(f.get("side", "")).upper() == "B" else -1
        fee = D(str(f.get("fee") or 0)) + D(str(f.get("deployerFee") or 0))
        # feeToken is NOT always USDC — HL spot charges the fee in the
        # RECEIVED token, so a BUY pays in base. Hardcoding 'USDC' here (the
        # original bug) recorded 0.193 HYPE of fees as $0.193 and left the
        # book position overstated by the fee.
        ftok = str(f.get("feeToken") or "USDC")
        ts = datetime.fromtimestamp(int(f["time"]) / 1000, timezone.utc)
        tuples.append((tag, acct, inst, prod, str(f["tid"]), ts,
                       D(str(f["sz"])) * sgn, D(str(f["px"])), fee, ftok))
    n = 0
    with conn.cursor() as cur:
        for i in range(0, len(tuples), 2000):
            execute_values(cur, """
                INSERT INTO trades_staging
                    (repair_tag, venue, account, instrument, product,
                     quote_asset, external_trade_id, trade_date,
                     signed_qty, price, fee_amount, fee_asset, source)
                VALUES %s
                ON CONFLICT (repair_tag, account, instrument,
                             external_trade_id) DO NOTHING
            """, tuples[i:i + 2000],
                template="(%s, 'HYPERLIQUID', %s, %s, %s, 'USDC', %s, "
                         "%s, %s, %s, %s, %s, 's3')",
                page_size=2000)
            n += cur.rowcount
    conn.commit()
    if skipped:
        print(f"[stage s3-hl] coins not on HL legs (skipped): {skipped}")
    print(f"[stage s3-hl] {len(fills)} fills read, {n} staged "
          f"(fees total {sum(t[8] for t in tuples):.2f} USDC)", flush=True)
    return n


def stage_ch_native(conn, tag, d0, d1):
    """ClickHouse native-spot fills for TRADING_01 into staging. CH carries
    duplicate rows per trade_id on some days (07-01..03) — the staging
    UNIQUE key collapses them. fee 0 (no fee column) — known residual."""
    from psycopg2.extras import execute_values
    n = 0
    day = d0
    while day <= d1:
        us0 = int(day.timestamp() * 1_000_000)
        us1 = int((day + timedelta(days=1)).timestamp() * 1_000_000)
        q = f"""
        SELECT raw_symbol, trade_id, side, price, quantity,
               MIN(ts_exchange_event)
        FROM production.execution
        PREWHERE ts_exchange_event >= {us0} AND ts_exchange_event < {us1}
        WHERE exchange = 'native-spot' AND user_id = '{NAT_USER}'
        GROUP BY raw_symbol, trade_id, side, price, quantity
        FORMAT TSV
        """
        rows = [ln.split("\t") for ln in _ch(q).splitlines() if ln.strip()]
        tuples = []
        for sym, tid, side, px, qty, ts_us in rows:
            base, quote = sym.split("/")
            inst = f"{base}/{quote}@NATIVECORE"
            ts = datetime.fromtimestamp(int(ts_us) / 1e6, timezone.utc)
            tuples.append((tag, NAT_ACCT, inst, quote, str(tid), ts,
                           D(qty) * int(side), D(px), quote))
        with conn.cursor() as cur:
            for i in range(0, len(tuples), 2000):
                execute_values(cur, """
                    INSERT INTO trades_staging
                        (repair_tag, venue, account, instrument, product,
                         quote_asset, external_trade_id, trade_date,
                         signed_qty, price, fee_amount, fee_asset, source)
                    VALUES %s
                    ON CONFLICT (repair_tag, account, instrument,
                                 external_trade_id) DO NOTHING
                """, tuples[i:i + 2000],
                    template="(%s, 'NATIVE CORE', %s, %s, 'SPOT', %s, %s, "
                             "%s, %s, %s, 0, %s, 'clickhouse')",
                    page_size=2000)
                n += cur.rowcount
        conn.commit()
        print(f"[stage ch-native] {day:%Y-%m-%d}: {len(rows)} distinct "
              f"(running staged: {n})", flush=True)
        day += timedelta(days=1)
    return n


# ── verify ─────────────────────────────────────────────────────────────
def verify(conn, tag):
    """Raw-data checks BEFORE any avg-cost math: in-staging duplicates and
    per-instrument/per-day staged-vs-store presence (by external id)."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT account, instrument, external_trade_id, COUNT(*)
            FROM trades_staging WHERE repair_tag = %s
            GROUP BY 1,2,3 HAVING COUNT(*) > 1
        """, (tag,))
        dups = cur.fetchall()
        print(f"duplicate keys within staging: {len(dups)}")
        for d_ in dups[:20]:
            print("  DUP", d_)

        cur.execute("""
            SELECT s.instrument, DATE(s.trade_date),
                   COUNT(*) AS staged,
                   COUNT(t.external_trade_id) AS in_store
            FROM trades_staging s
            LEFT JOIN trades_spot_avgcost t
              ON t.account = s.account AND t.instrument = s.instrument
             AND t.external_trade_id = s.external_trade_id
            WHERE s.repair_tag = %s
            GROUP BY 1,2 ORDER BY 1,2
        """, (tag,))
        missing_total = 0
        print(f"{'instrument':44} {'day':10} {'staged':>7} {'store':>7} miss")
        for inst, day, staged, in_store in cur.fetchall():
            miss = staged - in_store
            missing_total += miss
            if miss:
                print(f"{inst:44} {day} {staged:>7} {in_store:>7} {miss:>5}")
        print(f"TOTAL missing in store (to promote): {missing_total}")
    return missing_total


# ── promote ────────────────────────────────────────────────────────────
def promote(conn, tag):
    """Insert store-missing staged fills — ONE ingest_leg (= one refold)
    per touched leg, regardless of how many staging batches fed the tag."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT s.venue, s.account, s.instrument, s.product,
                   s.quote_asset, s.external_trade_id, s.trade_date,
                   s.signed_qty, s.price, s.fee_amount, s.fee_asset, s.source
            FROM trades_staging s
            WHERE s.repair_tag = %s
            ORDER BY s.trade_date
        """, (tag,))
        by_leg = defaultdict(list)
        for (ven, acct, inst, prod, qa, xid, ts, sq, px, fee, fa,
             src) in cur.fetchall():
            by_leg[(ven, acct, inst, prod, qa)].append({
                "external_trade_id": xid,
                "trade_date_ms": int(ts.timestamp() * 1000),
                "signed_qty": D(str(sq)), "price": D(str(px)),
                "fee_amount": D(str(fee)), "fee_asset": fa,
                "base_asset": inst.split("/")[0].split("-P")[0],
                "source": src, "venue": ven,
            })
    total = 0
    for (ven, acct, inst, prod, qa), fills in sorted(by_leg.items()):
        leg = {"venue": ven, "account": acct, "instrument": inst,
               "product": prod, "quote_asset": qa, "counterparty": None}
        ins, fresh, refold = avgcost_db.ingest_leg(conn, leg, fills)
        conn.commit()
        total += ins
        print(f"[promote] {inst}: {ins} inserted ({len(fills)} staged, "
              f"{fresh} fresh)" + (f", refold: {refold}" if refold else ""),
              flush=True)
    print(f"TOTAL promoted: {total}")
    return total


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tag", required=True, help="repair batch name")
    ap.add_argument("--stage-ch-hl", nargs=2, metavar=("D0", "D1"),
                    help="stage CH HL fills for [D0, D1] (YYYY-MM-DD)")
    ap.add_argument("--stage-ch-native", nargs=2, metavar=("D0", "D1"),
                    help="stage CH native-spot fills for [D0, D1]")
    ap.add_argument("--stage-s3-hl", metavar="JSON",
                    help="stage HL fills from an hl_s3_fills.py pull dump "
                         "(same ids as ch-hl, but WITH real fees)")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--promote", action="store_true")
    ap.add_argument("--clear", action="store_true",
                    help="delete this tag's staged rows")
    a = ap.parse_args()
    conn = avgcost_db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(DDL)
        conn.commit()
        if a.stage_ch_hl:
            d0 = datetime.strptime(a.stage_ch_hl[0], "%Y-%m-%d").replace(
                tzinfo=timezone.utc)
            d1 = datetime.strptime(a.stage_ch_hl[1], "%Y-%m-%d").replace(
                tzinfo=timezone.utc)
            n = stage_ch_hl(conn, a.tag, d0, d1)
            print(f"staged {n} new rows under tag {a.tag!r}")
        if a.stage_s3_hl:
            n = stage_s3_hl(conn, a.tag, a.stage_s3_hl)
            print(f"staged {n} new S3 rows under tag {a.tag!r}")
        if a.stage_ch_native:
            d0 = datetime.strptime(a.stage_ch_native[0], "%Y-%m-%d").replace(
                tzinfo=timezone.utc)
            d1 = datetime.strptime(a.stage_ch_native[1], "%Y-%m-%d").replace(
                tzinfo=timezone.utc)
            n = stage_ch_native(conn, a.tag, d0, d1)
            print(f"staged {n} new native rows under tag {a.tag!r}")
        if a.verify:
            verify(conn, a.tag)
        if a.promote:
            promote(conn, a.tag)
        if a.clear:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM trades_staging WHERE repair_tag=%s",
                            (a.tag,))
                print(f"cleared {cur.rowcount} staged rows")
            conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
