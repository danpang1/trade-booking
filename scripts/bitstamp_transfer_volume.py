"""Bitstamp deposit / withdrawal volume, split crypto vs fiat, in USD, annualised.

Built for the venue-onboarding questionnaire lines "estimated amount / number
of deposits (withdrawals) per year in crypto (fiat)". Reads the venue's own
ledger so the answer is what Bitstamp itself sees, not a proxy.

Source  POST /api/v2/user_transactions/ (HMAC v2, since_id walk, full history).
        type 0 = deposit, 1 = withdrawal. Types 68/69 are zero-amount
        tokenized-stock fill markers and are dropped; 2 (cash trade) and 14
        (sub-account transfer) are not deposits and are dropped too.
Rail    A row whose only non-zero amount is `usd` is the FIAT rail (wire).
        A row carrying an asset quantity is CRYPTO (on-chain: hoodeth tokenized
        equities, ethereum USDC/USDG, ...). One row can carry one asset.
Value   Crypto legs are quantities, so each is priced at the same-day USD
        price implied by our own fills in trades_spot_avgcost (nearest traded
        date, any venue), else the asset's all-time VWAP. Stablecoins are 1.0.
        --no-price skips the DB: counts stay exact, crypto USD covers
        stablecoins only.

Credentials (never printed): BITSTAMP_API_KEY / BITSTAMP_API_SECRET env vars,
else `KEY=value` lines in the repo .env. When a key appears twice in .env the
LAST occurrence wins -- the python-dotenv rule, and the one ACE follows. Taking
the first match reads a shadowed stale duplicate and reports the key as dead.

Run
---
    python scripts/bitstamp_transfer_volume.py                   # full window
    python scripts/bitstamp_transfer_volume.py --basis 30d
    python scripts/bitstamp_transfer_volume.py --basis months --months 2026-09
    python scripts/bitstamp_transfer_volume.py --basis months \\
        --months 2026-08,2026-09 --headroom 0.05 --csv legs.csv

--basis full    whole observed window scaled to 365 days (understates a
                ramping account).
--basis 30d     last 30 days scaled to 365.
--basis months  each listed month normalised to a 30.44-day month, averaged,
                x12. A partial current month is scaled up to a full one.
--headroom      fraction added on top of the annualised figure (0.05 = +5%).
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENV = REPO / ".env"
HOST = "www.bitstamp.net"
PAGE = 1000
MONTH_DAYS = 365.0 / 12.0

# Schema fields on a user_transactions row that are not asset amounts.
_STD = {
    "id", "datetime", "type", "fee", "btc_usd", "order_id", "eur",
    "crypto_txid", "crypto_network", "crypto_tx_venue_id",
    "originator_address", "destination_address",
}
STABLE = {"USD", "USDC", "USDG", "USDT", "PYUSD", "RLUSD", "DAI"}
DEPOSIT, WITHDRAWAL = "0", "1"


# ── credentials ────────────────────────────────────────────────────────
def env_last(text: str, key: str):
    """Value of the LAST `key=value` line in a .env text, or None.

    python-dotenv keeps the last occurrence of a duplicated key, so this is
    what a dotenv-loading process actually sees.
    """
    val = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(key + "="):
            val = s.split("=", 1)[1].strip()
    return val


def credentials():
    key = os.environ.get("BITSTAMP_API_KEY")
    sec = os.environ.get("BITSTAMP_API_SECRET")
    if key and sec:
        return key, sec
    if ENV.exists():
        text = ENV.read_text(encoding="utf-8", errors="replace")
        key = key or env_last(text, "BITSTAMP_API_KEY")
        sec = sec or env_last(text, "BITSTAMP_API_SECRET")
    if key and sec:
        return key, sec
    raise SystemExit(
        "Bitstamp credentials missing: set BITSTAMP_API_KEY / "
        "BITSTAMP_API_SECRET or add them to " + str(ENV)
    )


# ── venue API ──────────────────────────────────────────────────────────
def _headers(key, sec, method, path, query, body):
    nonce = uuid.uuid4().hex + uuid.uuid4().hex[:4]
    ts = str(int(time.time() * 1000))
    ctype = "application/x-www-form-urlencoded" if body else ""
    msg = ("BITSTAMP " + key + method + HOST + path + query + ctype
           + nonce + ts + "v2" + body)
    sig = hmac.new(sec.encode(), msg.encode(), hashlib.sha256).hexdigest()
    h = {
        "X-Auth": "BITSTAMP " + key,
        "X-Auth-Signature": sig,
        "X-Auth-Nonce": nonce,
        "X-Auth-Timestamp": ts,
        "X-Auth-Version": "v2",
    }
    if ctype:
        h["Content-Type"] = ctype
    return h


def post_signed(key, sec, path, params):
    body = urllib.parse.urlencode(params)
    for attempt in range(4):
        req = urllib.request.Request(
            "https://" + HOST + path,
            data=body.encode(),
            headers=_headers(key, sec, "POST", path, "", body),
            method="POST",
        )
        try:
            return json.loads(urllib.request.urlopen(req, timeout=60).read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < 3:
                time.sleep(2 * (attempt + 1))
                continue
            detail = e.read()[:200].decode("utf-8", "replace")
            raise SystemExit(f"Bitstamp {path} HTTP {e.code}: {detail}")


def user_transactions(key, sec, log=print):
    rows, since = [], 1
    while True:
        page = post_signed(key, sec, "/api/v2/user_transactions/",
                           {"limit": PAGE, "sort": "asc", "since_id": since})
        if not page:
            break
        rows += page
        log(f"  user_transactions +{len(page)} (total {len(rows)})")
        if len(page) < PAGE:
            break
        since = max(int(r["id"]) for r in page) + 1
    return rows


# ── classification (pure) ──────────────────────────────────────────────
def amounts(row):
    """Non-zero (ASSET, qty) pairs on a user_transactions row."""
    out = []
    for k, v in row.items():
        if k in _STD or k.endswith("_usd") or k == "btc":
            continue
        try:
            q = float(v)
        except (TypeError, ValueError):
            continue
        if q:
            out.append((k.upper(), q))
    return out


def classify(row):
    """One leg dict per asset amount on a deposit/withdrawal row, else []."""
    kind = str(row.get("type"))
    if kind not in (DEPOSIT, WITHDRAWAL):
        return []
    ts = dt.datetime.strptime(row["datetime"][:19], "%Y-%m-%d %H:%M:%S")
    legs = []
    for asset, qty in amounts(row):
        legs.append({
            "ts": ts,
            "asset": asset,
            "qty": abs(qty),
            "rail": "fiat" if asset == "USD" else "crypto",
            "dir": "in" if kind == DEPOSIT else "out",
        })
    return legs


# ── pricing ────────────────────────────────────────────────────────────
def price_book():
    """({asset: {date: px}}, {asset: vwap}) from our own fills."""
    import cashflow_db

    conn = cashflow_db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                select upper(base_asset), trade_date::date,
                       sum(abs(base_amount) * price)
                           / nullif(sum(abs(base_amount)), 0),
                       sum(abs(base_amount))
                from trades_spot_avgcost
                where price is not null and price > 0
                  and quote_asset in ('USD', 'USDC', 'USDG', 'USDT')
                group by 1, 2
            """)
            rows = cur.fetchall()
    finally:
        conn.close()
    daily = collections.defaultdict(dict)
    num, den = collections.Counter(), collections.Counter()
    for asset, day, px, qty in rows:
        daily[asset][day] = float(px)
        num[asset] += float(px) * float(qty)
        den[asset] += float(qty)
    vwap = {a: num[a] / den[a] for a in den if den[a]}
    return daily, vwap


