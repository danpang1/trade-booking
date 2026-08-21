"""EOD marks for tokenized-equity legs (MOON-TOKKA@BITSTAMP tokenized stocks).

Bitstamp Moon holds tokenized US equities/ETFs quoted in USD; the venue exposes
no quote/book, so marks come from two public, no-auth feeds:

  * HL `xyz` HIP-3 perp dex oracle price (metaAndAssetCtxs?dex=xyz) — live
    oraclePx for ~90 US equities/commodities. Same source ACE Terminal and the
    Native equity legs use. Covers most single-name tickers (AAPL, TSLA, NVDA…).
  * Yahoo Finance 1-min chart — for the ETFs HL xyz does NOT list
    (SPY, QQQ, SLV, USO, SGOV). Take the last-trade close of the last 1-min bar
    at/before the COB 23:59:59 UTC cutoff. includePrePost=true is required (the
    US regular session ends 20:00 UTC, so 23:59:59 is post-market); use the
    last-trade close, NOT a bid/ask mid (post-market ETF books are wide).

resolve_mark() precedence (per ticker, per date):
  pinned override  ->  ETF? Yahoo EOD close  ->  HL xyz historical EOD index
  (hist_fn, only where 8041 also holds the xyz perp)  ->  Yahoo EOD close for
  ANY US-listed ticker (2026-07-02+: deterministic historical closes; fixes
  backdated days where xyz hist is missing)  ->  live xyz oraclePx (COB day
  only)  ->  None (carry at cost, unrealized 0, flagged upstream).
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal

# ETFs HL xyz does not list — marked off Yahoo Finance instead.
ETF_YAHOO = ("SPY", "QQQ", "SLV", "USO", "SGOV")

# Tokenized tickers that are NOT the matching US-listed symbol on Yahoo —
# never mark these off Yahoo (a same-named listing would silently mis-mark).
YAHOO_DENY = ("WEEK",)

_XYZ_CACHE: dict[str, Decimal] | None = None


def _D(x):
    if x is None or x == "":
        return None
    return x if isinstance(x, Decimal) else Decimal(str(x))


def xyz_oracle_live():
    """{ticker -> oraclePx Decimal} from the live HL `xyz` dex asset contexts.
    Keys are the bare ticker (the `xyz:` prefix is stripped). Tickers with a
    null oraclePx are omitted. Cached for the process (one call per run)."""
    global _XYZ_CACHE
    if _XYZ_CACHE is not None:
        return _XYZ_CACHE
    req = urllib.request.Request(
        "https://api.hyperliquid.xyz/info",
        data=json.dumps({"type": "metaAndAssetCtxs", "dex": "xyz"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    d = json.loads(urllib.request.urlopen(req, timeout=30).read())
    meta, ctxs = d[0], d[1]
    uni = meta["universe"]
    out = {}
    for i, u in enumerate(uni):
        px = _D(ctxs[i].get("oraclePx")) if i < len(ctxs) else None
        if px is not None:
            out[u["name"].replace("xyz:", "").upper()] = px
    _XYZ_CACHE = out
    return out


def yahoo_eod_mark(symbol, cob_iso):
    """(bar_utc_iso, close Decimal) for `symbol` at the COB 23:59:59 UTC cutoff,
    or None. Pulls 1-min bars in a ±1h window (includePrePost) and returns the
    close of the last bar with ts <= cutoff. last-trade close, not a mid."""
    cutoff = int(datetime.strptime(cob_iso, "%Y-%m-%d")
                 .replace(hour=23, minute=59, second=59, tzinfo=timezone.utc).timestamp())
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/" + symbol +
           "?period1=" + str(cutoff - 3600) + "&period2=" + str(cutoff + 3600) +
           "&interval=1m&includePrePost=true")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=30).read())
        res = d["chart"]["result"][0]
        ts = res["timestamp"]
        close = res["indicators"]["quote"][0]["close"]
    except Exception:
        return None
    last = None
    for t, c in zip(ts, close):
        if c is not None and t <= cutoff:
            last = (t, c)
    if last is None:
        return None
    return (datetime.fromtimestamp(last[0], timezone.utc).isoformat(), Decimal(str(last[1])))


def resolve_mark(ticker, date_iso, *, is_cob, pinned=None, hist_fn=None):
    """Resolve one tokenized-equity EOD mark for `ticker` on `date_iso`.

    hist_fn(ticker, date_iso) -> Decimal|None is the HL xyz historical EOD index
    (tq_hist_position on the HL futures account) — used where 8041 also holds the
    matching xyz perp. is_cob gates the live-oracle fallback to the COB day only
    (metaAndAssetCtxs has no history). Returns Decimal or None.
    """
    t = ticker.upper()
    if pinned and t in pinned:
        return _D(pinned[t])
    if t in ETF_YAHOO:
        y = yahoo_eod_mark(t, date_iso)
        return y[1] if y else None
    if hist_fn is not None:
        h = hist_fn(t, date_iso)
        if h is not None:
            return _D(h)
    if t not in YAHOO_DENY:
        y = yahoo_eod_mark(t, date_iso)
        if y is not None:
            return y[1]
    if is_cob:
        return xyz_oracle_live().get(t)
    return None
