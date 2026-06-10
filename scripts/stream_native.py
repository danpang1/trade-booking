"""Native Core (spot-credit DEX) position snapshot collector → middle_office.tq_hist_position_mo.

Pulls spotCreditPositions via the read-only `POST /info` gateway and writes one
row per non-zero settled position (actual_qty).

Convention
----------
- Public read-only API (no auth). Mainnet host https://api.native.org. POST /info.
- Wallet `0xe71b2e6ddc88ffdecdcd0d750c57d0122aa586c2` → MO account_id 214004.
- pos_qty = signed actual_qty (settled). pending_exposure_qty kept in original_data.
- instrument_type = INST_TYPE_SPOT (tokenized spot assets, not perps).
- Native /info provides NO avg entry / mark / uPnL / margin for spot-credit
  positions, so those columns are NULL.
- update_ts = fetch time; query_height stashed in original_data.

Run
---
    python scripts/stream_native.py --once --dry-run
    python scripts/stream_native.py --once
    python scripts/stream_native.py --hourly
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
INSTR_VENUE = "NATIVECORE"
ACCOUNT_ID = 214004
ACCOUNT_NAME = "TRADING_01@NATIVECORE"

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV = REPO_ROOT / ".env"

log = logging.getLogger("stream_native")


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


def _disp(s: str | float | None) -> float:
    if s in (None, ""):
        return 0.0
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def normalize_position(fetch_dt: datetime, raw: dict, query_height) -> dict | None:
    symbol = raw.get("symbol", "")
    qty = _disp(raw.get("actual_display"))
    if qty == 0:
        return None
    side = "long" if qty > 0 else "short"
    data = dict(raw)
    data["query_height"] = query_height
    return {
        "account_id": ACCOUNT_ID,
        "account_name": ACCOUNT_NAME,
        "exch": EXCH,
        "instrument": f"{symbol}@{INSTR_VENUE}" if symbol else "",
        "instrument_type": "INST_TYPE_SPOT",
        "side": side,
        "contract_size": 1,
        "pos_qty": qty,
        "unsettled_pnl": None,
        "avg_entry_price": None,
        "index_price": None,
        "last_trade_price": None,
        "leverage": None,
        "liquidation_price": None,
        "margin": None,
        "instrument_mo": symbol,
        "instrument_exch": symbol,
        "sync_ts": fetch_dt.replace(tzinfo=None),
        "update_ts": fetch_dt.replace(tzinfo=None),
        "original_data": json.dumps(data),
    }


# ─────────────────────────────────────────────────────────────────────
# INSERT
# ─────────────────────────────────────────────────────────────────────

INSERT_SQL = """
INSERT INTO tq_hist_position_mo (
    account_id, account_name, exch, instrument, instrument_type, side,
    contract_size, pos_qty, unsettled_pnl, avg_entry_price, index_price,
    last_trade_price, leverage, liquidation_price, margin,
    instrument_mo, instrument_exch, sync_ts, update_ts, original_data
) VALUES (
    %(account_id)s, %(account_name)s, %(exch)s, %(instrument)s, %(instrument_type)s, %(side)s,
    %(contract_size)s, %(pos_qty)s, %(unsettled_pnl)s, %(avg_entry_price)s, %(index_price)s,
    %(last_trade_price)s, %(leverage)s, %(liquidation_price)s, %(margin)s,
    %(instrument_mo)s, %(instrument_exch)s, %(sync_ts)s, %(update_ts)s, %(original_data)s
)
"""


def snap_once(conn, dry_run: bool) -> int:
    fetch_dt = datetime.now(timezone.utc)
    try:
        pr = post_info({"type": "spotCreditPositions", "user": WALLET})
    except Exception as e:
        log.error(f"spotCreditPositions failed: {e}")
        return 0

    positions = pr.get("spot_credit_positions", []) or []
    rows: list[dict] = []
    for p in positions:
        row = normalize_position(fetch_dt, p, pr.get("query_height"))
        if row:
            rows.append(row)
    log.info(f"{ACCOUNT_NAME}: {len(rows)}/{len(positions)} non-zero positions")

    if dry_run:
        for r in rows:
            log.info(
                f"DRY {r['account_name']:22s} {r['instrument']:22s} "
                f"{r['side']:5s} qty={r['pos_qty']:>16,.6f}"
            )
        return len(rows)

    if conn and rows:
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, INSERT_SQL, rows)
        conn.commit()
        log.info(f"INSERTed {len(rows)} rows into tq_hist_position_mo")
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
    ap = argparse.ArgumentParser(description="Native Core position snapshot collector")
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
