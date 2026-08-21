"""Postgres layer for trades_spot_avgcost (UAT middle_office).

Creds: MO_DB_* env vars first, else the `# MO DB UAT` block in the parent
middle-office-tools/.env (same convention as scripts/spot_db.py). Times are
TIMESTAMPTZ; the session is pinned to UTC.
"""
from __future__ import annotations
import os
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent
PARENT_ENV = REPO.parent / ".env"   # middle-office-tools/.env holds # MO DB UAT

INSERT_COLS = (
    "venue", "account", "instrument", "product", "external_trade_id", "source",
    "direction", "base_asset", "base_amount", "quote_asset", "price",
    "fee_asset", "fee_amount", "fee_usd", "realized", "pos_qty_after",
    "avg_cost_after", "portfolio_id", "portfolio_name", "counterparty",
    "trade_date", "comment",
)


def load_creds():
    env_creds = {
        k: os.environ[f"MO_DB_{k.upper()}"]
        for k in ("host", "port", "database", "username", "password")
        if f"MO_DB_{k.upper()}" in os.environ
    }
    if all(k in env_creds for k in ("host", "database", "username", "password")):
        env_creds.setdefault("port", "5432")
        return env_creds
    creds = {}
    in_block = False
    for line in PARENT_ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if "MO DB UAT" in s.upper():
            in_block = True
            continue
        if not in_block:
            continue
        if not s or s.startswith("#"):
            if s.startswith("#") and "MO DB UAT" not in s.upper():
                break
            continue
        if ":" in s:
            k, _, v = s.partition(":")
            key = k.strip().lower()
            if key.startswith("mo_db_"):
                key = key[len("mo_db_"):]
            creds[key] = v.strip()
    if not creds:
        raise RuntimeError(f"No '# MO DB UAT' block found in {PARENT_ENV}")
    return creds


def connect():
    import psycopg2
    c = load_creds()
    conn = psycopg2.connect(
        host=c["host"],
        port=int(c.get("port", "5432")),
        dbname=c["database"],
        user=c["username"],
        password=c["password"],
        connect_timeout=15,
    )
    with conn.cursor() as cur:
        cur.execute("SET TIMEZONE = 'UTC'")
    conn.commit()
    return conn


def build_insert_tuple(leg, row):
    """Map a folded fill (row) + per-leg static labels (leg) to a value tuple
    in INSERT_COLS order. direction/base_amount derive from signed_qty;
    trade_date from trade_date_ms."""
    sq = row["signed_qty"]
    direction = "LONG" if sq >= 0 else "SHORT"
    base_amount = sq if sq >= 0 else -sq
    trade_date = datetime.fromtimestamp(row["trade_date_ms"] / 1000, timezone.utc)
    values = {
        "venue": row.get("venue", leg.get("venue")),
        "account": leg["account"],
        "instrument": leg["instrument"],
        "product": leg["product"],
        "external_trade_id": str(row["external_trade_id"]),
        "source": row["source"],
        "direction": direction,
        "base_asset": row["base_asset"],
        "base_amount": base_amount,
        "quote_asset": leg["quote_asset"],
        "price": row["price"],
        "fee_asset": row.get("fee_asset"),
        "fee_amount": row.get("fee_amount", 0),
        "fee_usd": row["fee_usd"],
        "realized": row["realized"],
        "pos_qty_after": row["pos_qty_after"],
        "avg_cost_after": row["avg_cost_after"],
        "portfolio_id": leg.get("portfolio_id", "8041"),
        "portfolio_name": leg.get("portfolio_name",
                                  "TOKKA LABS - MM - CENTRAL RISK BOOK"),
        "counterparty": row.get("counterparty", leg.get("counterparty")),
        "trade_date": trade_date,
        "comment": row.get("comment"),
    }
    return tuple(values[c] for c in INSERT_COLS)


