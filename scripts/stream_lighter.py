"""Lighter (zkSync L2 perps) position snapshot collector → middle_office.tq_hist_position_mo.

Resolves sub-accounts by L1 address, then pulls /account?by=index for each
and writes one row per open position.

Convention
----------
- Public read-only API (no auth).
- L1 wallets in L1_ADDRESSES; an unfunded wallet has no Lighter account yet
  and is skipped (HTTP 400 / code 21100) without failing the other wallets.
- Sub-account index → MO account_id via ACCOUNT_MAP; index 29911 (wallet
  `0xF8B5bde5…`, 8023 CDA SOL desk) → 215002 TRADING01@LIGHTER. Unmapped
  indexes are warned + skipped so nothing is written under a wrong id.
- `last_trade_price` derived: |position_value| / |position|.
- `margin`:
    cross  (margin_mode=0) → position_value × initial_margin_fraction / 100
    isolated              → allocated_margin
- `leverage` derived: 100 / initial_margin_fraction.
- `liquidation_price` NULL when Lighter returns "0".
- `update_ts` = account.transaction_time (μs epoch).

Run
---
    python "Snapshot MO/scripts/stream_lighter.py" --once --dry-run
    python "Snapshot MO/scripts/stream_lighter.py" --once
    python "Snapshot MO/scripts/stream_lighter.py" --interval 5
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
LIGHTER_API = "https://mainnet.zklighter.elliot.ai/api/v1"
EXCH = "LIGHTER_FUTURES"

# L1 wallets to snap. Each is looked up via /accountsByL1Address; a wallet that
# has never been funded has no Lighter account yet and is skipped (see
# _resolve_subaccounts). Sub-account indexes are global, so ACCOUNT_MAP below
# stays keyed by index regardless of which wallet a sub belongs to.
L1_ADDRESSES = [
    "0xF8B5bde5f6aa989c01754931E077e1E5A915E2bB",   # TRADING01@LIGHTER - 8023 CDA SOL
    "0xaa8307A460053a9E719e27bE78cF0135A86837f1",   # TRADING02@LIGHTER - 1INCH FUSION
]

# Lighter sub-account index → (MO account_id, account_name).
# Only one sub-account exists today (index 29911); if more get created the
# collector logs a warning and skips so we don't write under a wrong id.
ACCOUNT_MAP: dict[int, dict] = {
    29911: {"account_id": 215002, "name": "TRADING01@LIGHTER"},
    # TRADING02@LIGHTER (refdata account_exchange id 237 -> account_id 237002,
    # portfolio TOKKA LABS - SSB - 1INCH FUSION). Lighter assigns the index on
    # first deposit; until then the wallet returns "account not found". Once it
    # is funded the collector logs `unmapped Lighter sub-account index=N` -
    # that N is the index to add here.
}

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV = REPO_ROOT / ".env"

log = logging.getLogger("stream_lighter")


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
    """Tolerant float parser — Lighter returns numbers as strings."""
    if s in (None, ""):
        return default
    try:
        return float(s)
    except (TypeError, ValueError):
        return default


def _resolve_subaccounts() -> list[dict]:
    """Return {index, collateral, ...} rows across every wallet in L1_ADDRESSES.

    A wallet that has never been funded has no Lighter account and answers
    HTTP 400 `{"code":21100,"message":"account not found"}`. That is the normal
    state of a newly registered wallet, so it is logged and skipped rather than
    failing the snap for the wallets that DO have accounts.

    Any other failure is logged per wallet; if nothing at all could be resolved
    the error is raised so snapshot_all marks the task FAILED instead of
    recording a silent empty snapshot.
    """
    subs: list[dict] = []
    errors = 0
    for addr in L1_ADDRESSES:
        try:
            r = _get(f"{LIGHTER_API}/accountsByL1Address?l1_address={addr}")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            if e.code == 400 and "21100" in body:
                log.info(f"{addr[:10]}...: no Lighter account yet (unfunded), skipping")
            else:
                errors += 1
                log.error(f"accountsByL1Address failed for {addr[:10]}...: {e} {body[:200]}")
            continue
        except Exception as e:
            errors += 1
            log.error(f"accountsByL1Address failed for {addr[:10]}...: {e}")
            continue
        subs.extend(r.get("sub_accounts") or [])
    if errors and not subs:
        raise RuntimeError("accountsByL1Address failed for every configured wallet")
    return subs


def _fetch_account(index: int) -> dict | None:
    """Return the inner account object (accounts[0]) for a given index."""
    r = _get(f"{LIGHTER_API}/account?by=index&value={index}")
    accs = r.get("accounts") or []
    return accs[0] if accs else None


def normalize_position(account_id: int, account_name: str,
                       fetch_dt: datetime, update_dt: datetime | None,
                       raw: dict) -> dict | None:
    symbol = raw.get("symbol", "")
    qty = _f(raw.get("position"), 0.0)
    if not qty:
        return None
    sign = int(raw.get("sign") or 0)
    side = "long" if sign > 0 else "short"

    entry = _f(raw.get("avg_entry_price"))
    pos_value = _f(raw.get("position_value"))
    upnl = _f(raw.get("unrealized_pnl"))
    liq_raw = raw.get("liquidation_price")
    liq = _f(liq_raw, None) if liq_raw not in (None, "", "0") else None
    imf = _f(raw.get("initial_margin_fraction"))  # percent, e.g. "10.00"

    mark = (pos_value / qty) if qty > 0 else None
    leverage = (100.0 / imf) if imf and imf > 0 else None

    margin_mode = int(raw.get("margin_mode") or 0)
    if margin_mode == 0:
        # cross — IM contribution from this position
        margin = (pos_value * imf / 100.0) if imf and pos_value else None
    else:
        # isolated — use allocated_margin as authoritative
        margin = _f(raw.get("allocated_margin"), None)

    return {
        "account_id": account_id,
        "account_name": account_name,
        "exch": EXCH,
        "instrument": f"{symbol}-P/USDC@{EXCH}" if symbol else "",
        "instrument_type": "INST_TYPE_PERP",
        "side": side,
        "contract_size": 1,
        "pos_qty": qty,
        "unsettled_pnl": upnl,
        "avg_entry_price": entry,
        "index_price": None,
        "last_trade_price": mark,
        "leverage": leverage,
        "liquidation_price": liq,
        "margin": margin,
        "instrument_mo": f"{symbol}USDC" if symbol else "",
        "instrument_exch": symbol,
        "sync_ts": fetch_dt.replace(tzinfo=None),
        "update_ts": update_dt.replace(tzinfo=None) if update_dt else fetch_dt.replace(tzinfo=None),
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
    subs = _resolve_subaccounts()

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

        # transaction_time is μs epoch
        tx_us = int(acc.get("transaction_time") or 0)
        update_dt = (datetime.fromtimestamp(tx_us / 1_000_000, tz=timezone.utc)
                     if tx_us > 0 else None)

        positions = acc.get("positions", [])
        kept = 0
        for p in positions:
            row = normalize_position(meta["account_id"], meta["name"],
                                     fetch_dt, update_dt, p)
            if row:
                rows.append(row)
                kept += 1
        log.info(f"sub{idx} ({meta['name']}): {kept}/{len(positions)} open positions")

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
    ap = argparse.ArgumentParser(description="Lighter position snapshot collector")
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
    log.info(f"mode={mode} dry_run={args.dry_run} "
             f"wallets={[a[:10] + '...' for a in L1_ADDRESSES]}")

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
