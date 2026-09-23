"""Build + best-effort write of manual_trade / manual_cashflow rows.

This is the manual-booking dual-write sink: called AFTER a trades_spot /
trades_cashflow row is written, it mirrors that row into the tech DB's
manual_* tables (a SEPARATE database, so this is a best-effort secondary write
on its own connection — it must NEVER fail the primary booking).

Idempotency: `entry_uid` is derived deterministically from the trades_* row's
identity (deal_ref + effective_start), so an insert retried for the same
version dedups via `ON CONFLICT (entry_uid) DO NOTHING`.

Row-building here is pure (no DB) and unit-testable. The two OPEN-DECISION
inputs — the refdata exchange codename, and (for cashflow) the manual_cashflow
`kind` — are passed IN, not guessed here (see refdata_db.exchange_codename and
the cashflow_type→kind mapping, both still to be decided).
"""
from __future__ import annotations
import uuid
from decimal import Decimal

import sys

import refdata_db
import t2x_mysql
import tech_db

_NS = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")  # fixed namespace for uuid5

_STATUS = {
    "PENDING": "pending",
    "CONFIRMED": "confirmed",
    "PROCESSED": "processed",
    "SETTLED": "settled",
    "CANCELLED": "cancelled",
}


# ── pure helpers ────────────────────────────────────────────────────────────
def map_status(tms_status: str) -> str:
    s = (tms_status or "").strip().upper()
    if s not in _STATUS:
        raise ValueError(f"unknown TMS status {tms_status!r}")
    return _STATUS[s]


def map_trade_side(direction: str) -> str:
    """Spot direction → manual_trade_side. LONG/BUY → buy, SHORT/SELL → sell."""
    d = (direction or "").strip().upper()
    if d in ("LONG", "BUY"):
        return "buy"
    if d in ("SHORT", "SELL"):
        return "sell"
    raise ValueError(f"unknown trade direction {direction!r}")


# manual_cashflow.kind is 1:1 with TMS cashflow_type (stored verbatim). Must stay
# in sync with the manual_cashflow_kind enum in migrations/0001_*.sql and with
# cashflow_db.VALID_CASHFLOW_TYPES.
VALID_CASHFLOW_KINDS = {
    "INTER PTF FUNDING", "RETAINER FEES", "OPEX", "OPEX - OTHER EXPENSE",
    "OPEX - CONTRA ACC", "OTHER INCOME", "OTHER EXPENSE", "TRANSFER FEES",
    "TRADING FEES", "TRADING REWARDS", "STRATEGY TESTING EXPENSE",
    "STRATEGY TESTING RETURNED", "INTEREST EXPENSE", "INTEREST INCOME",
    "WITHHOLDING TAX", "LOAN", "LOAN REPAYMENT", "MARGIN LOAN",
    "MARGIN REPAYMENT", "MARGIN SETTLEMENT",
}


def map_cashflow_kind(cashflow_type: str, direction: str = None) -> str:
    """TMS cashflow_type -> manual_cashflow_kind, 1:1 verbatim (validated).

    `direction` is unused (kept for signature stability); amount sign is derived
    from direction separately in build_manual_cashflow_row.
    """
    t = (cashflow_type or "").strip().upper()
    if t not in VALID_CASHFLOW_KINDS:
        raise ValueError(f"unknown cashflow_type {cashflow_type!r}")
    return t


def counterparty_id_int(row: dict) -> int | None:
    """'CID000056' → 56 (reference_data.counterparty.id). None/'' → None."""
    v = row.get("counterparty_id")
    if v in (None, ""):
        return None
    s = str(v).strip().upper()
    if s.startswith("CID"):
        s = s[3:]
    try:
        return int(s)
    except ValueError:
        return None


def portfolio_id_int(row: dict) -> int | None:
    """Payload portfolio_id is the portfolio NUMBER (text) — store as int. None if absent."""
    v = row.get("portfolio_id")
    if v in (None, ""):
        return None
    try:
        return int(str(v).strip())
    except ValueError:
        return None


def _entry_uid(table: str, deal_ref: str, effective_start) -> str:
    return str(uuid.uuid5(_NS, f"{table}|{deal_ref}|{effective_start}"))


