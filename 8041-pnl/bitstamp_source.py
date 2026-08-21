"""Bitstamp Moon (MOON-TOKKA@BITSTAMP) venue-API source — fills + transfers.

Replaces the PROD-MO-DB booked-trade source: the venue is now authoritative.

Two feeds, both HMAC-v2 signed (creds: .env BITSTAMP_API_KEY / _SECRET — same
key the balance streamer uses):

  * Stock fills   GET /api-external/prime/v1/{acct}/order_history/?limit=10000
      Tokenized-equity orders. qty = filled_tokens_quantity, per-token price =
      average_fill_price (per share) x multiplier. Venue caps default at 100
      rows and honors ONLY `limit` (no offset/timestamp), so one big page.
      Signing note: the query is signed WITH the leading '?' or 403 API0005.
  * user_transactions   POST /api/v2/user_transactions/ (since_id asc walk)
      type 0/1 = deposits/withdrawals (mints + funding)  -> venue_transfers
      type 2   = classic cash trades (USDG/USD conversions) -> USDG fills
      type 68/69 = zero-amount stock-fill markers — ignored (real qty comes
      from order_history).

venue_transfers (UAT middle_office) stores transfer activity generically:
    venue / account / asset / qty (signed, +in) / transfer_type /
    external_id / event_time / raw
    UNIQUE (venue, account, external_id, asset) -> idempotent re-sync.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path

REPO = Path(__file__).resolve().parent
HOST = "www.bitstamp.net"
ACCOUNT = "MOON-TOKKA@BITSTAMP"
VENUE = "BITSTAMP"
PRIME_ACCT_ID = "0"

_STD_KEYS = {"id", "datetime", "type", "fee", "btc_usd", "usd", "btc", "eur",
             "order_id"}


def _env(key):
    for line in (REPO / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return None


def _headers(method, path, query, body):
    key, sec = _env("BITSTAMP_API_KEY"), _env("BITSTAMP_API_SECRET")
    nonce = uuid.uuid4().hex + uuid.uuid4().hex[:4]
    ts = str(int(time.time() * 1000))
    ctype = "application/x-www-form-urlencoded" if body else ""
    msg = ("BITSTAMP " + key + method + HOST + path + query + ctype
           + nonce + ts + "v2" + body)
    sig = hmac.new(sec.encode(), msg.encode(), hashlib.sha256).hexdigest()
    h = {"X-Auth": "BITSTAMP " + key, "X-Auth-Signature": sig,
         "X-Auth-Nonce": nonce, "X-Auth-Timestamp": ts,
         "X-Auth-Version": "v2"}
    if ctype:
        h["Content-Type"] = ctype
    return h


def get_signed(path, query=""):
    q = "?" + query if query else ""
    req = urllib.request.Request(
        "https://" + HOST + path + q,
        headers=_headers("GET", path, q, ""))
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def post_signed(path, params=None):
    body = urllib.parse.urlencode(params or {})
    req = urllib.request.Request(
        "https://" + HOST + path,
        data=body.encode() if body else None,
        headers=_headers("POST", path, "", body), method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


# ── stock fills ────────────────────────────────────────────────────────
def stock_fills(before_ms=None):
    """Canonical fill dicts for every filled tokenized-equity order (full
    history; the endpoint returns everything in one page)."""
    rows = get_signed(f"/api-external/prime/v1/{PRIME_ACCT_ID}/order_history/",
                      "limit=10000")
    out = []
    for o in rows:
        qty = D(str(o.get("filled_tokens_quantity")
                    or o.get("filled_base_quantity") or "0"))
        if qty <= 0:
            continue
        t_ms = int(o["created_at"])
        if before_ms is not None and t_ms >= before_ms:
            continue
        mult = D(str(o.get("multiplier") or "1"))
        px = D(str(o.get("average_fill_price") or "0")) * mult
        sign = D(1) if str(o.get("side")).upper() == "BUY" else D(-1)
        out.append({
            "external_trade_id": str(o["order_id"]),
            "trade_date_ms": t_ms,
            "signed_qty": qty * sign,
            "price": px,
            "fee_amount": D("0"),
            "fee_asset": "USD",
            "base_asset": str(o.get("product", "")).split("/")[0].upper(),
            "counterparty": None,
            "source": "api",
        })
    out.sort(key=lambda f: (f["trade_date_ms"], f["external_trade_id"]))
    return out


# ── user_transactions walk (transfers + cash conversions) ──────────────
def _user_transactions_all():
    rows, since = [], 1
    while True:
        b = post_signed("/api/v2/user_transactions/",
                        {"limit": 1000, "sort": "asc", "since_id": since})
        if not b:
            break
        rows += b
        if len(b) < 1000:
            break
        since = max(int(r["id"]) for r in b) + 1
    return rows


def _asset_amounts(r):
    """Non-zero (ASSET, qty) pairs from a user_transactions row."""
    out = []
    for k, v in r.items():
        if k in _STD_KEYS or k.endswith("_usd"):
            continue
        try:
            q = D(str(v))
        except Exception:
            continue
        if q != 0:
            out.append((k.upper(), q))
    # usd participates too (it's in _STD_KEYS to protect the schema fields,
    # but a nonzero usd amount on a type-0/1 row is a real cash move)
    try:
        q = D(str(r.get("usd", 0)))
        if q != 0:
            out.append(("USD", q))
    except Exception:
        pass
    return out


def fetch_activity():
    """(transfers, conversions): transfer rows for venue_transfers + USDG/USD
    conversion fills (type 2)."""
    xfers, convs = [], []
    for r in _user_transactions_all():
        ty = str(r.get("type"))
        ts = datetime.strptime(r["datetime"][:26],
                               "%Y-%m-%d %H:%M:%S.%f" if "." in r["datetime"]
                               else "%Y-%m-%d %H:%M:%S").replace(
                                   tzinfo=timezone.utc)
        if ty in ("0", "1"):
            for asset, qty in _asset_amounts(r):
                xfers.append({
                    "venue": VENUE, "account": ACCOUNT, "asset": asset,
                    "qty": qty,          # venue already signs (+in / -out)
                    "transfer_type": "DEPOSIT" if ty == "0" else "WITHDRAWAL",
                    "external_id": str(r["id"]),
                    "event_time": ts, "raw": json.dumps(r)})
        elif ty == "2":
            usdg = D(str(r.get("usdg", 0) or 0))
            usd = D(str(r.get("usd", 0) or 0))
            if usdg == 0:
                continue     # only USDG/USD conversions seen; skip others
            convs.append({
                "external_trade_id": "ut" + str(r["id"]),
                "trade_date_ms": int(ts.timestamp() * 1000),
                "signed_qty": usdg,
                "price": abs(usd / usdg) if usdg else D("1"),
                "fee_amount": D(str(r.get("fee", 0) or 0)),
                "fee_asset": "USD",
                "base_asset": "USDG",
                "counterparty": None,
                "source": "api"})
    return xfers, convs


# ── venue_transfers persistence (UAT middle_office) ────────────────────
DDL = """
CREATE TABLE IF NOT EXISTS venue_transfers (
    id            BIGSERIAL PRIMARY KEY,
    venue         TEXT        NOT NULL,
    account       TEXT        NOT NULL,
    asset         TEXT        NOT NULL,
    qty           NUMERIC(36, 18) NOT NULL,
    transfer_type TEXT,
    external_id   TEXT        NOT NULL,
    event_time    TIMESTAMPTZ NOT NULL,
    raw           JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (venue, account, external_id, asset)
);
CREATE INDEX IF NOT EXISTS idx_vxfer_window
    ON venue_transfers (venue, account, event_time);
"""


def sync_transfers(xfers):
    """Idempotent upsert into venue_transfers. Returns rows inserted."""
    import avgcost_db
    conn = avgcost_db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(DDL)
            n = 0
            for x in xfers:
                cur.execute("""
                    INSERT INTO venue_transfers
                        (venue, account, asset, qty, transfer_type,
                         external_id, event_time, raw)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
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
    fills = stock_fills()
    print(f"stock fills: {len(fills)}  "
          f"({fills[0]['trade_date_ms']} .. {fills[-1]['trade_date_ms']})")
    xf, cv = fetch_activity()
    print(f"transfers: {len(xf)}  conversions: {len(cv)}")
    print("synced new transfer rows:", sync_transfers(xf))
