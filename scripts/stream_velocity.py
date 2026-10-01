"""Velocity (Solana perps DEX, Drift fork) position snapshot collector → middle_office.tq_hist_position_mo.

Pulls `GET /user/{accountId}` from the public Velocity Data API for every mapped
sub-account of the owner wallet and writes one row per open perp position.

Convention
----------
- Public read-only Data API (no auth) — https://docs.velocity.exchange/developers/data-api
  base `https://data.velocity.exchange`.
- OWNER wallet `Dbre9pdVZqUzfqYcDFhySZxjJi8o4iw4qnSWVT1a3B55` is the on-chain
  *authority*; the desk key `EibQ2VYpzj18qSdEBkmxWVzde7FzamTxVG9rZyY689Yj`
  (Phoenix / Bulk wallet) is only the *delegate* and owns a dust sub-account of
  its own. Always read the owner's sub-accounts, never the delegate's.
- Sub-accounts are discovered via `/authority/{OWNER}/accounts` and must be
  mapped in ACCOUNT_MAP (keyed by Velocity accountId = sub-account pubkey);
  unmapped ones are logged and skipped so we never write under a wrong id.
- USDT-margined perps; `baseAssetAmount` signed (positive = long, negative = short).
- `pos_qty` = abs(baseAssetAmount); side from sign.
- `avg_entry_price` = quoteEntryAmount / abs(baseAssetAmount)  (not returned directly).
- `last_trade_price` = `markPrice`, `index_price` = `oraclePrice` from
  `/stats/markets` (matched on perp symbol); `unsettled_pnl` is derived
  (mark - entry) * signed size since the per-user payload carries only
  settledPnl. If the markets feed is unavailable mark/index/uPnL are NULL.
- `liquidation_price` as returned (NULL when 0).
- `margin` / `leverage` NULL — Velocity reports those only at account level
  (see stream_velocity_balance.py equity row).
- No account-level timestamp in the payload → update_ts = sync_ts.
- 429 / 5xx are retried honouring Retry-After; a failed fetch RAISES so
  snapshot_all counts the task FAILED (never a silent `rows=0` gap).

Run
---
    python scripts/stream_velocity.py --once --dry-run
    python scripts/stream_velocity.py --once
    python scripts/stream_velocity.py --hourly
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
VELOCITY_API = "https://data.velocity.exchange"
USER_AGENT = "trade-booking-snapshots/1.0"
EXCH = "VELOCITY_FUTURES"
QUOTE = "USDT"

# On-chain authority that owns the sub-accounts (NOT the delegate key).
OWNER = "Dbre9pdVZqUzfqYcDFhySZxjJi8o4iw4qnSWVT1a3B55"

# TODO(refdata): no `reference_data.account_exchange` row exists for VELOCITY
# yet (counterparty id 230 does). account_id follows the `<id>002` perps-venue
# convention once the row is created; until then INSERT is refused.
ACCOUNT_ID: int | None = None

# Velocity accountId (sub-account pubkey) → (MO account_id, account_name).
# Names mirror the venue's own sub-account index (tokka-labs-N → -N).
ACCOUNT_MAP: dict[str, dict] = {
    "H6JKgKwUaMmGo9XcynpVqTg8ABcTJVtD3qRmSWRMMpt4": {
        "account_id": ACCOUNT_ID, "name": "TRADING01@VELOCITY-0", "sub": 0,
    },
    "4JiXiZ3pkH2vGCUQyWi8v6mQmE983aQwEQEeAfDkWf1y": {
        "account_id": ACCOUNT_ID, "name": "TRADING01@VELOCITY-1", "sub": 1,
    },
    "gqwHcyqkBW6C7FFnSnVQsyAxuK8M3JA9dLF7fjqE6MJ": {
        "account_id": ACCOUNT_ID, "name": "TRADING01@VELOCITY-2", "sub": 2,
    },
    "6tG2no1AuEVFkYeakFgMsVeXyxihLGaYAyapTWtq7PFL": {
        "account_id": ACCOUNT_ID, "name": "TRADING01@VELOCITY-3", "sub": 3,
    },
    "HJrBErHQZnk65Upw16PcRaVV5oKmYWcDCs2ZcCSQadFY": {
        "account_id": ACCOUNT_ID, "name": "TRADING01@VELOCITY-4", "sub": 4,
    },
}

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV = REPO_ROOT / ".env"

log = logging.getLogger("stream_velocity")


# ─────────────────────────────────────────────────────────────────────
# Velocity fetch + normalize
# ─────────────────────────────────────────────────────────────────────

def _get(path: str, attempts: int = 5) -> dict:
    """GET a Data API path, retrying on 429 / 5xx with Retry-After.

    The balance + position collectors hit the same routes ~1s apart inside
    snapshot_all, so treat rate limiting as transient (Phoenix lesson).
    """
    req = urllib.request.Request(
        f"{VELOCITY_API}{path}",
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == attempts:
                raise
            wait = float(e.headers.get("Retry-After") or 2)
            log.warning(
                f"Velocity HTTP {e.code} on {path} (attempt {attempt}/{attempts}), "
                f"retrying in {wait:.0f}s"
            )
            time.sleep(wait)
    raise RuntimeError(f"unreachable: {path}")   # pragma: no cover


def _f(s: str | float | None, default: float | None = 0.0) -> float | None:
    if s in (None, ""):
        return default
    try:
        return float(s)
    except (TypeError, ValueError):
        return default


def fetch_subaccounts() -> list[dict]:
    """`/authority/{OWNER}/accounts` → [{accountId, subAccountId, name}]."""
    r = _get(f"/authority/{OWNER}/accounts")
    if not r.get("success", True):
        raise RuntimeError(f"authority accounts: {r}")
    return r.get("accounts") or []


def fetch_user(account_id: str) -> dict:
    """`/user/{accountId}` → {account, positions, balances, orders}."""
    r = _get(f"/user/{account_id}")
    if "account" not in r:
        raise RuntimeError(f"user {account_id[:8]}…: unexpected payload {str(r)[:200]}")
    return r


def is_empty(user: dict) -> bool:
    """True when a sub-account has zero equity, no asset balances, no positions."""
    acct = user.get("account") or {}
    if _f(acct.get("balance"), 0.0):
        return False
    if any(_f(b.get("balance"), 0.0) for b in user.get("balances") or []):
        return False
    if any(_f(p.get("baseAssetAmount"), 0.0) for p in user.get("positions") or []):
        return False
    return True


def fetch_perp_marks() -> dict[str, dict]:
    """`/stats/markets` → {perp symbol: {markPrice, oraclePrice}}.

    Spot and perp markets share marketIndex values, so match on symbol +
    marketType, never on index.
    """
    r = _get("/stats/markets")
    out: dict[str, dict] = {}
    for m in r.get("markets") or []:
        if m.get("marketType") == "perp" and m.get("symbol"):
            out[m["symbol"]] = {
                "mark": _f(m.get("markPrice"), None),
                "oracle": _f(m.get("oraclePrice"), None),
            }
    return out


def normalize_position(account_id: int, account_name: str, fetch_dt: datetime,
                       raw: dict, marks: dict[str, dict]) -> dict | None:
    symbol_exch = raw.get("symbol") or ""           # "SOL-PERP"
    symbol = symbol_exch.split("-")[0]
    size = _f(raw.get("baseAssetAmount"), 0.0)
    if not size:
        return None
    side = "long" if size > 0 else "short"
    abs_size = abs(size)

    quote_entry = _f(raw.get("quoteEntryAmount"), 0.0)
    entry = abs(quote_entry) / abs_size if quote_entry else None

    px = marks.get(symbol_exch) or {}
    mark = px.get("mark")
    oracle = px.get("oracle")
    upnl = (mark - entry) * size if (mark is not None and entry is not None) else None

    liq = _f(raw.get("liquidationPrice"), None)
    if not liq:
        liq = None

    return {
        "account_id": account_id,
        "account_name": account_name,
        "exch": EXCH,
        "instrument": f"{symbol}-P/{QUOTE}@{EXCH}" if symbol else "",
        "instrument_type": "INST_TYPE_PERP",
        "side": side,
        "contract_size": 1,
        "pos_qty": abs_size,
        "unsettled_pnl": upnl,
        "avg_entry_price": entry,
        "index_price": oracle,
        "last_trade_price": mark,
        "leverage": None,
        "liquidation_price": liq,
        "margin": None,
        "instrument_mo": f"{symbol}{QUOTE}" if symbol else "",
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
    """Yield (accountId, meta, user payload) for every mapped sub-account.

    Discovery comes from the owner's authority listing so a NEW sub-account
    is surfaced as a warning rather than silently missed. Fetch errors raise.
    """
    subs = fetch_subaccounts()
    if not subs:
        raise RuntimeError(f"no sub-accounts listed for owner {OWNER[:8]}…")
    seen = set()
    for s in subs:
        acc_id = s.get("accountId")
        meta = ACCOUNT_MAP.get(acc_id)
        if meta is None:
            log.warning(
                f"unmapped Velocity sub-account {acc_id} "
                f"(sub={s.get('subAccountId')} name={s.get('name')!r}), skipping"
            )
            continue
        seen.add(acc_id)
        yield acc_id, meta, fetch_user(acc_id)
    for acc_id in set(ACCOUNT_MAP) - seen:
        log.warning(f"mapped sub-account {acc_id[:8]}… not in authority listing")


def _check_account_ids(rows: list[dict]) -> None:
    missing = sorted({r["account_name"] for r in rows if r["account_id"] is None})
    if missing:
        raise RuntimeError(
            "account_id unset (no VELOCITY refdata row yet) for "
            f"{missing}; refusing to INSERT"
        )


def snap_once(conn, dry_run: bool) -> int:
    fetch_dt = datetime.now(timezone.utc)
    try:
        marks = fetch_perp_marks()
    except Exception as e:
        log.warning(f"markets feed failed ({e}); mark/index/uPnL will be NULL")
        marks = {}

    rows: list[dict] = []
    for acc_id, meta, user in _iter_accounts():
        positions = user.get("positions") or []
        kept = 0
        for p in positions:
            row = normalize_position(meta["account_id"], meta["name"], fetch_dt, p, marks)
            if row:
                rows.append(row)
                kept += 1
        log.info(f"sub{meta['sub']} ({meta['name']}): {kept}/{len(positions)} open positions")

    if dry_run:
        for r in rows:
            mark = r["last_trade_price"]
            upnl = r["unsettled_pnl"]
            log.info(
                f"DRY {r['account_name']:30s} {r['instrument_mo']:10s} "
                f"{r['side']:5s} qty={r['pos_qty']:>14,.4f} "
                f"entry={r['avg_entry_price'] or 0:>14,.6f} "
                f"mark={(mark if mark is not None else 0):>14,.6f} "
                f"upnl={(upnl if upnl is not None else 0):>10,.2f}"
            )
        return len(rows)

    if conn and rows:
        _check_account_ids(rows)
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
    ap = argparse.ArgumentParser(description="Velocity position snapshot collector")
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