def _dec(v):
    return None if v in (None, "") else Decimal(str(v))


def _fee(fee_amount, fee_asset_id):
    """Normalize a fee: a zero/absent amount means 'no fee' -> (None, None).

    trades_* default fee_amount to '0' when absent, but the manual_* CHECK
    requires a fee_asset whenever fee_amount is non-null; a bare 0 with no asset
    would violate it, so collapse it to NULL/NULL.
    """
    amt = _dec(fee_amount)
    if not amt:
        return None, None
    return amt, fee_asset_id


# ── row builders (pure) ─────────────────────────────────────────────────────
def build_manual_trade_row(
    row: dict,
    *,
    account_id: str,
    base_asset_id: int,
    quote_asset_id: int,
    fee_asset_id: int | None,
) -> dict:
    """Build a manual_trade column dict from a resolved trades_spot row.

    `row` is spot_db.row_to_payload(...) of the RETURNING * insert (carries the
    DB-generated deal_ref + effective_start). `account_id` (account_exchange.id
    + '001') and the refdata asset ids are passed in already resolved.
    """
    deal_ref = row["deal_ref"]
    eff_start = row.get("effective_start")
    fee_amt, fee_asset_id = _fee(row.get("fee_amount"), fee_asset_id)
    return {
        "entry_uid": _entry_uid("manual_trade", deal_ref, eff_start),
        "deal_ref": deal_ref,
        "external_trade_id": row.get("external_trade_id"),
        "instrument_id": None,  # OTC spot
        "account_id": account_id,
        "base_asset_id": base_asset_id,
        "quote_asset_id": quote_asset_id,
        "fee_asset_id": fee_asset_id,
        "portfolio_id": portfolio_id_int(row),
        "counterparty_id": counterparty_id_int(row),
        "raw_symbol": None,
        "side": map_trade_side(row.get("direction")),
        "quantity": _dec(row.get("base_amount")),
        "price": _dec(row.get("price")),
        "quote_amount": _dec(row.get("quote_amount")),
        "fee_amount": fee_amt,
        "status": map_status(row.get("status")),
        "ts_exchange_event": row.get("trade_date"),
        "value_date": row.get("value_date"),
        "effective_date_start": eff_start,
        "effective_date_end": row.get("effective_end"),
        "entity": row.get("entity"),
        "txid_reference": row.get("txid_reference"),
        "booked_by": row.get("user_id"),
        "comment": row.get("comment"),
    }


def build_manual_cashflow_row(
    row: dict,
    *,
    account_id: str,
    asset_id: int,
    fee_asset_id: int | None,
    kind: str,
) -> dict:
    """Build a manual_cashflow column dict from a resolved trades_cashflow row.

    `account_id` and `kind` are passed in resolved. `amount` sign:
    INCOMING → +, OUTGOING → −.
    """
    deal_ref = row["deal_ref"]
    eff_start = row.get("effective_start")
    fee_amt, fee_asset_id = _fee(row.get("fee_amount"), fee_asset_id)
    amount = _dec(row.get("amount"))
    if amount is not None:
        direction = (row.get("direction") or "").strip().upper()
        mag = abs(amount)
        if direction == "INCOMING":
            amount = mag
        elif direction == "OUTGOING":
            amount = -mag
        # else: leave as-provided (signed already)
    return {
        "entry_uid": _entry_uid("manual_cashflow", deal_ref, eff_start),
        "deal_ref": deal_ref,
        "external_trade_id": row.get("external_trade_id"),
        "account_id": account_id,
        "asset_id": asset_id,
        "fee_asset_id": fee_asset_id,
        "portfolio_id": portfolio_id_int(row),
        "counterparty_id": counterparty_id_int(row),
        "kind": kind,
        "amount": amount,
        "fee_amount": fee_amt,
        "status": map_status(row.get("status")),
        "ts_exchange_event": row.get("trade_date"),
        "value_date": row.get("value_date"),
        "effective_date_start": eff_start,
        "effective_date_end": row.get("effective_end"),
        "network": row.get("network"),
        "entity": row.get("entity"),
        "txid_reference": row.get("txid_reference"),
        "booked_by": row.get("user_id"),
        "comment": row.get("comment"),
    }


