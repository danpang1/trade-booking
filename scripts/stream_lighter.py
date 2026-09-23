"""Lighter (zkSync L2 perps) position snapshot collector → middle_office.tq_hist_position_mo.

Resolves sub-accounts by L1 address, then pulls /account?by=index for each
and writes one row per open position.

Convention
----------
- Public read-only API (no auth).
- L1 wallets in L1_ADDRESSES; an unfunded wallet has no Lighter account yet
  and is skipped (HTTP 400 / code 21100) without failing the other wallets.
- Two deployments: zkSync mainnet and Robinhood Chain (same REST surface,
  separate index spaces), so ACCOUNT_MAP is keyed by (api base, index):
    (mainnet, 29911) → 215002 TRADING01@LIGHTER  (8023 CDA SOL desk)
    (rh chain, 31599) → 237002 TRADING02@LIGHTER (1INCH FUSION desk)
  Unmapped pairs are warned + skipped so nothing lands under a wrong id.
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
# Lighter also runs on Robinhood Chain - a SEPARATE deployment with the same
# REST surface but its own order books, markets and account-index space. Host
# taken from the explorer bundle (apidocs.rh.lighter.xyz / api.rh.lighter.xyz).
LIGHTER_RH_API = "https://api.rh.lighter.xyz/api/v1"
# `exch` is per deployment, not per venue: refdata lists the Robinhood Chain
# account under exchangeName "LIGHTER ROBINHOOD" with products=UNIFIED, so it
# takes the UNIFIED naming used for Bitget's unified-trading accounts
# (EC001@BITGET_UNIFIED / exch BITGET_UNIFIED) rather than the _FUTURES form.
# Each ACCOUNT_MAP entry carries the value its rows are written with.
EXCH = "LIGHTER_FUTURES"        # zkSync mainnet deployment
EXCH_RH = "LIGHTER_UNIFIED"     # Robinhood Chain deployment

# (api base, L1 wallet) pairs to snap. A wallet only means something together
# with the deployment it lives on, so they travel as a pair. A wallet that has
# never been funded has no account yet and is skipped (see _resolve_subaccounts).
WALLETS = [
    (LIGHTER_API, "0xF8B5bde5f6aa989c01754931E077e1E5A915E2bB"),      # TRADING01 - 8023 CDA SOL
    (LIGHTER_RH_API, "0xaa8307A460053a9E719e27bE78cF0135A86837f1"),   # TRADING02 - 1INCH FUSION
]

# (api base, sub-account index) -> MO account. Keyed by api base as well as
# index because index spaces are PER DEPLOYMENT: index N on Robinhood Chain is
# a different account from index N on zkSync mainnet, so keying on the bare
# index would silently merge two desks. Unmapped pairs are warned + skipped so
# nothing is ever written under a wrong account_id.
ACCOUNT_MAP: dict[tuple[str, int], dict] = {
    (LIGHTER_API, 29911): {
        "account_id": 215002, "name": "TRADING01@LIGHTER", "exch": EXCH,
    },
    (LIGHTER_RH_API, 31599): {
        "account_id": 237002, "name": "TRADING02@LIGHTER_UNIFIED", "exch": EXCH_RH,
    },
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


def _resolve_subaccounts() -> list[tuple[str, dict]]:
    """Return (api base, sub-account row) for every wallet in WALLETS.

    The api base is carried alongside each row because every later call - the
    /account fetch and the ACCOUNT_MAP lookup - has to hit the same deployment
    the sub-account was discovered on.

    A wallet that has never been funded has no account and answers HTTP 400
    `{"code":21100,"message":"account not found"}`. That is the normal state of
    a newly registered wallet, so it is logged and skipped rather than failing
    the snap for the wallets that DO have accounts.

    Any other failure is logged per wallet; if nothing at all could be resolved
    the error is raised so snapshot_all marks the task FAILED instead of
    recording a silent empty snapshot.
    """
    subs: list[tuple[str, dict]] = []
    errors = 0
    for api, addr in WALLETS:
        try:
            r = _get(f"{api}/accountsByL1Address?l1_address={addr}")
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
        subs.extend((api, s) for s in (r.get("sub_accounts") or []))
    if errors and not subs:
        raise RuntimeError("accountsByL1Address failed for every configured wallet")
    return subs


def _fetch_account(api: str, index: int) -> dict | None:
    """Return the inner account object (accounts[0]) for a given index."""
    r = _get(f"{api}/account?by=index&value={index}")
    accs = r.get("accounts") or []
    return accs[0] if accs else None


def normalize_position(account_id: int, account_name: str, exch: str,
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
        "exch": exch,
        "instrument": f"{symbol}-P/USDC@{exch}" if symbol else "",
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
    for api, sub in subs:
        idx = sub.get("index")
        meta = ACCOUNT_MAP.get((api, idx))
        if meta is None:
            log.warning(f"unmapped Lighter sub-account index={idx} on {api}, skipping")
            continue
        try:
            acc = _fetch_account(api, idx)
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
            row = normalize_position(meta["account_id"], meta["name"], meta["exch"],
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
             f"wallets={[a[:10] + '...' for _, a in WALLETS]}")

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
