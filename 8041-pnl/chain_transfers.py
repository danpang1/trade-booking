"""Non-fill token transfers for the EVM RFQ wallets → venue_transfers.

Self-owned transfer indexer (the data team does not index transfers in
ClickHouse, so we keep our own): walks the Blockscout **Etherscan-compatible**
API (`?module=account&action=tokentx`) which is address-filtered, block-range
scoped and returns 1,000 rows per call — ~20x fewer HTTP calls than the v2
token-transfers feed. A per-venue block cursor (venue_transfer_cursor) makes
every sync incremental: each block range is scanned exactly once, ever.

Classification: group records by tx hash — a tx where the wallet both sends
AND receives tokens is a swap (fill; already in trades_spot_avgcost via the
ClickHouse ingest — skipped); one-directional txs are transfers (deposits,
withdrawals, mints/burns, gas top-ups) and land in venue_transfers.

Native coin (ETH gas top-ups) via `action=txlist`, recorded as 'ETH-NATIVE'.
Spam airdrops are excluded via the RFQ token-map allowlists.
Rows tagged transfer_type='SETTLEMENT_BOOKED' (set manually when an arrival's
acquisition is already booked as cost-basis fills) are preserved — the sync
never overwrites existing rows (ON CONFLICT DO NOTHING).
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path

import avgcost_db

REPO = Path(__file__).resolve().parent

WALLETS = {
    "ROBINHOOD": {
        "account": "WALLET_CRB_EVM_02_ROBINHOOD",
        "wallet": "0x9f736f87e6293ac1bd9142e257dbfac8b7acf1ae",
        "base": "https://robinhoodchain.blockscout.com",
        "gateway": "https://api.blockscout.com/4663/",
        "native": False,               # maker pays no gas on RH chain
        "allowlist": "rh_token_map.json",
        "cold_start_days": 8,
    },
    # second RH-chain RFQ wallet (GME market making, active since 07-23) —
    # found 2026-07-31 via the refdata account cross-check
    "ROBINHOOD_05": {
        "account": "WALLET_CRB_EVM_05_ROBINHOOD",
        "wallet": "0xe93c3433ee34b4a0d6f3830bc05d625c6dd0da7d",
        "base": "https://robinhoodchain.blockscout.com",
        "gateway": "https://api.blockscout.com/4663/",
        "native": False,
        "allowlist": "rh05_token_map.json",
        "cold_start_days": 10,
    },
    "ETHEREUM": {
        "account": "WALLET_CRB_EVM_04_ETHEREUM",
        "wallet": "0x391af49b1793529f430c4b5918da6bb237306865",
        "base": "https://eth.blockscout.com",
        "gateway": "https://api.blockscout.com/1/",
        "native": True,
        "allowlist": "eth_token_map.json",
        "cold_start_days": 30,
    },
    # Dinari primary-market treasury on HyperEVM. Pure custody column: its
    # trades are ALREADY booked as the 17 venue=DINARI fills folded into the
    # HL SPCXD leg, so nothing here becomes a fill — every movement (dShare
    # mint in, USDC payment out, SPCX<->SPCX.dw wrap, bridge out) is a
    # transfer, wraps included (swaps_as_transfers).
    "DINARI": {
        "account": "TOKKA_TREASURY_EVM_01_DINARI",
        "wallet": "0xb7c6a246c658814c5a879fbec61055ec9896fd3c",
        "base": "https://www.hyperscan.com",
        "gateway": None,               # no Blockscout paid gateway for HyperEVM
        "native": True,
        "native_asset": "HYPE",
        "swaps_as_transfers": True,
        "allowlist": "dinari_token_map.json",
        "cold_start_days": 55,         # first activity 2026-06-12
    },
}

CURSOR_DDL = """
CREATE TABLE IF NOT EXISTS venue_transfer_cursor (
    venue      TEXT PRIMARY KEY,
    last_block BIGINT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def _env(key):
    for line in (REPO / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return None


def _api(cfg, params):
    """Etherscan-compatible endpoint on the Blockscout instance."""
    url = cfg["base"] + "/api?" + urllib.parse.urlencode(params)
    key = _env("BLOCKSCOUT_API_KEY")
    if key and cfg.get("gateway"):
        url = (url.replace(cfg["base"] + "/", cfg["gateway"])
               + "&apikey=" + key)
    for attempt in range(8):
        try:
            r = urllib.request.urlopen(urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0"}), timeout=45)
            d = json.loads(r.read())
            if isinstance(d, dict) and "result" in d:
                return d["result"]
        except Exception:
            pass
        time.sleep(min(20, 2 * (attempt + 1)))
    raise RuntimeError(f"blockscout etherscan-api kept failing ({params.get('action')})")


def _latest_block(cfg):
    """v2 /blocks — the legacy proxy module 400s on some instances."""
    url = cfg["base"] + "/api/v2/blocks?type=block"
    key = _env("BLOCKSCOUT_API_KEY")
    if key and cfg.get("gateway"):
        url = (url.replace(cfg["base"] + "/", cfg["gateway"])
               + "&apikey=" + key)
    for attempt in range(6):
        try:
            r = urllib.request.urlopen(urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30)
            return int(json.loads(r.read())["items"][0]["height"])
        except Exception:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("latest-block lookup failed")


def _block_at(cfg, dt):
    r = _api(cfg, {"module": "block", "action": "getblocknobytime",
                   "timestamp": int(dt.timestamp()), "closest": "before"})
    if isinstance(r, dict):
        r = r.get("blockNumber") or r.get("BlockNumber")
    return int(r)


def _walk_range(cfg, action, start_block, end_block):
    """All records for the wallet in [start_block, end_block], ascending —
    1,000 rows/call. A full page may cut MID-BLOCK; stepping past that block
    would silently drop its remaining rows (this split swap legs into
    phantom one-sided 'transfers' — found 2026-07-30, 178 bogus rows), so a
    boundary block is re-fetched in full on the next iteration."""
    out, frm = [], start_block
    while True:
        rows = _api(cfg, {"module": "account", "action": action,
                          "address": cfg["wallet"], "startblock": frm,
                          "endblock": end_block, "sort": "asc",
                          "page": 1, "offset": 1000})
        if not isinstance(rows, list) or not rows:
            break
        if len(rows) < 1000:
            out += rows
            break
        last_blk = int(rows[-1]["blockNumber"])
        if last_blk == int(rows[0]["blockNumber"]):
            # degenerate: one block holding a full page — take it whole and
            # step past (its tail beyond 1,000 rows is unreachable via this
            # endpoint; unheard-of for our wallets)
            out += rows
            frm = last_blk + 1
        else:
            out += [r for r in rows if int(r["blockNumber"]) < last_blk]
            frm = last_blk          # re-fetch the boundary block in full
        if frm > end_block:
            break
    return out


def _classify(cfg, venue, records):
    """tokentx records -> transfer rows (swap txs dropped, spam filtered)."""
    w = cfg["wallet"].lower()
    allow, amap = None, {}
    p = REPO / cfg.get("allowlist", "")
    if p.name and p.exists():
        amap = {a.lower(): (str(s).upper(), int(d)) for a, (s, d) in
                json.loads(p.read_text(encoding="utf-8")).items()}
        allow = set(amap)
    by_tx = defaultdict(list)
    for t in records:
        by_tx[t["hash"].lower()].append(t)
    rows = []
    for tx, ts_ in by_tx.items():
        ins, outs, meta = defaultdict(int), defaultdict(int), {}
        for t in ts_:
            addr = (t.get("contractAddress") or "").lower()
            if allow is not None and addr not in allow:
                continue
            # the local token map is authoritative for symbol/decimals —
            # chain metadata can be absent (RH) or unicode-styled (USD₮0)
            meta[addr] = amap.get(addr) or (
                str(t.get("tokenSymbol") or "?").upper(),
                int(t.get("tokenDecimal") or 18))
            val = int(t.get("value") or 0)
            if (t.get("from") or "").lower() == w:
                outs[addr] += val
            if (t.get("to") or "").lower() == w:
                ins[addr] += val
        if not (ins or outs):
            continue                      # nothing relevant for the wallet
        if ins and outs and not cfg.get("swaps_as_transfers"):
            continue                      # swap = fill (booked via ingest)
        when = datetime.fromtimestamp(int(ts_[0]["timeStamp"]),
                                      timezone.utc)
        for addr, val in list(ins.items()) + [(a, -v)
                                              for a, v in outs.items()]:
            if val == 0:
                continue
            sym, dec = meta[addr]
            rows.append({
                "venue": venue, "account": cfg["account"], "asset": sym,
                "qty": D(val) / D(10) ** dec,
                "transfer_type": "DEPOSIT" if val > 0 else "WITHDRAWAL",
                "external_id": f"{tx}:{sym}",
                "event_time": when, "raw": json.dumps({"tx": tx})})
    return rows


def _native_rows(cfg, venue, start_block, end_block):
    w = cfg["wallet"].lower()
    asset = cfg.get("native_asset", "ETH-NATIVE")
    rows = []
    for t in _walk_range(cfg, "txlist", start_block, end_block):
        val = int(t.get("value") or 0)
        if val == 0 or str(t.get("isError")) == "1":
            continue
        frm = (t.get("from") or "").lower()
        to = (t.get("to") or "").lower()
        sign = 1 if to == w else (-1 if frm == w else 0)
        if not sign:
            continue
        rows.append({
            "venue": venue, "account": cfg["account"], "asset": asset,
            "qty": D(sign * val) / D(10) ** 18,
            "transfer_type": "DEPOSIT" if sign > 0 else "WITHDRAWAL",
            "external_id": f"{t['hash'].lower()}:{asset}",
            "event_time": datetime.fromtimestamp(int(t["timeStamp"]),
                                                 timezone.utc),
            "raw": json.dumps({"tx": t["hash"]})})
    return rows


# DINARI dropped from the default 2026-08-03: its explorer (hyperscan.com)
# stopped serving the Blockscout API entirely — the domain now returns a
# marketing page and every /api/v2/* path 404s. That leg lives in
# dinari_transfers.py (GoldRush) now. Pass venues=(...,"DINARI") explicitly
# if hyperscan ever comes back.
def sync(venues=("ROBINHOOD", "ROBINHOOD_05", "ETHEREUM")):
    """Incremental block-cursor sync; returns {venue: (rows, blocks)}.

    One chain's explorer being down must not cost us the others: on
    2026-08-03 hyperscan.com started 404ing on /api/v2/blocks and killed the
    whole stage. DINARI happens to be LAST in the default order, so the other
    three had already committed — pure luck. Each venue is now isolated, and
    failures are RAISED as a summary at the end rather than swallowed: a
    silently un-synced wallet is worse than a loudly broken one.
    """
    import bitstamp_source
    conn = avgcost_db.connect()
    out, failed = {}, {}
    try:
        with conn.cursor() as cur:
            cur.execute(bitstamp_source.DDL)
            cur.execute(CURSOR_DDL)
        conn.commit()
        for venue in venues:
            try:
                out[venue] = _sync_one(conn, venue)
            except Exception as e:
                conn.rollback()
                failed[venue] = f"{type(e).__name__}: {e}"
                print(f"  [chain_transfers] {venue} FAILED — {failed[venue]}",
                      flush=True)
    finally:
        conn.close()
    if failed:
        raise RuntimeError(
            f"{len(failed)}/{len(venues)} chain(s) failed: {failed}. "
            f"Synced OK: {sorted(out)}")
    return out


def _sync_one(conn, venue):
    """Sync one venue's transfers. Returns (rows_inserted, blocks_walked)."""
    cfg = WALLETS[venue]
    with conn.cursor() as cur:
        cur.execute("SELECT last_block FROM venue_transfer_cursor "
                    "WHERE venue = %s", (venue,))
        row = cur.fetchone()
    tip = _latest_block(cfg)
    if row:
        start = row[0] + 1
    else:
        start = _block_at(cfg, datetime.now(timezone.utc)
                          - timedelta(days=cfg["cold_start_days"]))
    if start > tip:
        return (0, 0)
    records = _walk_range(cfg, "tokentx", start, tip)
    rows = _classify(cfg, venue, records)
    # guard: a tx that is a booked fill is NEVER also a transfer —
    # any one-sided leg here means the walk/collector saw half a
    # swap, and recording it double-books the trade as a transfer
    if rows:
        txs = list({x["external_id"].split(":")[0] for x in rows})
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT split_part(external_trade_id, ':', 1)
                FROM trades_spot_avgcost
                WHERE venue = %s
                  AND split_part(external_trade_id, ':', 1)
                      = ANY(%s)
            """, (venue, txs))
            fill_txs = {r[0] for r in cur.fetchall()}
        dropped = [x for x in rows
                   if x["external_id"].split(":")[0] in fill_txs]
        if dropped:
            print(f"  ({venue}: {len(dropped)} one-sided swap legs "
                  "dropped — tx already booked as fill)")
        rows = [x for x in rows
                if x["external_id"].split(":")[0] not in fill_txs]
    if cfg["native"]:
        rows += _native_rows(cfg, venue, start, tip)
    n = 0
    with conn.cursor() as cur:
        for x in rows:
            cur.execute("""
                INSERT INTO venue_transfers
                    (venue, account, asset, qty, transfer_type,
                     external_id, event_time, raw)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (venue, account, external_id, asset)
                DO NOTHING
            """, (x["venue"], x["account"], x["asset"], str(x["qty"]),
                  x["transfer_type"], x["external_id"],
                  x["event_time"], x["raw"]))
            n += cur.rowcount
        cur.execute("""
            INSERT INTO venue_transfer_cursor (venue, last_block)
            VALUES (%s, %s)
            ON CONFLICT (venue) DO UPDATE
                SET last_block = EXCLUDED.last_block,
                    updated_at = now()
        """, (venue, tip))
    conn.commit()
    return (n, tip - start + 1)


if __name__ == "__main__":
    for v, (n, blocks) in sync().items():
        print(f"{v}: +{n} transfer rows over {blocks} blocks")


def chain_fills(venue, start_dt, end_dt=None):
    """Canonical RFQ fills reconstructed from the FAST block-range tokentx
    walk (swap txs = wallet sends AND receives). Robinhood-shaped:
    {ticker -> [fill dicts]} with '{tx}:{TICKER}' ids, source='chain'.
    ~20x fewer HTTP calls than the legacy v2 token-transfers walk."""
    from datetime import timezone as _tz
    cfg = WALLETS[venue]
    w = cfg["wallet"].lower()
    usdg = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"
    allow = None
    p = REPO / cfg.get("allowlist", "")
    if p.name and p.exists():
        allow = {a.lower() for a in json.loads(p.read_text(encoding="utf-8"))}
    start_block = _block_at(cfg, start_dt)
    end_block = (_block_at(cfg, end_dt) if end_dt else _latest_block(cfg))
    records = _walk_range(cfg, "tokentx", start_block, end_block)
    by_tx = defaultdict(list)
    for t in records:
        by_tx[t["hash"].lower()].append(t)
    out = defaultdict(list)
    for tx, ts_ in by_tx.items():
        ins, outs, meta = defaultdict(int), defaultdict(int), {}
        for t in ts_:
            addr = (t.get("contractAddress") or "").lower()
            if allow is not None and addr not in allow:
                continue
            meta[addr] = (str(t.get("tokenSymbol") or "?").upper(),
                          int(t.get("tokenDecimal") or 18))
            val = int(t.get("value") or 0)
            if (t.get("from") or "").lower() == w:
                outs[addr] += val
            if (t.get("to") or "").lower() == w:
                ins[addr] += val
        if not (ins and outs):
            continue                     # one-way = transfer, not a fill
        t_ms = int(ts_[0]["timeStamp"]) * 1000
        for side, legs_, quote_ in (("BUY", ins, outs), ("SELL", outs, ins)):
            base = [a for a in legs_ if a != usdg]
            if len(base) != 1:
                continue
            uv = quote_.get(usdg, 0)
            if uv == 0:
                continue
            addr = base[0]
            sym, dec = meta[addr]
            ticker = "WETH" if sym in ("WETH", "ETH") else sym
            qty = D(legs_[addr]) / D(10) ** dec
            if qty == 0:
                continue
            px = (D(uv) / D(10) ** 6) / qty
            sign = D(1) if side == "BUY" else D(-1)
            out[ticker].append({
                "external_trade_id": f"{tx}:{ticker}",
                "trade_date_ms": t_ms,
                "signed_qty": qty * sign,
                "price": px,
                "fee_amount": D("0"),
                "fee_asset": "USDG",
                "base_asset": ticker,
                "source": "chain",
            })
    return out
