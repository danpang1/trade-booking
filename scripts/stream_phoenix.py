"""Phoenix Eternal position snapshot collector → middle_office.tq_hist_position_mo.

Pulls /trader/{WALLET}/state?pdaIndex=0 and writes one row per open position
across all active trader sub-accounts.

Convention
----------
- Public read-only API (no auth).
- Wallet `EibQ2VYpzj18qSdEBkmxWVzde7FzamTxVG9rZyY689Yj` (8023 - CDA SOL desk).
- Three trader sub-accounts (traderSubaccountIndex 0, 1, 2); each maps to its
  account_id 216002, names TRADING01@PHOENIX-1/-2/-3 via ACCOUNT_MAP.
- `last_trade_price` derived: |positionValue| / |positionSize|.
- `margin` = position-level `initialMargin.ui`.
- `leverage` derived: |positionValue| / initialMargin.
- `index_price`, `liquidation_price` are NULL (not returned by Phoenix).

Run
---
    python "Snapshot MO/scripts/stream_phoenix.py" --once --dry-run
    python "Snapshot MO/scripts/stream_phoenix.py" --once
    python "Snapshot MO/scripts/stream_phoenix.py" --interval 5
"""
from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
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

log = logging.getLogger("stream_phoenix")


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
    """Phoenix returns {value, decimals, ui}; prefer the pre-formatted ui."""
    if not field:
        return 0.0
    ui = field.get("ui")
    if ui is not None:
        return float(ui)
    val = field.get("value", 0)
    dec = field.get("decimals", 0)
    return float(val) / (10 ** dec) if dec else float(val)


def normalize_position(account_id: int, account_name: str,
                       fetch_dt: datetime, raw: dict) -> dict | None:
    """Phoenix position dict → tq_hist_position_mo row. Returns None for flat."""
    symbol = raw.get("symbol", "")
    size = _ui_float(raw.get("positionSize"))
    if size == 0:
        return None

    entry = _ui_float(raw.get("entryPrice"))
    upnl = _ui_float(raw.get("unrealizedPnl"))
    pos_value = _ui_float(raw.get("positionValue"))
    init_margin = _ui_float(raw.get("initialMargin"))

    abs_size = abs(size)
    side = "long" if size > 0 else "short"
    mark = abs(pos_value) / abs_size if abs_size > 0 else None
    leverage = abs(pos_value) / init_margin if init_margin > 0 else None

    return {
        "account_id": account_id,
        "account_name": account_name,
        "exch": EXCH,
        "instrument": f"{symbol}-P/USDC@{EXCH}" if symbol else "",
        "instrument_type": "INST_TYPE_PERP",
        "side": side,
        "contract_size": 1,
        "pos_qty": abs_size,
        "unsettled_pnl": upnl,
        "avg_entry_price": entry,
        "index_price": None,
        "last_trade_price": mark,
        "leverage": leverage,
        "liquidation_price": None,
        "margin": init_margin if init_margin > 0 else None,
        "instrument_mo": f"{symbol}USDC" if symbol else "",
        "instrument_exch": symbol,
        "sync_ts": fetch_dt.replace(tzinfo=None),
        "update_ts": fetch_dt.replace(tzinfo=None),
        "original_data": json.dumps(raw),
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
        positions = trader.get("positions", [])
        for p in positions:
            row = normalize_position(meta["account_id"], meta["name"], fetch_dt, p)
            if row:
                rows.append(row)
        log.info(f"sub{sub_idx} ({meta['name']}): {len(positions)} positions")

    if dry_run:
        for r in rows:
            log.info(
                f"DRY {r['account_name']:30s} {r['instrument_mo']:10s} "
                f"{r['side']:5s} qty={r['pos_qty']:>14,.4f} "
                f"mark={r['last_trade_price']:>14,.6f} "
                f"upnl={r['unsettled_pnl']:>10,.2f}"
            )
        return len(rows)

    if conn and rows:
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, INSERT_SQL, rows)
        conn.commit()
        log.info(f"INSERTed {len(rows)} rows into tq_hist_position_mo")
    return len(rows)


def _sleep_until_next_hour(stop: dict) -> bool:
    """Block until the next UTC top-of-hour. Returns True if SIGINT'd."""
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
    ap = argparse.ArgumentParser(description="Phoenix Eternal position snapshot collector")
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
