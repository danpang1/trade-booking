"""Hyperliquid flow feeds for the recon dashboard (TRADING_06 futures).

Windowed pulls from the public info API (address from .env
TRADING_06@HYPERLIQUID):

  * fills_by_time  — userFillsByTime: closedPnl + fee per fill, bucketed to
                     the margin pool ('USDC' main dex / 'xyz:USDC' HIP-3 dex)
  * funding        — userFunding: funding payments per pool
  * ledger_transfers — userNonFundingLedgerUpdates classified into USDC pool
                     transfers (deposit / withdraw / accountClassTransfer /
                     send / spotTransfer / subAccountTransfer), for
                     venue_transfers (venue HYPERLIQUID)

Pool convention: coins like 'xyz:AAPL' fund/settle in the xyz dex USDC pool;
everything else (HYPE, BTC) in the main pool. Matches account_recon.pool_of.
"""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path

REPO = Path(__file__).resolve().parent
API = "https://api.hyperliquid.xyz/info"
VENUE = "HYPERLIQUID"
ACCOUNT = "TRADING_06@HYPERLIQUID_FUTURES"


def _env(key):
    for line in (REPO / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return None


def _addr():
    a = _env("TRADING_06@HYPERLIQUID")
    if not a:
        raise RuntimeError("TRADING_06@HYPERLIQUID missing from .env")
    return a.lower()


def _post(body):
    for attempt in range(6):
        try:
            r = urllib.request.urlopen(urllib.request.Request(
                API, data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"}), timeout=30)
            return json.loads(r.read())
        except Exception:
            if attempt == 5:
                raise
            time.sleep(2 * (attempt + 1))


def _pool(coin):
    return "xyz:USDC" if str(coin).startswith("xyz:") else "USDC"


def _paged(kind, start_ms, end_ms, time_key="time"):
    # per-call caps differ by endpoint (userFillsByTime 2000, userFunding 500)
    # so page until a batch stops advancing — never infer "last page" from size
    out, cur = [], start_ms
    while True:
        b = _post({"type": kind, "user": _addr(),
                   "startTime": cur, "endTime": end_ms})
        if not b:
            break
        out += b
        bmax = max(int(x[time_key]) for x in b)
        if bmax + 1 <= cur or len(b) < 500:
            break
        cur = bmax + 1
    return out


def fills_by_time(start_ms, end_ms):
    """[{'t', 'coin', 'pool', 'qty'(signed), 'closed', 'fee'}] — perp fills
    only (spot fills carry '@'-prefixed coins and belong to the spot acct)."""
    out = []
    for f in _paged("userFillsByTime", start_ms, end_ms):
        coin = str(f.get("coin", ""))
        if coin.startswith("@"):
            continue
        sz = D(str(f.get("sz", 0)))
        out.append({
            "t": int(f["time"]), "coin": coin, "pool": _pool(coin),
            "qty": sz if f.get("side") == "B" else -sz,
            "closed": D(str(f.get("closedPnl", 0) or 0)),
            "fee": D(str(f.get("fee", 0) or 0)),
        })
    return out


def funding(start_ms, end_ms):
    """[{'t', 'pool', 'usdc'}] funding payments."""
    out = []
    for u in _paged("userFunding", start_ms, end_ms):
        d = u.get("delta") or {}
        out.append({"t": int(u["time"]), "pool": _pool(d.get("coin", "")),
                    "usdc": D(str(d.get("usdc", 0) or 0))})
    return out


SPOT_ACCOUNT = "TRADING_06@HYPERLIQUID_SPOT"


def ledger_transfers(start_ms, end_ms):
    """Pool transfer rows for venue_transfers, POOL-AWARE (2026-07-30):
    perp pool -> (FUTURES acct, USDC), xyz dex -> (FUTURES acct, xyz:USDC),
    spot pool -> (SPOT acct, token). Internal pool moves emit BOTH legs —
    the old one-account mapping recorded spot-pool sends against the
    futures column (the +90k/+50k USDC phantom breaks)."""
    addr = _addr()

    def pool_of(dex):
        # (account, asset-prefix) for a dex label on USDC moves
        if dex == "spot":
            return (SPOT_ACCOUNT, "USDC")
        if dex == "xyz":
            return (ACCOUNT, "xyz:USDC")
        return (ACCOUNT, "USDC")            # '', None, 'perp', 'main' = core perp

    rows = []
    for u in _paged("userNonFundingLedgerUpdates", start_ms, end_ms):
        d = u.get("delta") or {}
        ty = d.get("type")
        t_ms = int(u["time"])
        when = datetime.fromtimestamp(t_ms / 1000, timezone.utc)
        h = str(u.get("hash") or t_ms)
        moves = []      # (account, asset, signed qty)
        if ty == "deposit":
            moves.append((ACCOUNT, "USDC", D(str(d.get("usdc", 0)))))
        elif ty == "withdraw":
            moves.append((ACCOUNT, "USDC", -D(str(d.get("usdc", 0)))))
        elif ty == "accountClassTransfer":
            # perp <-> spot within our own address: both legs
            amt = D(str(d.get("usdc", 0)))
            s = D(1) if d.get("toPerp") else D(-1)
            moves.append((ACCOUNT, "USDC", amt * s))
            moves.append((SPOT_ACCOUNT, "USDC", -amt * s))
        elif ty in ("send", "spotTransfer", "subAccountTransfer",
                    "internalTransfer"):
            tok = str(d.get("token", "USDC")).upper().split(":")[0]
            amt = D(str(d.get("amount", d.get("usdc", 0)) or 0))
            if str(d.get("user", "")).lower() == addr:
                acct, asset = pool_of(d.get("sourceDex"))
                if "USDC" not in tok:
                    acct, asset = SPOT_ACCOUNT, tok   # token moves live in spot
                moves.append((acct, asset, -amt))
            if str(d.get("destination", "")).lower() == addr:
                acct, asset = pool_of(d.get("destinationDex"))
                if "USDC" not in tok:
                    acct, asset = SPOT_ACCOUNT, tok
                moves.append((acct, asset, amt))
        elif ty == "perpDexClassTransfer":
            # core perp <-> builder-dex perp: both legs
            amt = D(str(d.get("amount", 0) or 0))
            dex = d.get("dex") or ""
            dex_asset = "xyz:USDC" if dex == "xyz" else "USDC"
            s = D(1) if d.get("toPerp") else D(-1)
            moves.append((ACCOUNT, dex_asset, amt * s))
            if dex_asset != "USDC":
                moves.append((ACCOUNT, "USDC", -amt * s))
        else:
            continue
        for i, (acct, asset, qty) in enumerate(moves):
            if qty == 0:
                continue
            rows.append({
                "venue": VENUE, "account": acct, "asset": asset,
                "qty": qty,
                "transfer_type": ty.upper(),
                "external_id": f"{h}:{i}:{asset}",
                "event_time": when, "raw": json.dumps(d)})
    return rows


def sync_transfers(start_ms, end_ms):
    """Windowed idempotent sync into venue_transfers; returns inserted."""
    import avgcost_db
    import bitstamp_source
    rows = ledger_transfers(start_ms, end_ms)
    conn = avgcost_db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(bitstamp_source.DDL)
            n = 0
            for x in rows:
                cur.execute("""
                    INSERT INTO venue_transfers
                        (venue, account, asset, qty, transfer_type,
                         external_id, event_time, raw)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (venue, account, external_id, asset)
                    DO NOTHING
                """, (x["venue"], x["account"], x["asset"], str(x["qty"]),
                      x["transfer_type"], x["external_id"], x["event_time"],
                      x["raw"]))
                n += cur.rowcount
        conn.commit()
        return n
    finally:
        conn.close()


if __name__ == "__main__":
    now = int(time.time() * 1000)
    start = now - 3 * 24 * 3600 * 1000
    f = fills_by_time(start, now)
    fu = funding(start, now)
    x = ledger_transfers(start, now)
    print(f"fills {len(f)}  funding {len(fu)}  transfers {len(x)}")
    print("synced:", sync_transfers(start, now))
