"""Bitstamp (spot CEX) position snapshot collector → middle_office.tq_hist_position_mo.

Spot-only account: there are no derivative positions, so this mirrors the
Native/Lighter/Phoenix convention of recording each non-zero spot holding as a
long INST_TYPE_SPOT position. Source is the same signed v2 endpoint the balance
collector uses:
    POST /api/v2/account_balances/

Convention
----------
- Signed v2 HMAC-SHA256 API. Host www.bitstamp.net. Bodyless POST → NO
  Content-Type header (Bitstamp rejects it otherwise, API0020).
- account_name='MOON-TOKKA@BITSTAMP_SPOT', exch='BITSTAMP_SPOT', account_id=218001.
- pos_qty = total holding (positive → side 'long'). instrument='{CCY}@BITSTAMP'
  (currency upper-cased; raw kept in original_data).
- Spot holdings carry no mark/entry/uPnL/margin/leverage/liq, so those columns
  are NULL. The available/reserved split lives in the balance table, not here.

Credentials resolve by precedence via gw_creds: Vault agent-injected file
gw_218001.json (prod) → BITSTAMP_API_KEY / BITSTAMP_API_SECRET env → repo-root
.env MAIN.BITSTAMP_API_KEY / MAIN.BITSTAMP_API_SECRET (local dev). If none is
present, snap_once() warns and skips (returns 0) so the shared venue-snapshots
cron is never broken by a missing key. See docs/vault-credentials.md.

Run
---
    python scripts/stream_bitstamp.py --once --dry-run
    python scripts/stream_bitstamp.py --once
    python scripts/stream_bitstamp.py --hourly
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import signal
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

import psycopg2
import psycopg2.extras

import mo_db
import gw_creds


# ── Constants ──────────────────────────────────────────────────────────
BITSTAMP_HOST = "www.bitstamp.net"
BALANCES_PATH = "/api/v2/account_balances/"
EXCH = "BITSTAMP_SPOT"
INSTR_VENUE = "BITSTAMP_SPOT"
ACCOUNT_ID = 218001
ACCOUNT_NAME = "MOON-TOKKA@BITSTAMP_SPOT"

log = logging.getLogger("stream_bitstamp")


# ─────────────────────────────────────────────────────────────────────
# Credentials: Vault file → env (k8s Secret) → .env (local dev), via gw_creds
# ─────────────────────────────────────────────────────────────────────

def bitstamp_creds() -> tuple[str, str] | None:
    creds = gw_creds.find_gw_creds(
        ACCOUNT_ID, env_prefix="BITSTAMP",
        dotenv_key="MAIN.BITSTAMP_API_KEY",
        dotenv_secret="MAIN.BITSTAMP_API_SECRET",
    )
    return (creds.key, creds.secret) if creds else None


# ─────────────────────────────────────────────────────────────────────
# Bitstamp v2 signing + fetch
# ─────────────────────────────────────────────────────────────────────

def post_signed(key: str, secret: str, path: str, timeout: int = 20) -> object:
    """Bodyless signed POST. No Content-Type header (Bitstamp API0020)."""
    nonce = str(uuid.uuid4())
    timestamp = str(int(time.time() * 1000))
    msg = (
        "BITSTAMP " + key
        + "POST" + BITSTAMP_HOST + path
        + nonce + timestamp + "v2"
    )
    sig = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    headers = {
        "X-Auth": "BITSTAMP " + key,
        "X-Auth-Signature": sig,
        "X-Auth-Nonce": nonce,
        "X-Auth-Timestamp": timestamp,
        "X-Auth-Version": "v2",
    }
    # data=None so urllib omits Content-Type on this bodyless POST.
    req = urllib.request.Request(
        "https://" + BITSTAMP_HOST + path, data=None, headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _num(s: object) -> float:
    if s in (None, ""):
        return 0.0
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def normalize_position(fetch_dt: datetime, raw: dict) -> dict | None:
    ccy = (raw.get("currency") or "").upper()
    total = _num(raw.get("total"))
    if total == 0 or not ccy:
        return None
    return {
        "account_id": ACCOUNT_ID,
        "account_name": ACCOUNT_NAME,
        "exch": EXCH,
        "instrument": f"{ccy}@{INSTR_VENUE}",
        "instrument_type": "INST_TYPE_SPOT",
        "side": "long",
        "contract_size": 1,
        "pos_qty": total,
        "unsettled_pnl": None,
        "avg_entry_price": None,
        "index_price": None,
        "last_trade_price": None,
        "leverage": None,
        "liquidation_price": None,
        "margin": None,
        "instrument_mo": ccy,
        "instrument_exch": ccy,
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
    creds = bitstamp_creds()
    if creds is None:
        log.warning(
            "no Bitstamp creds (BITSTAMP_API_KEY/SECRET or MAIN.BITSTAMP_* in "
            ".env); skipping"
        )
        return 0
    key, secret = creds

    fetch_dt = datetime.now(timezone.utc)
    try:
        payload = post_signed(key, secret, BALANCES_PATH)
    except urllib.error.HTTPError as e:
        log.error(f"account_balances HTTP {e.code}: {e.read().decode()[:300]}")
        return 0
    except Exception as e:
        log.error(f"account_balances failed: {e}")
        return 0

    if isinstance(payload, dict) and payload.get("status") == "error":
        log.error(f"account_balances error: {payload}")
        return 0

    balances = payload if isinstance(payload, list) else []
    rows: list[dict] = []
    for b in balances:
        row = normalize_position(fetch_dt, b)
        if row:
            rows.append(row)
    log.info(f"{ACCOUNT_NAME}: {len(rows)}/{len(balances)} non-zero positions")

    if dry_run:
        for r in rows:
            log.info(
                f"DRY {r['account_name']:22s} {r['instrument']:18s} "
                f"{r['side']:5s} qty={r['pos_qty']:>18,.8f}"
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
    ap = argparse.ArgumentParser(description="Bitstamp position snapshot collector")
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
    log.info(f"mode={mode} dry_run={args.dry_run} account={ACCOUNT_NAME}")

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