def ingest_leg(conn, leg, fills):
    """Pre-filter DB-present ids, fold the tail seeded from last_state, insert.

    If any fresh fill is back-dated before the stored tip, a seed-from-tip fold
    mis-orders history and corrupts the memoized running position, so re-fold the
    whole leg chronologically afterwards to repair it. Returns
    (inserted, n_fresh, refold_reason | None). Shared by the daily runner and the
    Native fills collector so both fold identically."""
    from decimal import Decimal
    import avgcost_ingest as ing
    inst = leg["instrument"]
    state = last_state(conn, inst)
    if state is None:
        seed_qty, seed_avg, tip_key = Decimal("0"), Decimal("0"), None
    else:
        seed_qty, seed_avg = Decimal(str(state[0])), Decimal(str(state[1]))
        tip_key = (int(state[2].timestamp() * 1000), str(state[3]))
    present = existing_ids(conn, inst, [f["external_trade_id"] for f in fills])
    fresh = [f for f in fills if f["external_trade_id"] not in present]
    fresh.sort(key=lambda f: (f["trade_date_ms"], str(f["external_trade_id"])))
    folded = ing.fold_fills(seed_qty, seed_avg, fresh)
    tuples = [build_insert_tuple(leg, r) for r in folded]
    inserted = insert_fills(conn, tuples)
    reason = None
    if ing.needs_refold(tip_key, fresh):
        reason = "back-dated fill"
    elif position_drift(conn, inst) != 0:
        reason = f"position drift {position_drift(conn, inst)}"
    if reason:
        refold_leg(conn, inst)
    return inserted, len(fresh), reason


def distinct_instruments(conn):
    """[(instrument, account, product, quote_asset)] for every stored instrument.
    Used to drive a DB-only report without re-pulling venue fills. account is the
    snapshot/account venue (not the per-fill venue), so DINARI manual rows don't
    create a separate instrument."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT instrument, account, product, "
            "       max(quote_asset) AS quote_asset "
            "FROM trades_spot_avgcost "
            "WHERE account NOT IN ('') "
            "GROUP BY instrument, account, product "
            "ORDER BY instrument"
        )
        return cur.fetchall()


def last_state(conn, instrument):
    """(pos_qty_after, avg_cost_after, trade_date, external_trade_id) of the
    most recent fill for instrument, or None if empty."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pos_qty_after, avg_cost_after, trade_date, external_trade_id "
            "FROM trades_spot_avgcost WHERE instrument = %s "
            "ORDER BY trade_date DESC, id DESC LIMIT 1",
            (instrument,),
        )
        return cur.fetchone()


def existing_ids(conn, instrument, ids):
    """Subset of `ids` already stored for instrument (pre-fold dedup)."""
    if not ids:
        return set()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT external_trade_id FROM trades_spot_avgcost "
            "WHERE instrument = %s AND external_trade_id = ANY(%s)",
            (instrument, [str(i) for i in ids]),
        )
        return {r[0] for r in cur.fetchall()}


def insert_fills(conn, tuples):
    """Insert pre-built value tuples (INSERT_COLS order). Idempotent via
    ON CONFLICT DO NOTHING. Returns rows actually inserted."""
    if not tuples:
        return 0
    cols_sql = ", ".join(INSERT_COLS)
    placeholders = ", ".join(["%s"] * len(INSERT_COLS))
    sql = (
        f"INSERT INTO trades_spot_avgcost ({cols_sql}) "
        f"VALUES ({placeholders}) "
        "ON CONFLICT (venue, instrument, external_trade_id, source) DO NOTHING"
    )
    from psycopg2.extras import execute_values
    values_sql = (
        f"INSERT INTO trades_spot_avgcost ({cols_sql}) VALUES %s "
        "ON CONFLICT (venue, instrument, external_trade_id, source) DO NOTHING"
    )
    tpl = "(" + placeholders + ")"
    n = 0
    with conn.cursor() as cur:
        # one statement per page instead of one per row — VPN-latency bound
        for i in range(0, len(tuples), 1000):
            execute_values(cur, values_sql, tuples[i:i + 1000],
                           template=tpl, page_size=1000)
            n += cur.rowcount
    conn.commit()
    return n