# ── id resolution (refdata) ──────────────────────────────────────────────────
def resolve_trade_asset_ids(cur, row: dict) -> dict:
    """base/quote/fee asset ids from a trades_spot row (fee id only when fee>0)."""
    base = refdata_db.resolve_asset_id(cur, row.get("base_asset"))
    quote = refdata_db.resolve_asset_id(cur, row.get("quote_asset"))
    fee = None
    if _dec(row.get("fee_amount")):
        fee = refdata_db.resolve_asset_id(cur, row.get("fee_asset"))
    if base is None or quote is None:
        raise ValueError(
            f"unresolved asset(s): base={row.get('base_asset')} quote={row.get('quote_asset')}"
        )
    return {"base_asset_id": base, "quote_asset_id": quote, "fee_asset_id": fee}


def resolve_cashflow_asset_ids(cur, row: dict) -> dict:
    asset = refdata_db.resolve_asset_id(cur, row.get("asset"))
    fee = None
    if _dec(row.get("fee_amount")):
        fee = refdata_db.resolve_asset_id(cur, row.get("fee_asset"))
    if asset is None:
        raise ValueError(f"unresolved asset: {row.get('asset')}")
    return {"asset_id": asset, "fee_asset_id": fee}


# ── best-effort insert into the tech DB ──────────────────────────────────────
def _insert(cur, table: str, coldict: dict) -> None:
    cols = list(coldict.keys())
    ph = ", ".join(["%s"] * len(cols))
    cur.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({ph}) "
        f"ON CONFLICT (entry_uid) DO NOTHING",
        [coldict[c] for c in cols],
    )


def insert_manual_trade(cur, coldict: dict) -> None:
    _insert(cur, "manual_trade", coldict)


def insert_manual_cashflow(cur, coldict: dict) -> None:
    _insert(cur, "manual_cashflow", coldict)


# ── best-effort orchestrators (called by the booking hooks) ──────────────────
# These open their OWN connections (manual_* live in a different DB than
# trades_*), resolve → build → insert, and swallow every error so the primary
# booking is NEVER affected. They return True if a manual_* row was written.

def _log(msg: str) -> None:
    print(f"manual dual-write: {msg}", file=sys.stderr)


def enabled() -> bool:
    """True only when the tech DB is configured — TECH_DB_URL (full DSN, how the
    deployment injects it) OR TECH_DB_* / `# TECH DB` split creds. Lets envs
    without the sink skip the dual-write silently."""
    return tech_db.configured()


def write_manual_trade(row: dict) -> bool:
    """Mirror a trades_spot row into manual_trade. Best-effort; never raises."""
    if not enabled():
        return False
    ref = None
    tech = None
    try:
        account_id = None
        with t2x_mysql.connect() as my:
            account_id = t2x_mysql.resolve_account_id(my.cursor(), row.get("account"))
        if account_id is None:
            _log(f"skip manual_trade {row.get('deal_ref')}: account {row.get('account')!r} not in account_exchange")
            return False

        ref = refdata_db.connect()
        ids = resolve_trade_asset_ids(ref.cursor(), row)

        coldict = build_manual_trade_row(
            row, account_id=account_id, **ids
        )
        tech = tech_db.connect()
        with tech:
            with tech.cursor() as cur:
                insert_manual_trade(cur, coldict)
        _log(f"wrote manual_trade {row.get('deal_ref')} (account_id={account_id})")
        return True
    except Exception as e:  # noqa: BLE001 — best-effort, must not fail booking
        _log(f"skip manual_trade {row.get('deal_ref')}: {e!r}")
        return False
    finally:
        for c in (ref, tech):
            try:
                if c is not None:
                    c.close()
            except Exception:
                pass


