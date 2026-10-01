"""Velocity (Solana perps DEX, Drift fork) balance snapshot collector → middle_office.tq_hist_balance_mo.

Pulls `GET /user/{accountId}` from the public Velocity Data API for every mapped
sub-account of the owner wallet and writes, per sub-account:

  (1) ONE USDT equity row (instrument='USDT', total_qty=account.balance)
      → the account net equity / MTM (collateral + uPnL on cross positions).
  (2) ONE INST_TYPE_SPOT row per NON-quote asset in `balances[]` (e.g. SOL /
      wBTC collateral or borrows) — negative balance = borrow → side='short',
      borrowed_qty=abs.
  (3) ONE INST_TYPE_PERP row per open position (mirrors the Lighter / Phoenix /
      Bulk convention of duplicating positions into the balance table).

Sub-accounts that are completely empty (zero equity, no balances, no
positions — tokka-labs-1..4 today) are skipped so the table isn't padded with
zero rows every hour; they start recording the moment anything lands in them.

Convention
----------
- Public read-only Data API (no auth) — https://docs.velocity.exchange/developers/data-api
- OWNER wallet `Dbre9pdVZqUzfqYcDFhySZxjJi8o4iw4qnSWVT1a3B55` is the on-chain
  authority; `EibQ2VYpzj18qSdEBkmxWVzde7FzamTxVG9rZyY689Yj` (desk key, same as
  Phoenix / Bulk) is only the DELEGATE and owns a dust sub-account of its own.
- Sub-accounts discovered via `/authority/{OWNER}/accounts`; must be in
  ACCOUNT_MAP (keyed by Velocity accountId) or they're warned + skipped.
- Equity row total_qty  = `account.balance`         (net equity incl. uPnL, USDT).
- Equity row avail_qty  = `account.freeCollateral`.
- Equity row frozen_qty = `account.initialMargin`   (margin consumed by positions).
- Equity original_data  = `account` block + `balances[]` (positions / orders stripped).
  The raw USDT spot balance (`balances[].balance`, excl. uPnL) lives there.
- Position rows total_qty = abs(baseAssetAmount), side by sign,
  instrument='{SYM}-P/USDT@VELOCITY_FUTURES'; borrowed/interest NULL.
- No account-level timestamp in the payload → update_ts = sync_ts.
- 429 / 5xx retried honouring Retry-After; a failed fetch RAISES so
  snapshot_all counts the task FAILED (never a silent `rows=0` gap).

Run
---
    python scripts/stream_velocity_balance.py --once --dry-run
    python scripts/stream_velocity_balance.py --once
    python scripts/stream_velocity_balance.py --hourly
"""
from __future__ import annotations

import argparse
import json
import logging
import signal
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras

