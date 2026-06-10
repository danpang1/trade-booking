"""Lighter (zkSync L2 perps) balance snapshot collector → middle_office.tq_hist_balance_mo.

Resolves sub-accounts by L1 address, then pulls /account?by=index for each
and writes:

  (1) ONE USDC equity row (instrument='USDC', total_qty=total_asset_value)
      → the account net equity / MTM (collateral + UPnL on cross positions).
  (2) ONE INST_TYPE_PERP row per open position (mirrors Hyperliquid's
      convention of duplicating positions into the balance table).

Convention
----------
- Public read-only API (no auth).
- L1 address `0xF8B5bde5f6aa989c01754931E077e1E5A915E2bB` (8023 - CDA SOL desk).
- One Lighter sub-account today (index 29911) → MO account_id 215002.
- Equity row total_qty = `total_asset_value` (MTM, USDC).
- Equity row avail_qty = `available_balance`.
- Position rows total_qty = abs(position), side=long/short by `sign`,
  instrument='{symbol}-P/USDC@LIGHTER_FUTURES'.
- borrowed_qty / interest_qty = NULL on position rows (matches HL).
- update_ts = account.transaction_time (μs epoch) for both row types.

Run
---
    python "Snapshot MO/scripts/stream_lighter_balance.py" --once --dry-run
    python "Snapshot MO/scripts/stream_lighter_balance.py" --once
    python "Snapshot MO/scripts/stream_lighter_balance.py" --interval 5
"""
from __future__ import annotations

import argparse
import json
import logging
import signal
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras

import mo_db


# ── Constants ──────────────────────────────────────────────────────────
LIGHTER_API = "https://mainnet.zklighter.elliot.ai/api/v1"
L1_ADDRESS = "0xF8B5bde5f6aa989c01754931E077e1E5A915E2bB"
EXCH = "LIGHTER_FUTURES"

ACCOUNT_MAP: dict[int, dict] = {
    29911: {"account_id": 215002, "name": "TRADING01@LIGHTER"},
}

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV = REPO_ROOT / ".env"

log = logging.getLogger("stream_lighter_balance")


# ─────────────────────────────────────────────────────────────────────
# .env
# ─────────────────────────────────────────────────────────────────────

def _env_block(marker: str) -> dict[str, str]:
    creds, in_block = {}, False
    for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s.startswith("#"):
            in_block = marker.upper() in s.upper()
            continue
        if not in_block or not s or ":" not in s:
            continue
        k, _, v = s.partition(":")
        key = k.strip().lower()
        if key.startswith("mo_db_"):
            key = key[len("mo_db_"):]
        creds[key] = v.strip()
    return creds


# ─────────────────────────────────────────────────────────────────────
# Lighter fetch + normalize
# ─────────────────────────────────────────────────────────────────────

def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def _f(s: str | float | None, default: float | None = 0.0) -> float | None:
    if s in (None, ""):
        return default
    try:
        return float(s)
    except (TypeError, ValueError):
        return default


def _resolve_subaccounts() -> list[dict]:
    r = _get(f"{LIGHTER_API}/accountsByL1Address?l1_address={L1_ADDRESS}")
    return r.get("sub_accounts") or []


def _fetch_account(index: int) -> dict | None:
    r = _get(f"{LIGHTER_API}/account?by=index&value={index}")
    accs = r.get("accounts") or []
    return accs[0] if accs else None


def normalize_equity(account_id: int, account_name: str,
                     fetch_dt: datetime, update_dt: datetime | None,
                     account: dict) -> dict:
    """One USDC equity (MTM) row per Lighter sub-account.

    Strips `positions` from original_data — those become separate rows below.
    """
    total_value = _f(account.get("total_asset_value"))
    avail = _f(account.get("available_balance"))
    raw = {k: v for k, v in account.items() if k != "positions"}
    return {
        "account_id": account_id,
        "account_name": account_name,
        "exch": EXCH,
        "instrument": "USDC",
        "instrument_type": "INST_TYPE_SPOT",
        "side": "long",
        "total_qty": total_value,
        "avail_qty": avail,
        "frozen_qty": 0,
        "instrument_mo": "USDC",
        "instrument_exch": "USDC",
        "sync_ts": fetch_dt.replace(tzinfo=None),
        "update_ts": (update_dt.replace(tzinfo=None) if update_dt else fetch_dt.replace(tzinfo=None)),
        "original_data": json.dumps(raw),
        "borrowed_qty": 0,
        "interest_qty": 0,
    }


def normalize_position_row(account_id: int, account_name: str,
                           fetch_dt: datetime, update_dt: datetime | None,
                           raw: dict) -> dict | None:
    """One INST_TYPE_PERP balance row per open Lighter position."""
    symbol = raw.get("symbol", "")
    qty = _f(raw.get("position"), 0.0)
    if not qty:
        return None
    sign = int(raw.get("sign") or 0)
    side = "long" if sign > 0 else "short"
    abs_qty = abs(qty)
    return {
        "account_id": account_id,
        "account_name": account_name,
        "exch": EXCH,
        "instrument": f"{symbol}-P/USDC@{EXCH}" if symbol else "",
        "instrument_type": "INST_TYPE_PERP",
        "side": side,
        "total_qty": abs_qty,
        "avail_qty": abs_qty,
        "frozen_qty": 0,
        "instrument_mo": f"{symbol}USDC" if symbol else "",
        "instrument_exch": symbol,
        "sync_ts": fetch_dt.replace(tzinfo=None),
        "update_ts": (update_dt.replace(tzinfo=None) if update_dt else fetch_dt.replace(tzinfo=None)),
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
    try:
        subs = _resolve_subaccounts()
    except Exception as e:
        log.error(f"accountsByL1Address failed: {e}")
        return 0

    rows: list[dict] = []
    for sub in subs:
        idx = sub.get("index")
        meta = ACCOUNT_MAP.get(idx)
        if meta is None:
            log.warning(f"unmapped Lighter sub-account index={idx}, skipping")
            continue
        try:
            acc = _fetch_account(idx)
        except Exception as e:
            log.error(f"account fetch failed for index={idx}: {e}")
            continue
        if not acc:
            log.warning(f"account index={idx}: no body")
            continue

        tx_us = int(acc.get("transaction_time") or 0)
        update_dt = (datetime.fromtimestamp(tx_us / 1_000_000, tz=timezone.utc)
                     if tx_us > 0 else None)

        rows.append(normalize_equity(meta["account_id"], meta["name"],
                                     fetch_dt, update_dt, acc))
        positions = acc.get("positions", [])
        pos_kept = 0
        for p in positions:
            row = normalize_position_row(meta["account_id"], meta["name"],
                                         fetch_dt, update_dt, p)
            if row:
                rows.append(row)
                pos_kept += 1
        log.info(f"sub{idx} ({meta['name']}): equity + {pos_kept}/{len(positions)} positions")

    if dry_run:
        for r in rows:
            log.info(
                f"DRY {r['account_name']:30s} {r['instrument']:30s} "
                f"{r['instrument_type']:18s} {r['side']:5s} "
                f"total={r['total_qty']:>14,.4f}"
            )
        return len(rows)

    if conn and rows:
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
    ap = argparse.ArgumentParser(description="Lighter balance snapshot collector")
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
    log.info(f"mode={mode} dry_run={args.dry_run} l1={L1_ADDRESS[:10]}…")

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
