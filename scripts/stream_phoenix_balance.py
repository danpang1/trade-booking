"""Phoenix Eternal balance snapshot collector → middle_office.tq_hist_balance_mo.

Pulls /trader/{WALLET}/state?pdaIndex=0 and writes, per active sub-account:

  (1) ONE USDC equity row (instrument='USDC', total_qty=portfolioValue.ui)
      → the account net equity / MTM (collateral + UPnL + funding).
  (2) ONE INST_TYPE_PERP row per open position (mirrors Hyperliquid's
      convention of duplicating positions into the balance table).

Convention
----------
- Public read-only API (no auth).
- Wallet `EibQ2VYpzj18qSdEBkmxWVzde7FzamTxVG9rZyY689Yj` (8023 - CDA SOL desk).
- Three trader sub-accounts (traderSubaccountIndex 0/1/2) → account_id 216002, names TRADING01@PHOENIX-1/-2/-3.
- Equity row total_qty = `portfolioValue.ui`  (collateral + uPnL, MTM, USDC).
- Equity row avail_qty = `effectiveCollateralForWithdrawals.ui`.
- Position rows total_qty = abs(positionSize.ui), side=long/short by sign,
  instrument='{symbol}-P/USDC@PHOENIX_FUTURES'.
- borrowed_qty / interest_qty = NULL on position rows (matches HL).

Run
---
    python "Snapshot MO/scripts/stream_phoenix_balance.py" --once --dry-run
    python "Snapshot MO/scripts/stream_phoenix_balance.py" --once
    python "Snapshot MO/scripts/stream_phoenix_balance.py" --interval 5
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
PHOENIX_API = "https://perp-api.phoenix.trade"
WALLET = "EibQ2VYpzj18qSdEBkmxWVzde7FzamTxVG9rZyY689Yj"
PDA_INDEX = 0
EXCH = "PHOENIX_FUTURES"

# traderSubaccountIndex → (MO account_id, account_name)
ACCOUNT_MAP: dict[int, dict] = {
    0: {"account_id": 216002, "name": "TRADING01@PHOENIX-1"},
    1: {"account_id": 216002, "name": "TRADING01@PHOENIX-2"},
    2: {"account_id": 216002, "name": "TRADING01@PHOENIX-3"},
}

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV = REPO_ROOT / ".env"

log = logging.getLogger("stream_phoenix_balance")


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
# Phoenix fetch + normalize
# ─────────────────────────────────────────────────────────────────────

def _fetch_state(pda_index: int) -> dict:
    url = f"{PHOENIX_API}/trader/{WALLET}/state?pdaIndex={pda_index}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def _ui_float(field: dict | None) -> float:
    if not field:
        return 0.0
    ui = field.get("ui")
    if ui is not None:
        return float(ui)
    val = field.get("value", 0)
    dec = field.get("decimals", 0)
    return float(val) / (10 ** dec) if dec else float(val)


def normalize_equity(account_id: int, account_name: str,
                     fetch_dt: datetime, trader: dict) -> dict:
    """One USDC equity (MTM) row per trader sub-account.

    Strips the heavy `positions` array from original_data — those get their
    own rows below — so the equity JSON stays compact.
    """
    portfolio = _ui_float(trader.get("portfolioValue"))
    eff_wd = _ui_float(trader.get("effectiveCollateralForWithdrawals"))
    raw = {k: v for k, v in trader.items() if k != "positions"}
    return {
        "account_id": account_id,
        "account_name": account_name,
        "exch": EXCH,
        "instrument": "USDC",
        "instrument_type": "INST_TYPE_SPOT",
        "side": "long",
        "total_qty": portfolio,
        "avail_qty": eff_wd,
        "frozen_qty": 0,
        "instrument_mo": "USDC",
        "instrument_exch": "USDC",
        "sync_ts": fetch_dt.replace(tzinfo=None),
        "update_ts": fetch_dt.replace(tzinfo=None),
        "original_data": json.dumps(raw),
        "borrowed_qty": 0,
        "interest_qty": 0,
    }


def normalize_position_row(account_id: int, account_name: str,
                           fetch_dt: datetime, raw: dict) -> dict | None:
    """One INST_TYPE_PERP balance row per open Phoenix position."""
    symbol = raw.get("symbol", "")
    size = _ui_float(raw.get("positionSize"))
    if size == 0:
        return None
    abs_size = abs(size)
    side = "long" if size > 0 else "short"
    return {
        "account_id": account_id,
        "account_name": account_name,
        "exch": EXCH,
        "instrument": f"{symbol}-P/USDC@{EXCH}" if symbol else "",
        "instrument_type": "INST_TYPE_PERP",
        "side": side,
        "total_qty": abs_size,
        "avail_qty": abs_size,
        "frozen_qty": 0,
        "instrument_mo": f"{symbol}USDC" if symbol else "",
        "instrument_exch": symbol,
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
    try:
        st = _fetch_state(PDA_INDEX)
    except Exception as e:
        log.error(f"state fetch failed: {e}")
        return 0

    rows: list[dict] = []
    for trader in st.get("traders", []):
        sub_idx = trader.get("traderSubaccountIndex")
        meta = ACCOUNT_MAP.get(sub_idx)
        if meta is None:
            log.warning(f"unmapped traderSubaccountIndex={sub_idx}, skipping")
            continue
        rows.append(normalize_equity(meta["account_id"], meta["name"], fetch_dt, trader))
        positions = trader.get("positions", [])
        pos_kept = 0
        for p in positions:
            row = normalize_position_row(meta["account_id"], meta["name"], fetch_dt, p)
            if row:
                rows.append(row)
                pos_kept += 1
        log.info(f"sub{sub_idx} ({meta['name']}): equity + {pos_kept}/{len(positions)} positions")

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
    ap = argparse.ArgumentParser(description="Phoenix Eternal balance snapshot collector")
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
    log.info(f"mode={mode} dry_run={args.dry_run} wallet={WALLET[:8]}…")

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