def price_of(asset, day, daily, vwap, missing):
    if asset in STABLE:
        return 1.0
    book = daily.get(asset)
    if book:
        return book[min(book, key=lambda d: abs((d - day).days))]
    if asset in vwap:
        return vwap[asset]
    missing[asset] += 1
    return 0.0


# ── annualisation (pure) ───────────────────────────────────────────────
BUCKETS = (
    ("crypto", "in", "crypto deposit"),
    ("crypto", "out", "crypto withdrawal"),
    ("fiat", "in", "fiat deposit"),
    ("fiat", "out", "fiat withdrawal"),
)


def totals(legs, pred):
    sel = [x for x in legs if pred(x)]
    return len(sel), sum(x["usd"] for x in sel)


def month_span_days(legs, month):
    """Days of `month` (YYYY-MM) the data actually covers.

    A finished month is its calendar length; the current partial month is
    counted only up to its last leg, so it can be scaled up to a full one.
    """
    y, m = (int(p) for p in month.split("-"))
    start = dt.datetime(y, m, 1)
    nxt = dt.datetime(y + (m == 12), m % 12 + 1, 1)
    last = max((x["ts"] for x in legs), default=start)
    end = min(nxt, last)
    return max((end - start).total_seconds() / 86400.0, 1e-9)


def annualise_months(legs, months):
    """{bucket: (legs/yr, usd/yr)}: each month normalised to a 30.44-day
    month, averaged, x12."""
    out = {}
    for rail, d, name in BUCKETS:
        n_sum = u_sum = 0.0
        for month in months:
            span = month_span_days(legs, month)
            n, u = totals(legs, lambda x, r=rail, dd=d, mm=month: (
                x["rail"] == r and x["dir"] == dd
                and x["ts"].strftime("%Y-%m") == mm))
            n_sum += n * MONTH_DAYS / span
            u_sum += u * MONTH_DAYS / span
        k = len(months)
        out[name] = (n_sum / k * 12.0, u_sum / k * 12.0)
    return out


def annualise_window(legs, since=None):
    """{bucket: (legs/yr, usd/yr)} scaling the window [since, last] to 365d."""
    sel = [x for x in legs if since is None or x["ts"] >= since]
    first = since or min(x["ts"] for x in sel)
    last = max(x["ts"] for x in sel)
    days = max((last - first).total_seconds() / 86400.0, 1e-9)
    out = {}
    for rail, d, name in BUCKETS:
        n, u = totals(sel, lambda x, r=rail, dd=d: (
            x["rail"] == r and x["dir"] == dd))
        out[name] = (n * 365.0 / days, u * 365.0 / days)
    return out