def refold_leg(conn, instrument):
    """Re-fold one instrument's whole history chronologically and rewrite its
    memoized realized / pos_qty_after / avg_cost_after / fee_usd in place.

    Repairs a leg corrupted by an out-of-order incremental top-up (back-dated
    manual add). Returns (rows_updated, new_tip_qty). No-op-safe: a leg already
    in chronological order is rewritten to the same values.
    """
    import avgcost_ingest as ing
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, external_trade_id, direction, base_amount, price, "
            "       base_asset, fee_asset, fee_amount, trade_date "
            "FROM trades_spot_avgcost WHERE instrument = %s",
            (instrument,),
        )
        rows = cur.fetchall()
    fills = []
    for (rid, eid, direction, base_amount, price, base_asset,
         fee_asset, fee_amount, trade_date) in rows:
        sq = base_amount if direction == "LONG" else -base_amount
        fills.append({
            "id": rid,
            "external_trade_id": eid,
            "signed_qty": sq,
            "price": price,
            "base_asset": base_asset,
            "fee_asset": fee_asset,
            "fee_amount": fee_amount if fee_amount is not None else 0,
            "trade_date_ms": int(trade_date.timestamp() * 1000),
        })
    folded = ing.refold_rows(fills)
    from psycopg2.extras import execute_values
    n = 0
    with conn.cursor() as cur:
        # batched write-back: one statement per 5k rows instead of one
        # round-trip per fill (a 30k-fill refold was ~35 min over VPN)
        for i in range(0, len(folded), 5000):
            batch = [(r["realized"], r["pos_qty_after"],
                      r["avg_cost_after"], r["fee_usd"], r["id"])
                     for r in folded[i:i + 5000]]
            execute_values(cur, """
                UPDATE trades_spot_avgcost AS t
                   SET realized = v.realized,
                       pos_qty_after = v.pos_qty_after,
                       avg_cost_after = v.avg_cost_after,
                       fee_usd = v.fee_usd
                  FROM (VALUES %s) AS v(realized, pos_qty_after,
                                        avg_cost_after, fee_usd, id)
                 WHERE t.id = v.id
            """, batch,
                template="(%s::numeric, %s::numeric, %s::numeric, "
                         "%s::numeric, %s::bigint)",
                page_size=5000)
            n += cur.rowcount
    conn.commit()
    tip_qty = folded[-1]["pos_qty_after"] if folded else None
    return n, tip_qty


def net_signed_qty(conn, instrument):
    """Order-independent net signed position for a leg:
    SUM(signed base_amount) − SUM(in-kind fees), matching the net-quantity
    fold (fee_asset == base_asset fees settle out of the received tokens).
    Independent of fold order, so it is the ground-truth a memoized tip
    pos_qty_after must match."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(SUM((CASE WHEN direction='LONG' THEN base_amount "
            "ELSE -base_amount END) - (CASE WHEN upper(coalesce(fee_asset,'')) "
            "= upper(base_asset) THEN COALESCE(fee_amount, 0) ELSE 0 END)), 0) "
            "FROM trades_spot_avgcost WHERE instrument = %s", (instrument,))
        return cur.fetchone()[0]


def position_drift(conn, instrument):
    """memoized tip pos_qty_after - order-independent net signed qty, as Decimal.

    Non-zero means the leg's memoized running position is inconsistent with its
    fills (an out-of-order / back-dated fold) and the leg must be re-folded.
    """
    from decimal import Decimal
    state = last_state(conn, instrument)
    tip = Decimal(str(state[0])) if state else Decimal("0")
    return tip - Decimal(str(net_signed_qty(conn, instrument)))


def verify_legs(conn):
    """[(instrument, tip_qty, net_sum, drift)] for every stored leg, drift first.
    drift != 0 flags a leg whose memo needs a re-fold (read-only health check)."""
    from decimal import Decimal
    out = []
    for inst, _acct, _prod, _quote in distinct_instruments(conn):
        state = last_state(conn, inst)
        tip = Decimal(str(state[0])) if state else Decimal("0")
        net = Decimal(str(net_signed_qty(conn, inst)))
        out.append((inst, tip, net, tip - net))
    out.sort(key=lambda r: (r[3] == 0, r[0]))
    return out


def window_agg(conn, instrument, w0, w1):
    """(realized_sum, fee_usd_sum, n_api, n_manual) for [w0, w1) on instrument.
    w0/w1 are tz-aware datetimes."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(SUM(realized),0), COALESCE(SUM(fee_usd),0), "
            "  COUNT(*) FILTER (WHERE source='api'), "
            "  COUNT(*) FILTER (WHERE source='manual') "
            "FROM trades_spot_avgcost "
            "WHERE instrument = %s AND trade_date >= %s AND trade_date < %s",
            (instrument, w0, w1),
        )
        return cur.fetchone()


def pos_at(conn, instrument, ts):
    """(pos_qty_after, avg_cost_after) of the last fill with trade_date < ts;
    (0, 0) if none."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pos_qty_after, avg_cost_after FROM trades_spot_avgcost "
            "WHERE instrument = %s AND trade_date < %s "
            "ORDER BY trade_date DESC, id DESC LIMIT 1",
            (instrument, ts),
        )
        r = cur.fetchone()
        return r if r else (0, 0)
