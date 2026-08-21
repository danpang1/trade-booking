"""Native Core trade history: native_trades.csv UNION ClickHouse execution.

Native's own userFills API retains only ~8 minutes of fills, so history lives in
two lossy-but-complementary recorders, validated against the hourly position
snapshots (tq_hist_position_mo) on 2026-07-02:

  * native_trades.csv — the trading-team fill logger. Richest (side, role, fee,
    fee_asset, oids), complete 2026-06-11 -> now EXCEPT 06-13..15 + part of
    06-16. No duplicates.
  * ClickHouse production.execution (exchange='native-spot') — live collector.
    Complete 06-13..16 and 06-24.., but ZERO fills 06-16 15:42 -> 06-23 02:52
    (collector outage; unrecoverable from the venue) and 618 double-written
    rows since 06-30 (second trade_id format `tx:1:maker:oid`).

  => UNION (CSV primary, CH adds only what CSV lacks) ties to the position
     snapshots on every symbol/day once in-kind fees are counted (buys pay fee
     in the BASE token, sells in USDT). Residual: one 0.16 SNDKB early-day
     snapshot artifact on 2026-06-12 (~$250).

Dedup key across sources: (tx_hash, our_order_id, price, qty).
external_trade_id = tx:oid:px — deterministic, so re-ingest is idempotent.
"""
from __future__ import annotations
import csv
import json
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
from native_common import WALLET, EXCH, INSTR_VENUE, ACCOUNT_NAME  # noqa: E402

CSV_PATH = REPO / "native_trades.csv"
CH = ("https://jp-clickhouse-api.internal.tokkalabs.com:443/"
      "?user=prod_ro&password=scCtp%21Ez8%233h%23LK8")
_W = WALLET.lower()


def _D(x):
    return Decimal(str(x))


def _px_key(px):
    """Canonical price string for the dedup key / external id (no exponent,
    no trailing zeros) so CSV '1601.6' == CH '1601.600000000000000000'."""
    return format(_D(px).normalize(), "f")


def csv_fills():
    """{key: fill dict} from native_trades.csv (our wallet only)."""
    out = {}
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["user"].lower() != _W:
                continue                       # foreign maker (e.g. TSLAon rows)
            oid = r["maker_oid"] if r["role"] == "maker" else r["taker_oid"]
            qty = _D(r["quantity"])
            sign = Decimal(1) if r["side"] == "buy" else Decimal(-1)
            t_ms = int(datetime.strptime(r["time_utc_est"], "%Y-%m-%dT%H:%M:%SZ")
                       .replace(tzinfo=timezone.utc).timestamp() * 1000)
            sym = r["market"].split("/")[0].upper()
            key = (r["tx_hash"].lower(), str(oid), _px_key(r["price"]), str(qty.normalize()))
            out[key] = {
                "external_trade_id": f"{key[0]}:{key[1]}:{key[2]}",
                "trade_date_ms": t_ms,
                "signed_qty": qty * sign,
                "price": _D(r["price"]),
                "fee_amount": _D(r["fee"] or "0"),
                "fee_asset": (r["fee_asset"] or "USDT").upper(),
                "base_asset": sym,
                "source": "api",
                "comment": f"native h={r['height']} {r['role']}",
            }
    return out


def ch_fills():
    """{key: fill dict} from ClickHouse execution — BOTH trade_id formats.

    The collector wrote plain tx-hash ids until 2026-07-03 ~08:00, dual
    plain+suffixed (`tx:1:maker:oid`) 06-30..07-03, and suffixed-ONLY from
    07-03 on (verified 2026-07-08: a plain-only filter silently dropped all
    fills after 07-03 07:18). Normalising tx = the part before ':' and keying
    on (tx, oid, price, qty) dedups the dual-write twins naturally. CH has no
    fee column; fees on CH-only rows are recorded as 0."""
    sql = ("SELECT splitByChar(':', trade_id)[1], exchange_order_id,"
           " toString(price), toString(quantity),"
           " side, intDiv(ts_exchange_event, 1000), upper(base_asset)"
           " FROM production.execution"
           " WHERE exchange='native-spot'"
           " FORMAT TSV")
    r = urllib.request.urlopen(urllib.request.Request(
        CH, data=sql.encode(), headers={"Content-Type": "text/plain"}), timeout=60)
    out = {}
    for ln in r.read().decode().strip().splitlines():
        tx, oid, px, qty, side, t_ms, sym = ln.split("\t")
        q = _D(qty)
        key = (tx.lower(), str(oid), _px_key(px), str(q.normalize()))
        out[key] = {
            "external_trade_id": f"{key[0]}:{key[1]}:{key[2]}",
            "trade_date_ms": int(t_ms),
            "signed_qty": q if side == "1" else -q,
            "price": _D(px),
            "fee_amount": Decimal(0),
            "fee_asset": "USDT",
            "base_asset": sym,
            "source": "api",
            "comment": "native ch-execution",
        }
    return out


def union_fills():
    """Merged {key: fill}, CSV wins on overlap. Returns (fills, n_csv, n_ch_added)."""
    base = csv_fills()
    added = 0
    for k, f in ch_fills().items():
        if k not in base:
            base[k] = f
            added += 1
    return base, len(base) - added, added


def native_trade_legs():
    """[(leg_labels, fills)] per instrument, ready for adb.ingest_leg."""
    fills, n_csv, n_ch = union_fills()
    by_sym = defaultdict(list)
    for f in fills.values():
        by_sym[f["base_asset"]].append(f)
    legs = []
    for sym in sorted(by_sym):
        legs.append((
            {"venue": EXCH, "account": ACCOUNT_NAME,
             "instrument": f"{sym}/USDT@{INSTR_VENUE}", "product": "SPOT",
             "quote_asset": "USDT", "counterparty": None},
            by_sym[sym],
        ))
    return legs, n_csv, n_ch


if __name__ == "__main__":
    legs, n_csv, n_ch = native_trade_legs()
    print(f"union: {n_csv} csv + {n_ch} ch-only fills, {len(legs)} legs")
    for lg, fl in legs:
        tot = sum(f["signed_qty"] for f in fl)
        print(f"  {lg['instrument']:24} {len(fl):5} fills  net {tot}")