# ── report ─────────────────────────────────────────────────────────────
def _fmt(n):
    return f"{n:,.0f}"


def print_monthly(legs):
    print("Monthly:")
    print("%-9s %26s %26s" % ("", "crypto (n / USD)", "fiat (n / USD)"))
    for month in sorted({x["ts"].strftime("%Y-%m") for x in legs}):
        line = "%-9s" % month
        for rail in ("crypto", "fiat"):
            n, u = totals(legs, lambda x, r=rail, mm=month: (
                x["rail"] == r and x["ts"].strftime("%Y-%m") == mm))
            line += "  %8s / %14s" % (_fmt(n), _fmt(u))
        print(line)
    print()


def print_estimate(title, est, headroom):
    print(title)
    hdr = "%-22s %12s %18s" % ("", "legs / yr", "USD / yr")
    if headroom:
        hdr += "   %12s %18s" % ("+%.0f%% legs" % (headroom * 100),
                                 "+%.0f%% USD" % (headroom * 100))
    print(hdr)
    print("-" * len(hdr))
    for _, _, name in BUCKETS:
        n, u = est[name]
        line = "%-22s %12s %18s" % (name, _fmt(n), _fmt(u))
        if headroom:
            line += "   %12s %18s" % (_fmt(n * (1 + headroom)),
                                      _fmt(u * (1 + headroom)))
        print(line)
    print()


def write_csv(path, legs):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["datetime_utc", "rail", "direction", "asset", "qty",
                    "price_usd", "usd_value"])
        for x in legs:
            w.writerow([x["ts"].strftime("%Y-%m-%d %H:%M:%S"), x["rail"],
                        x["dir"], x["asset"], "%.8f" % x["qty"],
                        "%.6f" % x["px"], "%.2f" % x["usd"]])


def build_legs(rows, daily, vwap):
    missing = collections.Counter()
    legs = []
    for row in rows:
        for leg in classify(row):
            px = price_of(leg["asset"], leg["ts"].date(), daily, vwap, missing)
            leg["px"] = px
            leg["usd"] = leg["qty"] * px
            legs.append(leg)
    legs.sort(key=lambda x: x["ts"])
    return legs, missing


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--basis", choices=("full", "30d", "months"), default="full")
    ap.add_argument("--months", default="",
                    help="comma list of YYYY-MM for --basis months")
    ap.add_argument("--headroom", type=float, default=0.0,
                    help="fraction added to the annualised figure, e.g. 0.05")
    ap.add_argument("--no-price", action="store_true",
                    help="skip the fills DB; crypto USD covers stablecoins only")
    ap.add_argument("--csv", default="", help="write row-level legs here")
    ap.add_argument("--raw", default="",
                    help="reuse a saved user_transactions JSON instead of the API")
    args = ap.parse_args(argv)

    if args.basis == "months" and not args.months:
        ap.error("--basis months needs --months YYYY-MM[,YYYY-MM]")

    if args.raw:
        rows = json.loads(Path(args.raw).read_text(encoding="utf-8"))
        if isinstance(rows, dict):
            rows = rows["user_transactions"]
        print(f"rows: {len(rows)} from {args.raw}")
    else:
        key, sec = credentials()
        print("pulling /api/v2/user_transactions/ ...")
        rows = user_transactions(key, sec)

    daily, vwap = ({}, {}) if args.no_price else price_book()
    legs, missing = build_legs(rows, daily, vwap)
    if not legs:
        raise SystemExit("no deposit/withdrawal rows")

    first, last = legs[0]["ts"], legs[-1]["ts"]
    print(f"window : {first:%Y-%m-%d} -> {last:%Y-%m-%d %H:%M} UTC "
          f"({(last - first).total_seconds() / 86400:.1f} days), "
          f"{len(legs)} legs")
    if missing:
        print(f"unpriced: {dict(missing)}")
    if args.no_price:
        print("crypto USD covers stablecoins only (--no-price)")
    print()

    print("To date:")
    for _, _, name in BUCKETS:
        rail, d = name.split()[0], name.split()[1]
        n, u = totals(legs, lambda x, r=rail, dd=d: (
            x["rail"] == r and x["dir"] == ("in" if dd == "deposit" else "out")))
        print("%-22s %9s %18s" % (name, _fmt(n), _fmt(u)))
    print()
    print_monthly(legs)

    if args.basis == "full":
        est = annualise_window(legs)
        title = "Annualised: full window x 365/days"
    elif args.basis == "30d":
        est = annualise_window(legs, since=last - dt.timedelta(days=30))
        title = "Annualised: last 30 days x 365/30"
    else:
        months = [m.strip() for m in args.months.split(",") if m.strip()]
        est = annualise_months(legs, months)
        title = ("Annualised: avg of %s (each as a 30.44-day month) x 12"
                 % ", ".join(months))
    print_estimate(title, est, args.headroom)

    if args.csv:
        write_csv(args.csv, legs)
        print(f"legs -> {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