import mo_db
# Shared venue plumbing (fetch, retry, discovery, account map) lives in the
# position collector so the two scripts can't drift apart.
from stream_velocity import (  # noqa: F401
    ACCOUNT_MAP, EXCH, OWNER, QUOTE, _check_account_ids, _f, _iter_accounts, is_empty,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
ENV = REPO_ROOT / ".env"

log = logging.getLogger("stream_velocity_balance")


# ─────────────────────────────────────────────────────────────────────
# normalize
# ─────────────────────────────────────────────────────────────────────

def normalize_equity(account_id: int, account_name: str,
                     fetch_dt: datetime, user: dict) -> dict:
    """One USDT equity (MTM) row per Velocity sub-account."""
    acct = user.get("account") or {}
    raw = {"account": acct, "balances": user.get("balances") or []}
    return {
        "account_id": account_id,
        "account_name": account_name,
        "exch": EXCH,
        "instrument": QUOTE,
        "instrument_type": "INST_TYPE_SPOT",
        "side": "long",
        "total_qty": _f(acct.get("balance")),
        "avail_qty": _f(acct.get("freeCollateral")),
        "frozen_qty": _f(acct.get("initialMargin")),
        "instrument_mo": QUOTE,
        "instrument_exch": QUOTE,
        "sync_ts": fetch_dt.replace(tzinfo=None),
        "update_ts": fetch_dt.replace(tzinfo=None),
        "original_data": json.dumps(raw),
        "borrowed_qty": 0,
        "interest_qty": 0,
    }


def normalize_asset_row(account_id: int, account_name: str,
                        fetch_dt: datetime, raw: dict) -> dict | None:
    """One INST_TYPE_SPOT row per non-quote asset in `balances[]`.

    The quote asset is covered by the equity row. A negative balance is a
    borrow against the account → side='short', borrowed_qty = abs.
    """
    symbol = raw.get("symbol") or ""
    bal = _f(raw.get("balance"), 0.0)
    if not symbol or symbol == QUOTE or not bal:
        return None
    abs_bal = abs(bal)
    is_borrow = bal < 0
    return {
        "account_id": account_id,
        "account_name": account_name,
        "exch": EXCH,
        "instrument": f"{symbol}@{EXCH}",
        "instrument_type": "INST_TYPE_SPOT",
        "side": "short" if is_borrow else "long",
        "total_qty": abs_bal,
        "avail_qty": abs_bal,
        "frozen_qty": 0,
        "instrument_mo": symbol,
        "instrument_exch": symbol,
        "sync_ts": fetch_dt.replace(tzinfo=None),
        "update_ts": fetch_dt.replace(tzinfo=None),
        "original_data": json.dumps(raw),
        "borrowed_qty": abs_bal if is_borrow else 0,
        "interest_qty": 0,
    }


def normalize_position_row(account_id: int, account_name: str,
                           fetch_dt: datetime, raw: dict) -> dict | None:
    """One INST_TYPE_PERP balance row per open Velocity position."""
    symbol_exch = raw.get("symbol") or ""
    symbol = symbol_exch.split("-")[0]
    size = _f(raw.get("baseAssetAmount"), 0.0)
    if not size:
        return None
    side = "long" if size > 0 else "short"
    abs_qty = abs(size)
    return {
        "account_id": account_id,
        "account_name": account_name,
        "exch": EXCH,
        "instrument": f"{symbol}-P/{QUOTE}@{EXCH}" if symbol else "",
        "instrument_type": "INST_TYPE_PERP",
        "side": side,
        "total_qty": abs_qty,
        "avail_qty": abs_qty,
        "frozen_qty": 0,
        "instrument_mo": f"{symbol}{QUOTE}" if symbol else "",
        "instrument_exch": symbol_exch,
        "sync_ts": fetch_dt.replace(tzinfo=None),
        "update_ts": fetch_dt.replace(tzinfo=None),
        "original_data": json.dumps(raw),
        "borrowed_qty": None,
        "interest_qty": None,
    }


# ─────────────────────────────────────────────────────────────────────
# INSERT
# ─────────────────────────────────────────────────────────────────────

INSERT_SQL = """
INSERT INTO tq_hist_balance_mo (
    account_id, account_name, exch, instrument, instrument_type, side,
    total_qty, avail_qty, frozen_qty, instrument_mo, instrument_exch,
    sync_ts, update_ts, original_data, borrowed_qty, interest_qty
) VALUES (
    %(account_id)s, %(account_name)s, %(exch)s, %(instrument)s, %(instrument_type)s, %(side)s,
    %(total_qty)s, %(avail_qty)s, %(frozen_qty)s, %(instrument_mo)s, %(instrument_exch)s,
    %(sync_ts)s, %(update_ts)s, %(original_data)s, %(borrowed_qty)s, %(interest_qty)s
)
"""


def snap_once(conn, dry_run: bool) -> int:
    fetch_dt = datetime.now(timezone.utc)
    rows: list[dict] = []
    for acc_id, meta, user in _iter_accounts():
        if is_empty(user):
            log.info(f"sub{meta['sub']} ({meta['name']}): empty, skipped")
            continue
        rows.append(normalize_equity(meta["account_id"], meta["name"], fetch_dt, user))
        assets = 0
        for b in user.get("balances") or []:
            row = normalize_asset_row(meta["account_id"], meta["name"], fetch_dt, b)
            if row:
                rows.append(row)
                assets += 1
        positions = user.get("positions") or []
        pos_kept = 0
        for p in positions:
            row = normalize_position_row(meta["account_id"], meta["name"], fetch_dt, p)
            if row:
                rows.append(row)
                pos_kept += 1
        log.info(
            f"sub{meta['sub']} ({meta['name']}): equity + {assets} assets + "
            f"{pos_kept}/{len(positions)} positions"
        )

    if dry_run:
        for r in rows:
            log.info(
                f"DRY {r['account_name']:30s} {r['instrument']:30s} "
                f"{r['instrument_type']:18s} {r['side']:5s} "
                f"total={r['total_qty']:>14,.4f}"
            )
        return len(rows)

    if conn and rows:
        _check_account_ids(rows)
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, INSERT_SQL, rows)
        conn.commit()
        log.info(f"INSERTed {len(rows)} rows into tq_hist_balance_mo")
    return len(rows)


def _sleep_until_next_hour(stop: dict) -> bool:
    now = datetime.now(timezone.utc)
    next_hr = (now.replace(minute=0, second=0, microsecond=0)
               + timedelta(hours=1))
    total = (next_hr - now).total_seconds()
    log.info(f"next snap at {next_hr.isoformat(timespec='seconds')} "
             f"(sleeping {int(total)}s)")
    deadline = time.monotonic() + total
    while time.monotonic() < deadline:
        if stop["flag"]:
            return True
        time.sleep(min(1.0, deadline - time.monotonic()))
    return False


def main() -> None:
    ap = argparse.ArgumentParser(description="Velocity balance snapshot collector")
    ap.add_argument("--interval", type=int, default=5,
                    help="Poll interval in seconds (ignored when --hourly is set; default: 5)")
    ap.add_argument("--hourly", action="store_true",
                    help="Snap at the top of every UTC hour (1am, 2am, 3am, ...)")
    ap.add_argument("--once", action="store_true", help="Run a single snap and exit")
    ap.add_argument("--dry-run", action="store_true", help="Print rows but don't INSERT")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    conn = None
    if not args.dry_run:
        conn = mo_db.connect()

    stop = {"flag": False}

    def handle_sig(*_):
        log.info("shutdown requested")
        stop["flag"] = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, handle_sig)
        except (OSError, ValueError):
            pass

    mode = "once" if args.once else ("hourly" if args.hourly else f"interval={args.interval}s")
    log.info(f"mode={mode} dry_run={args.dry_run} owner={OWNER[:8]}… subs={len(ACCOUNT_MAP)}")

    try:
        if args.once:
            snap_once(conn, args.dry_run)
            return
        if args.hourly:
            snap_once(conn, args.dry_run)
            while not stop["flag"]:
                if _sleep_until_next_hour(stop):
                    break
                try:
                    snap_once(conn, args.dry_run)
                except Exception as e:
                    log.error(f"snap_once failed: {e}")
            return
        while not stop["flag"]:
            try:
                snap_once(conn, args.dry_run)
            except Exception as e:
                log.error(f"snap_once failed: {e}")
            for _ in range(args.interval * 10):
                if stop["flag"]:
                    break
                time.sleep(0.1)
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    main()
