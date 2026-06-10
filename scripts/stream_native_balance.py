"""Native Core (spot-credit DEX) balance snapshot collector → middle_office.tq_hist_balance_mo.

Native Core exposes a single read-only `POST /info` gateway. A user is keyed by
wallet address. This collector writes, per snapshot:

  (1) ONE USD credit row (instrument='USD', total_qty=available_usd) capturing
      the spot-credit line (credit / available, full account in original_data).
  (2) ONE INST_TYPE_SPOT row per non-zero spot-credit position (actual_qty),
      mirroring the Lighter/Phoenix convention of duplicating holdings into the
      balance table. pending_exposure is preserved in original_data.
  (3) ONE row per non-zero plain spot-wallet balance (userBalances), if any.

Convention
----------
- Public read-only API (no auth). Mainnet host https://api.native.org (confirmed;
  docs only publish testnet api-test.native.org). POST /info, body {"type": ...}.
- Wallet `0xe71b2e6ddc88ffdecdcd0d750c57d0122aa586c2` → MO account_id 214004.
- Units: 8-dp. Position qtys use `actual_display` (already decimal); USD/spot
  atoms ÷ 1e8.
- Position qty basis = actual_qty only (settled). pending_exposure_qty is NOT
  added — kept in original_data for reference.
- update_ts = fetch time (Native /info has no per-account wall-clock); query_height
  stashed in original_data.

Run
---
    python scripts/stream_native_balance.py --once --dry-run
    python scripts/stream_native_balance.py --once
    python scripts/stream_native_balance.py --hourly
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
NATIVE_API = "https://api.native.org"
WALLET = "0xe71b2e6ddc88ffdecdcd0d750c57d0122aa586c2"
EXCH = "NATIVE CORE"
INSTR_VENUE = "NATIVECORE"          # instrument @suffix (no space)
ACCOUNT_ID = 214004
ACCOUNT_NAME = "TRADING_01@NATIVECORE"
USD_DP = 8                          # USD/spot atoms → ÷ 1e8

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV = REPO_ROOT / ".env"

log = logging.getLogger("stream_native_balance")


# ─────────────────────────────────────────────────────────────────────
# .env (MO DB block)
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
# Native /info fetch + normalize
# ─────────────────────────────────────────────────────────────────────

def post_info(body: dict, timeout: int = 20) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{NATIVE_API}/info", data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _atoms(s: str | int | None, dp: int = USD_DP) -> float:
    """integer-atom string → decimal float (÷ 10**dp)."""
    if s in (None, ""):
        return 0.0
    try:
        return float(s) / (10 ** dp)
    except (TypeError, ValueError):
        return 0.0


def _disp(s: str | float | None) -> float:
    """already-decimal display string → float."""
    if s in (None, ""):
        return 0.0
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def normalize_credit(fetch_dt: datetime, acct: dict, query_height) -> dict:
    """One USD credit row from spotCreditAccount."""
    avail = _atoms(acct.get("available_usd_atoms"))
    credit = _atoms(acct.get("credit_usd_atoms"))
    raw = dict(acct)
    raw["query_height"] = query_height
    return {
        "account_id": ACCOUNT_ID,
        "account_name": ACCOUNT_NAME,
        "exch": EXCH,
        "instrument": "USD",
        "instrument_type": "INST_TYPE_SPOT",
        "side": "long",
        "total_qty": avail,
        "avail_qty": avail,
        "frozen_qty": max(credit - avail, 0.0),   # drawn portion
        "instrument_mo": "USD",
        "instrument_exch": "USD",
        "sync_ts": fetch_dt.replace(tzinfo=None),
        "update_ts": fetch_dt.replace(tzinfo=None),
        "original_data": json.dumps(raw),
        "borrowed_qty": 0,
        "interest_qty": 0,
    }


def normalize_credit_position(fetch_dt: datetime, raw: dict) -> dict | None:
    """One INST_TYPE_SPOT row per non-zero spot-credit position (actual_qty)."""
    symbol = raw.get("symbol", "")
    qty = _disp(raw.get("actual_display"))
    if qty == 0:
        return None
    abs_qty = abs(qty)
    side = "long" if qty > 0 else "short"
    return {
        "account_id": ACCOUNT_ID,
        "account_name": ACCOUNT_NAME,
        "exch": EXCH,
        "instrument": f"{symbol}@{INSTR_VENUE}" if symbol else "",
        "instrument_type": "INST_TYPE_SPOT",
        "side": side,
        "total_qty": abs_qty,
        "avail_qty": abs_qty,
        "frozen_qty": 0,
        "instrument_mo": symbol,
        "instrument_exch": symbol,
        "sync_ts": fetch_dt.replace(tzinfo=None),
        "update_ts": fetch_dt.replace(tzinfo=None),
        "original_data": json.dumps(raw),
        "borrowed_qty": None,
        "interest_qty": None,
    }


def normalize_spot_balance(fetch_dt: datetime, raw: dict) -> dict | None:
    """One row per non-zero plain spot-wallet balance (userBalances)."""
    symbol = raw.get("symbol", "")
    avail = _atoms(raw.get("available"))
    locked = _atoms(raw.get("locked"))
    total = avail + locked
    if total == 0:
        return None
    return {
        "account_id": ACCOUNT_ID,
        "account_name": ACCOUNT_NAME,
        "exch": EXCH,
        "instrument": symbol,
        "instrument_type": "INST_TYPE_SPOT",
        "side": "long",
        "total_qty": total,
        "avail_qty": avail,
        "frozen_qty": locked,
        "instrument_mo": symbol,
        "instrument_exch": symbol,
        "sync_ts": fetch_dt.replace(tzinfo=None),
        "update_ts": fetch_dt.replace(tzinfo=None),
        "original_data": json.dumps(raw),
        "borrowed_qty": 0,
        "interest_qty": 0,
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

    # (1) USD credit line
    try:
        acct = post_info({"type": "spotCreditAccount", "user": WALLET})
        rows.append(normalize_credit(fetch_dt, acct, acct.get("query_height")))
    except Exception as e:
        log.error(f"spotCreditAccount failed: {e}")

    # (2) spot-credit positions
    pos_kept = 0
    try:
        pr = post_info({"type": "spotCreditPositions", "user": WALLET})
        positions = pr.get("spot_credit_positions", []) or []
        for p in positions:
            row = normalize_credit_position(fetch_dt, p)
            if row:
                rows.append(row)
                pos_kept += 1
        log.info(f"{ACCOUNT_NAME}: credit row + {pos_kept}/{len(positions)} positions")
    except Exception as e:
        log.error(f"spotCreditPositions failed: {e}")

    # (3) plain spot-wallet balances (usually empty)
    bal_kept = 0
    try:
        br = post_info({"type": "userBalances", "user": WALLET})
        balances = br.get("balances", []) or []
        for b in balances:
            row = normalize_spot_balance(fetch_dt, b)
            if row:
                rows.append(row)
                bal_kept += 1
        if balances:
            log.info(f"{ACCOUNT_NAME}: {bal_kept}/{len(balances)} spot-wallet balances")
    except Exception as e:
        log.error(f"userBalances failed: {e}")

    if dry_run:
        for r in rows:
            log.info(
                f"DRY {r['account_name']:22s} {r['instrument']:22s} "
                f"{r['instrument_type']:16s} {r['side']:5s} "
                f"total={r['total_qty']:>16,.4f}"
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
    ap = argparse.ArgumentParser(description="Native Core balance snapshot collector")
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
    log.info(f"mode={mode} dry_run={args.dry_run} wallet={WALLET[:10]}…")

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
