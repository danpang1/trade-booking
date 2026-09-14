"""Bulk (Solana-native perps DEX) position snapshot collector → middle_office.tq_hist_position_mo.

Pulls `POST /account {type: fullAccount}` for each mapped master pubkey and
writes one row per open position.

Convention
----------
- Public read-only API (no auth, no signature) — https://docs.bulk.trade/api-reference/getAccount
- Master pubkey `EibQ2VYpzj18qSdEBkmxWVzde7FzamTxVG9rZyY689Yj` → MO account_id 235002
  (reference_data.account_exchange id 235, TRADING_01@BULK, exchangeName BULK).
- USDC-margined perps; `size` signed (positive = long, negative = short).
- `pos_qty` = abs(size); side from sign.
- `avg_entry_price` = `price`; `last_trade_price` = `fairPrice` (Bulk mark).
- `unsettled_pnl` = `unrealizedPnl`.
- `margin` = `maintenanceMargin` — Bulk's account `marginUsed` is Σ of these,
  so it's the venue's own notion of margin consumed per position.
- `liquidation_price` NULL when Bulk returns 0.0.
- `index_price` NULL (not returned).
- No account-level timestamp in the payload → update_ts = sync_ts.
- Sub-accounts (`subAccounts[]` on the master) are snapped separately if
  mapped in ACCOUNT_MAP; unmapped ones are logged and skipped.
- Per-instrument isolated positions arrive inline on the parent (`iso=true`)
  and are recorded under the parent account.

Run
---
    python scripts/stream_bulk.py --once --dry-run
    python scripts/stream_bulk.py --once
    python scripts/stream_bulk.py --hourly
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
BULK_API = "https://mainnet-api1.bulk.trade/api/v1"
# Bulk's edge 403s the default `Python-urllib/x.y` UA; any other UA is fine.
USER_AGENT = "trade-booking-snapshots/1.0"
EXCH = "BULK_FUTURES"

# Bulk pubkey → (MO account_id, account_name). Masters are queried directly;
# any `subAccounts[]` returned on a master are looked up here too.
ACCOUNT_MAP: dict[str, dict] = {
    "EibQ2VYpzj18qSdEBkmxWVzde7FzamTxVG9rZyY689Yj": {
        "account_id": 235002, "name": "TRADING_01@BULK",
    },
}
MASTERS = list(ACCOUNT_MAP)

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV = REPO_ROOT / ".env"

log = logging.getLogger("stream_bulk")


# ─────────────────────────────────────────────────────────────────────
# Bulk fetch + normalize
# ─────────────────────────────────────────────────────────────────────

def _post(path: str, body: dict) -> list | dict:
    req = urllib.request.Request(
        f"{BULK_API}{path}",
        data=json.dumps(body).encode(),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def _f(s: str | float | None, default: float | None = 0.0) -> float | None:
    if s in (None, ""):
        return default
    try:
        return float(s)
    except (TypeError, ValueError):
        return default


def _fetch_account(pubkey: str) -> dict | None:
    """Return the inner `fullAccount` object for a master / sub-account pubkey.

    Response is a list of externally-tagged objects; an unknown pubkey comes
    back as `{"error": {"code": "ACCOUNT_NOT_FOUND", ...}}`.
    """
    r = _post("/account", {"type": "fullAccount", "user": pubkey})
    if isinstance(r, dict) and r.get("error"):
        raise RuntimeError(f"{r['error'].get('code')}: {r['error'].get('message')}")
    for item in r or []:
        if isinstance(item, dict) and "fullAccount" in item:
            return item["fullAccount"]
    return None


def normalize_position(account_id: int, account_name: str,
                       fetch_dt: datetime, raw: dict) -> dict | None:
    symbol_exch = raw.get("symbol") or ""
    symbol = symbol_exch.split("-")[0]   # "BTC-USD" → "BTC"
    size = _f(raw.get("size"), 0.0)
    if not size:
        return None
    side = "long" if size > 0 else "short"

    entry = _f(raw.get("price"))
    mark = _f(raw.get("fairPrice"))
    upnl = _f(raw.get("unrealizedPnl"))
    liq = _f(raw.get("liquidationPrice"), None)
    if not liq:
        liq = None
    leverage = _f(raw.get("leverage"), None)
    margin = _f(raw.get("maintenanceMargin"), None)

    return {
        "account_id": account_id,
        "account_name": account_name,
        "exch": EXCH,
        "instrument": f"{symbol}-P/USDC@{EXCH}" if symbol else "",
        "instrument_type": "INST_TYPE_PERP",
        "side": side,
        "contract_size": 1,
        "pos_qty": abs(size),
        "unsettled_pnl": upnl,
        "avg_entry_price": entry,
        "index_price": None,
        "last_trade_price": mark,
        "leverage": leverage,
        "liquidation_price": liq,
        "margin": margin,
        "instrument_mo": f"{symbol}USDC" if symbol else "",
        "instrument_exch": symbol_exch,
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


def _iter_accounts():
    """Yield (pubkey, fullAccount) for each master, then its mapped sub-accounts.

    Sub-accounts are discovered from the master's `subAccounts[]`; unmapped
    ones are logged and skipped so we never write under a wrong account_id.
    """
    for master in MASTERS:
        try:
            acc = _fetch_account(master)
        except Exception as e:
            log.error(f"account fetch failed for {master[:8]}…: {e}")
            continue
        if not acc:
            log.warning(f"account {master[:8]}…: no fullAccount body")
            continue
        yield master, acc
        for sub in acc.get("subAccounts") or []:
            pk = sub.get("pubkey") if isinstance(sub, dict) else sub
            if pk not in ACCOUNT_MAP:
                log.warning(f"unmapped Bulk sub-account {pk} under {master[:8]}…, skipping")
                continue
            try:
                sub_acc = _fetch_account(pk)
            except Exception as e:
                log.error(f"sub-account fetch failed for {pk[:8]}…: {e}")
                continue
            if sub_acc:
                yield pk, sub_acc


def snap_once(conn, dry_run: bool) -> int:
    fetch_dt = datetime.now(timezone.utc)
    rows: list[dict] = []
    for pk, acc in _iter_accounts():
        meta = ACCOUNT_MAP[pk]
        positions = acc.get("positions") or []
        kept = 0
        for p in positions:
            row = normalize_position(meta["account_id"], meta["name"], fetch_dt, p)
            if row:
                rows.append(row)
                kept += 1
        log.info(f"{meta['name']}: {kept}/{len(positions)} open positions")

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
    ap = argparse.ArgumentParser(description="Bulk position snapshot collector")
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
    log.info(f"mode={mode} dry_run={args.dry_run} masters={[m[:8] + '…' for m in MASTERS]}")

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