def write_manual_cashflow(row: dict) -> bool:
    """Mirror a trades_cashflow row into manual_cashflow. Best-effort; never raises."""
    if not enabled():
        return False
    ref = None
    tech = None
    try:
        account_id = None
        with t2x_mysql.connect() as my:
            account_id = t2x_mysql.resolve_account_id(my.cursor(), row.get("account"))
        if account_id is None:
            _log(f"skip manual_cashflow {row.get('deal_ref')}: account {row.get('account')!r} not in account_exchange")
            return False

        ref = refdata_db.connect()
        ids = resolve_cashflow_asset_ids(ref.cursor(), row)
        kind = map_cashflow_kind(row.get("cashflow_type"), row.get("direction"))

        coldict = build_manual_cashflow_row(
            row, account_id=account_id, kind=kind, **ids
        )
        tech = tech_db.connect()
        with tech:
            with tech.cursor() as cur:
                insert_manual_cashflow(cur, coldict)
        _log(f"wrote manual_cashflow {row.get('deal_ref')} (account_id={account_id}, kind={kind})")
        return True
    except Exception as e:  # noqa: BLE001 — best-effort, must not fail booking
        _log(f"skip manual_cashflow {row.get('deal_ref')}: {e!r}")
        return False
    finally:
        for c in (ref, tech):
            try:
                if c is not None:
                    c.close()
            except Exception:
                pass


# ── amend (SCD2 supersede) ───────────────────────────────────────────────────
# Every TMS amend — including cancel (an amend with status='CANCELLED') — closes
# the prior trades_* version and inserts a new version (same deal_ref). Mirror it
# into manual_*: close the prior OPEN manual_* row (effective_date_end = the new
# version's effective_start) and insert the new version, staying open. The new
# entry gets its own deterministic entry_uid (the position service's dedup key);
# position reads the current version via effective_date_start/end. Status carries
# through (cancelled for a cancel, otherwise the amended status).

def _supersede(row: dict, *, table: str, insert_fn, coldict_fn) -> bool:
    """Best-effort amend/cancel mirror; never raises. True if a new version was written."""
    if not enabled():
        return False
    ref = None
    tech = None
    deal_ref = row.get("deal_ref")
    try:
        with t2x_mysql.connect() as my:
            account_id = t2x_mysql.resolve_account_id(my.cursor(), row.get("account"))
        if account_id is None:
            _log(f"skip {table} amend {deal_ref}: account {row.get('account')!r} not in account_exchange")
            return False

        ref = refdata_db.connect()
        rcur = ref.cursor()
        tech = tech_db.connect()
        with tech:
            with tech.cursor() as cur:
                # close the prior open version FIRST (keeps one-open-per-deal_ref)
                cur.execute(
                    f"UPDATE {table} SET effective_date_end = %s "
                    f"WHERE deal_ref = %s AND effective_date_end IS NULL "
                    f"RETURNING id",
                    (row.get("effective_start"), deal_ref),
                )
                prior = cur.fetchone()
                if prior is None:
                    _log(f"skip {table} amend {deal_ref}: no open row to supersede")
                    return False
                coldict = coldict_fn(rcur, account_id)
                insert_fn(cur, coldict)
        _log(f"superseded {table} {deal_ref} (reverses id={int(prior[0])}, account_id={account_id}, status={row.get('status')})")
        return True
    except Exception as e:  # noqa: BLE001 — best-effort, must not fail booking
        _log(f"skip {table} amend {deal_ref}: {e!r}")
        return False
    finally:
        for c in (ref, tech):
            try:
                if c is not None:
                    c.close()
            except Exception:
                pass


def write_manual_trade_amend(row: dict) -> bool:
    """Mirror any trades_spot amend (incl. cancel) into a new manual_trade version."""
    def build(rcur, account_id):
        ids = resolve_trade_asset_ids(rcur, row)
        return build_manual_trade_row(row, account_id=account_id, **ids)
    return _supersede(row, table="manual_trade", insert_fn=insert_manual_trade, coldict_fn=build)


def write_manual_cashflow_amend(row: dict) -> bool:
    """Mirror any trades_cashflow amend (incl. cancel) into a new manual_cashflow version."""
    def build(rcur, account_id):
        ids = resolve_cashflow_asset_ids(rcur, row)
        kind = map_cashflow_kind(row.get("cashflow_type"), row.get("direction"))
        return build_manual_cashflow_row(
            row, account_id=account_id, kind=kind, **ids
        )
    return _supersede(row, table="manual_cashflow", insert_fn=insert_manual_cashflow, coldict_fn=build)
