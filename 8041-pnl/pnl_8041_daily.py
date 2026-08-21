"""Portfolio 8041 (Central Risk Book) — DAILY PnL + full-account recon.

  python pnl_8041_daily.py --date 2026-06-15 --mark 199.82

Produces, for the COB --date:
  1. FULL PnL (ALL trades) — every instrument on Binance 810 + HL TRADING_06
     (both map to portfolio 8041): SPCX delta-neutral pair via avg-cost engine
     + every HL futures leg (HYPE, xyz:*) via realized/unrealized/funding/fees.
  2. FULL-ACCOUNT RECON — balance Δ = trade/cash Δ + unrealized + transfers.

Avg-cost replay runs from book inception; only the --date COB is reported.
EOD mark for --date is pinned via --mark (or PINNED_MARKS / the 24/7 feed).
"""
from __future__ import annotations
import argparse
import hashlib
import hmac
import json
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")   # box-drawing chars on Windows cp1252
except Exception:
    pass

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
from engine import Position, apply_fill, unrealized, D, ZERO  # noqa: E402
import avgcost_db as adb  # noqa: E402
import native_common as ntv  # noqa: E402
import equity_marks as eqm  # noqa: E402
from asset_map import std_asset  # noqa: E402


def _load_venue_map():
    """{refdata account name -> venue} from public/refdata/accounts.json (exchange)."""
    p = REPO.parent / "public" / "refdata" / "accounts.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {r["name"]: r["venue"] for r in d.get("exchange", [])}


_VENUE_MAP = _load_venue_map()


def venue_of(account_name):
    """Resolve a snapshot account_name (TK810@BINANCE_USDT_FUTURE) to its venue
    via refdata, matching on the base account (TK810@BINANCE)."""
    for base, ven in sorted(_VENUE_MAP.items(), key=lambda kv: -len(kv[0])):
        if account_name.startswith(base):
            return ven
    for tok in ("BINANCE", "HYPERLIQUID", "ROBINHOOD"):
        if tok in account_name:
            return tok
    return "?"


def _prod_mo_creds():
    """Parse the `#PROD MO DB RO` block from nxgenmo/.env (read-only golden record)."""
    envp = REPO.parent.parent / "nxgenmo" / ".env"
    creds, in_block = {}, False
    for ln in envp.read_text(encoding="utf-8", errors="replace").splitlines():
        s, st = ln.rstrip(), ln.strip()
        if st.startswith("#") and "PROD MO DB RO" in st.upper():
            in_block = True
            continue
        if not in_block:
            continue
        if st.startswith("#"):
            break
        if not st:
            continue
        idxs = [i for i in (s.find(":"), s.find("=")) if i >= 0]
        if not idxs:
            continue
        i = min(idxs)
        creds[s[:i].strip().upper()] = s[i + 1:].strip().strip('"').strip("'")
    return creds


# Two inception mints carry validated intraday times the date-only golden record lacks.
_DINARI_TIME_OVERRIDE = {"MFX00000108": (2026, 6, 12, 14, 4),
                         "MFX00000109": (2026, 6, 12, 19, 23)}


def dinari_spcx_buys(cob_iso):
    """Live Dinari SPCX manual trades (CENTRAL RISK BOOK) up to COB, signed by the
    BOOKED direction: LONG => +qty (cost-basis add), SHORT => -qty (sell). The
    booking is the source of truth — we honour what was booked, not the on-chain
    bridge timing. (Misnamed `_buys` for history; it carries shorts too.)"""
    import psycopg2
    c = _prod_mo_creds()
    conn = psycopg2.connect(host=c["MO_DB_HOST"], port=int(c.get("MO_DB_PORT", "5432")),
                            dbname=c["MO_DB_DATABASE"], user=c["MO_DB_USERNAME"],
                            password=c["MO_DB_PASSWORD"], connect_timeout=15)
    try:
        cur = conn.cursor()
        cur.execute("SET TIMEZONE = 'UTC'")
        cur.execute("""
            SELECT deal_ref, base_amount, price, trade_date, direction
            FROM trades_spot
            WHERE base_asset = 'SPCX' AND counterparty = 'DINARI'
              AND effective_end IS NULL
              AND status <> 'CANCELLED'
              AND portfolio_name LIKE '%%CENTRAL RISK BOOK%%'
              AND trade_date < (%s::date + INTERVAL '1 day')
            ORDER BY trade_date, deal_ref
        """, (cob_iso,))
        rows = cur.fetchall()
    finally:
        conn.close()
    out = []
    for dref, qty, px, td, direction in rows:
        if dref in _DINARI_TIME_OVERRIDE:
            t = ms_at(*_DINARI_TIME_OVERRIDE[dref])
        else:
            t = int(td.timestamp() * 1000)
        sign = D(1) if str(direction).upper() == "LONG" else D(-1)
        out.append({
            "external_trade_id": str(dref),
            "trade_date_ms": t,
            "signed_qty": D(str(qty)) * sign,
            "price": D(str(px)),
            "fee_amount": D("0"),
            "fee_asset": None,
            "base_asset": "SPCXD",
            "source": "manual",
        })
    return out


BITSTAMP_ACCT = "MOON-TOKKA@BITSTAMP"


def bitstamp_moon_spot_buys(cob_iso):
    """Live Bitstamp Moon tokenized-equity spot trades (CENTRAL RISK BOOK) up to
    COB, from the PROD MO DB booking (source of truth), signed by the booked
    direction: LONG => +qty, SHORT => -qty. All legs quote USD; fees are booked
    in USD. Returns one fill dict per booked trade — build_legs groups them into
    one leg per ticker ({TICKER}/USD@BITSTAMP)."""
    import psycopg2
    c = _prod_mo_creds()
    conn = psycopg2.connect(host=c["MO_DB_HOST"], port=int(c.get("MO_DB_PORT", "5432")),
                            dbname=c["MO_DB_DATABASE"], user=c["MO_DB_USERNAME"],
                            password=c["MO_DB_PASSWORD"], connect_timeout=15)
    try:
        cur = conn.cursor()
        cur.execute("SET TIMEZONE = 'UTC'")
        cur.execute("""
            SELECT deal_ref, base_asset, base_amount, price, trade_date, direction,
                   fee_asset, fee_amount, counterparty
            FROM trades_spot
            WHERE account = %s AND effective_end IS NULL
              AND status <> 'CANCELLED'
              AND trade_date < (%s::date + INTERVAL '1 day')
            ORDER BY trade_date, deal_ref
        """, (BITSTAMP_ACCT, cob_iso))
        rows = cur.fetchall()
    finally:
        conn.close()
    out = []
    for dref, base, qty, px, td, direction, fee_asset, fee_amt, cparty in rows:
        sign = D(1) if str(direction).upper() == "LONG" else D(-1)
        out.append({
            "external_trade_id": str(dref),
            "trade_date_ms": int(td.timestamp() * 1000),
            "signed_qty": D(str(qty)) * sign,
            "price": D(str(px)),
            "fee_amount": D(str(fee_amt)) if fee_amt is not None else D("0"),
            "fee_asset": fee_asset,
            "base_asset": str(base).upper(),
            "counterparty": cparty,
            "source": "manual",
        })
    return out


# ── Ethereum-mainnet RFQ maker fills (1inch et al; chain = venue truth) ─
ETH_RFQ_ACCT = "WALLET_CRB_EVM_04_ETHEREUM"
ETH_RFQ_WALLET = "0x391af49b1793529f430c4b5918da6bb237306865"
ETH_WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
ETH_USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
# tokens the ClickHouse rfq_fill source already covers — this legacy blockscout
# walk is only a chain-only ETH/USDC backfill now, so skipping them is correct
# and silent. Anything OUTSIDE both sets is a genuinely new pair: stay loud.
ETH_CH_COVERED = {
    "0xdac17f958d2ee523a2206206994597c13d831ec7",   # USDT
    "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599",   # WBTC
    "0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf",   # CBBTC
}
ETH_RFQ_API = ("https://eth.blockscout.com/api/v2/addresses/"
               + ETH_RFQ_WALLET + "/token-transfers")


def ethereum_rfq_events():
    """Ethereum-mainnet RFQ maker fills (WETH/USDC) for the ETH RFQ wallet,
    from Blockscout token transfers — same construction as the Robinhood
    chain leg: a tx with two-way flow nets to one fill; WETH in + USDC out =
    BUY ETH, WETH out + USDC in = SELL. Maker pays no fee leg on-chain.
    Live since 2026-07-13 (1inch venue in rfq_fill). Returns [fill dicts]."""
    def get(params):
        url = _bs_url(
            ETH_RFQ_API
            + (("?" + urllib.parse.urlencode(params)) if params else ""))
        for attempt in range(8):
            try:
                r = urllib.request.urlopen(urllib.request.Request(
                    url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30)
                d = json.loads(r.read())
                # a 200 whose body lacks "items" is an error payload — treating
                # it as a page silently ENDS pagination and truncates history
                # (caused the 2026-07-15 fill hole on the Robinhood leg)
                if isinstance(d, dict) and "items" in d:
                    return d
            except (urllib.error.HTTPError, urllib.error.URLError):
                if attempt == 7:
                    raise
            time.sleep(min(20, 2 * (attempt + 1)))
        raise RuntimeError("eth.blockscout kept returning non-page bodies")

    cutoff = None
    last = _stored_max("trade_date", "%@ETHEREUM")
    if last is not None:
        cutoff = last - timedelta(hours=_args.backfill_hours)
    transfers, params = [], None
    while True:
        d = get(params)
        items = d.get("items", [])
        transfers += items
        params = d.get("next_page_params")
        if not params:
            break
        if cutoff is not None and items:
            oldest = datetime.strptime(items[-1]["timestamp"].split(".")[0],
                                       "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            if oldest < cutoff:
                break
    by_tx = defaultdict(list)
    for t in transfers:
        by_tx[t["transaction_hash"].lower()].append(t)
    out = []
    for tx, ts in by_tx.items():
        ins, outs = defaultdict(int), defaultdict(int)
        for t in ts:
            tok = t.get("token") or {}
            addr = (tok.get("address_hash") or tok.get("address") or "").lower()
            frm = (t.get("from") or {}).get("hash", "").lower()
            to = (t.get("to") or {}).get("hash", "").lower()
            val = int((t.get("total") or {}).get("value") or 0)
            if frm == ETH_RFQ_WALLET:
                outs[addr] += val
            if to == ETH_RFQ_WALLET:
                ins[addr] += val
        if not (ins and outs):
            continue                       # funding transfer, not a fill
        legs_ = set(ins) | set(outs)
        if not legs_ <= {ETH_WETH, ETH_USDC}:
            if not legs_ <= {ETH_WETH, ETH_USDC} | ETH_CH_COVERED:
                print(f"  (ethereum-rfq: tx {tx[:14]} has UNKNOWN tokens "
                      f"{sorted(legs_ - {ETH_WETH, ETH_USDC} - ETH_CH_COVERED)}"
                      " — extend leg mapping)")
            continue
        weth_in, weth_out = ins.get(ETH_WETH, 0), outs.get(ETH_WETH, 0)
        usdc_in, usdc_out = ins.get(ETH_USDC, 0), outs.get(ETH_USDC, 0)
        qty = D(weth_in - weth_out) / D(10) ** 18
        usdc = D(usdc_in - usdc_out) / D(10) ** 6
        if qty == 0 or usdc == 0:
            continue                       # same-token in+out, not a fill
        when = ts[0]["timestamp"]
        t_ms = int(datetime.strptime(when.split(".")[0], "%Y-%m-%dT%H:%M:%S")
                   .replace(tzinfo=timezone.utc).timestamp() * 1000)
        out.append({
            "external_trade_id": tx + ":ETH",
            "trade_date_ms": t_ms,
            "signed_qty": qty,             # +WETH = BUY, -WETH = SELL
            "price": abs(usdc / qty),
            "fee_amount": D("0"),
            "fee_asset": "USDC",
            "base_asset": "ETH",
            "source": "api",
        })
    return out


CH = ("https://jp-clickhouse-api.internal.tokkalabs.com:443/"
      "?user=prod_ro&password=scCtp%21Ez8%233h%23LK8")

INCEPTION = "2026-06-12"   # SPCX book start (avg-cost replay anchor)
PINNED_MARKS = {"2026-06-14": "168.01", "2026-06-15": "199.82"}   # user-pinned EOD marks

_ap = argparse.ArgumentParser(description="Portfolio 8041 daily PnL + recon")
_ap.add_argument("--date", default="2026-06-15", help="COB day YYYY-MM-DD")
_ap.add_argument("--mark", default=None, help="EOD mark for --date (overrides pinned/feed)")
_ap.add_argument("--no-pull", action="store_true",
                 help="skip venue trade ingest + recon; compute PnL from stored "
                      "trades only (marks from internal snapshot DB)")
_ap.add_argument("--ingest-only", action="store_true",
                 help="pull + fold + save all trades to the DB, then exit "
                      "(no PnL table, no recon)")
_ap.add_argument("--recon", action="store_true",
                 help="force the full-account recon to run even under --no-pull")
_ap.add_argument("--verify", action="store_true",
                 help="health check: report any leg whose memoized position "
                      "drifts from its fills, then exit (read-only, no repair)")
_ap.add_argument("--rebuild", metavar="INSTRUMENT",
                 help="re-fold a leg's memo chronologically and exit; pass ALL "
                      "to re-fold every leg that has drifted")
_ap.add_argument("--bmark", action="append", default=[], metavar="TICKER=PX",
                 help="pin a Bitstamp tokenized-equity EOD mark, e.g. "
                      "--bmark SPY=746.3 (repeatable; overrides the xyz/Yahoo feeds)")
# 48h lookback: CH rfq_fill rows can arrive DAYS late (collector backfill) —
# a 6h window left 07-11..07-28 late rows permanently behind the watermark
# (found in the 2026-07-30 recon sweep; run rh_ch_repair.py for older windows)
_ap.add_argument("--backfill-hours", type=int, default=48, metavar="N",
                 help="how far past the newest stored fill the incremental "
                      "chain pulls page back (default 6h). Raise it to re-pull "
                      "through a hole left by a truncated earlier run")
_ap.add_argument("--only", default=None, metavar="VENUE",
                 help="ingest filter: pull only sources whose name contains "
                      "this substring (BINANCE / HYPERLIQUID_SPOT / "
                      "HYPERLIQUID_FUTURES / BITSTAMP / ROBINHOOD) — other "
                      "venues' stored fills are untouched")
_args, _ = _ap.parse_known_args()
COB = _args.date
BMARK = {}
for _bm in _args.bmark:
    if "=" in _bm:
        _k, _v = _bm.split("=", 1)
        BMARK[_k.strip().upper()] = _v.strip()


def _drange(a, b):
    da, db = datetime.strptime(a, "%Y-%m-%d"), datetime.strptime(b, "%Y-%m-%d")
    out, d = [], da
    while d <= db:
        out.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return out


DAYS = _drange(INCEPTION, COB)
MARK_CUTOFFS = [(datetime.strptime(INCEPTION, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")] + DAYS


def day_of(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def ms_at(y, mo, d, h, mi):
    return int(datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp() * 1000)


def _hl_end_ms():
    """Dynamic upper bound for HL userFillsByTime pulls: now + 1 day. A fixed
    constant here silently truncates every fill after it (was 1782200000000 =
    2026-06-23 07:33 UTC, which dropped ~16h of fills once the book traded past
    it). Evaluated per-call so it never expires."""
    return int(time.time() * 1000) + 86_400_000


def env(key):
    for line in (REPO / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return None


# ── Binance UM perp fills (papi userTrades) ────────────────────────────
BIN_UM_SYMBOLS = ("SPCXUSDT", "QQQUSDT", "XAGUSDT",
                  # added 2026-07-13: traded since ~Jul 9 but absent from this
                  # list — their fills were silently missing from the store
                  # (found via ClickHouse cross-check; recon USDT CHECK +5,719)
                  "CLUSDT", "SPYUSDT", "USARUSDT",
                  # added 2026-07-14 (same CH cross-check for COB-13);
                  # ETHUSDC is USDC-quoted — legs derive quote from sym[-4:]
                  "SKHYUSDT", "DRAMUSDT", "ETHUSDC",
                  # added 2026-07-16 (CH cross-check for COB-15): ownership
                  # verified via papi userTrades (id 8460227116, SELL 0.928)
                  "ETHUSDT",
                  # added 2026-07-28 (CH cross-check after 4-day gap): ownership
                  # verified via papi userTrades (NVDA id 13529600 SELL 3.72,
                  # BTC id 542284456 BUY 0.092); BTCUSDC is USDC-quoted
                  "NVDAUSDT", "BTCUSDC",
                  # added 2026-08-03 (CH cross-check after a 2-day gap):
                  # AMDUSDT, 1,108 fills from 08-01 00:23. Ownership is not in
                  # doubt here — the sweep filtered on user_id 127002, which
                  # IS TK810@BINANCE_USDT_FUTURE.
                  "AMDUSDT",
                  # added 2026-08-04: BE-P round-trip on 08-03 (100 contracts,
                  # open+closed inside the 11:00 hour) — caught by the board's
                  # untracked-legs banner, its first live catch
                  "BEUSDT",
                  # added 2026-07-30 (recon sweep CH cross-check): PLTR traded
                  # 07-16..07-23 (venue -1.07 vs book 0 on the dashboard),
                  # ORCL 4 fills 07-23
                  "PLTRUSDT", "ORCLUSDT",
                  # added 2026-07-28 (snapshot cross-check for recon dashboard):
                  # live positions with no trade leg; ownership verified via
                  # fromId=0 walks (CRWV id 2379680, INTC id 36104859, BTC id
                  # 7908889985) — papi userTrades ignores startTime seeds here
                  "CRWVUSDT", "INTCUSDT", "BTCUSDT",
                  # added 2026-07-31 (recon untracked-leg warning after window
                  # extension to 06-10): 2-contract test short 06-11..06-12,
                  # closed, realized -5.86 (12 fills via papi userTrades)
                  "HYPEUSDT")


def _bin_um_instrument(symbol):
    """UM symbol -> store instrument label (quote-aware: ETHUSDC != USDT)."""
    return f"{symbol[:-4]}-P/{symbol[-4:]}@BINANCE_USDT_FUTURE"


def _stored_max(expr, pattern, extra=""):
    """max(<expr>) over stored fills for instruments LIKE pattern (None if
    empty) — drives incremental fetch starts so routine top-ups don't
    re-download full venue history every run."""
    conn = adb.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT max({expr}) FROM trades_spot_avgcost "
                f"WHERE instrument LIKE %s {extra}", (pattern,))
            return cur.fetchone()[0]
    finally:
        conn.close()


_HL_OVERLAP_MS = 6 * 3600 * 1000     # re-fetch window; dedup absorbs overlap


def _hl_start(pattern, extra=""):
    ts = _stored_max("trade_date", pattern, extra)
    if ts is None:
        return 1778000000000
    return max(1778000000000, int(ts.timestamp() * 1000) - _HL_OVERLAP_MS)


def binance_um_events(symbol):
    """userTrades for one UM symbol -> canonical fill dicts (fromId walk,
    resumed from the last stored trade id; full walk for a fresh leg)."""
    key, secret = env("810.BINANCE_API_KEY"), env("810.BINANCE_API_SECRET")
    H = {"X-MBX-APIKEY": key}

    def sget(path, params):
        p = dict(params)
        p["timestamp"] = int(time.time() * 1000)
        p["recvWindow"] = 60000
        qs = urllib.parse.urlencode(p)
        sig = hmac.new(secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
        r = urllib.request.urlopen(urllib.request.Request(
            f"https://papi.binance.com{path}?{qs}&signature={sig}", headers=H), timeout=20)
        return json.loads(r.read())

    fills, seen = [], set()
    last = _stored_max("external_trade_id::bigint",
                       _bin_um_instrument(symbol),
                       extra="AND external_trade_id ~ '^[0-9]+$'")
    if last is not None:
        from_id = int(last)          # re-fetch the last id; dedup drops it
    else:
        seed = sget("/papi/v1/um/userTrades", {"symbol": symbol, "limit": 1000, "startTime": 1781000000000})
        from_id = min(int(f["id"]) for f in seed) if seed else 0
    while True:
        batch = sget("/papi/v1/um/userTrades", {"symbol": symbol, "limit": 1000, "fromId": from_id})
        if not batch:
            break
        new = [f for f in batch if int(f["id"]) not in seen]
        for f in new:
            seen.add(int(f["id"]))
        fills += new
        if len(batch) < 1000:
            break
        from_id = max(int(f["id"]) for f in batch) + 1
    base = symbol[:-4]                                  # SPCXUSDT -> SPCX
    fills_out = []
    for f in fills:
        sign = D(1) if f["buyer"] else D(-1)
        fills_out.append({
            "external_trade_id": str(f["id"]),
            "trade_date_ms": int(f["time"]),
            "signed_qty": D(f["qty"]) * sign,
            "price": D(f["price"]),
            "fee_amount": D(f["commission"]),
            "fee_asset": f.get("commissionAsset", "USDT"),
            "base_asset": base,
            "source": "api",
        })
    return fills_out


# ── Binance plain-spot fills (tk810 SPOT wallet — NOT the papi margin acct) ──
# B-token tokenized equities (long spot vs HL xyz perp shorts), traded since
# 2026-07-10 but absent from every PnL until 2026-07-14 (found via the same
# ClickHouse binance-spot cross-check; ownership verified via /api/v3/myTrades).
# ETHUSDC is pulled through the same walk but folds into ETH/USDC@ETHEREUM_RFQ
# — the 27.7268 ETH bought 2026-07-10 was withdrawn (sub->master->chain) to the
# RFQ wallet the same hour and IS that leg's inventory cost basis (Dinari-on-HL
# pattern; leg position then ties to the wallet's ETH+WETH balance).
BIN_SPOT_SYMBOLS = ("SPCXBUSDT", "CRCLBUSDT", "MUBUSDT", "NVDABUSDT", "SNDKBUSDT",
                    # added 2026-07-28: stable conversions (id 461029887, BUY
                    # 400k USDC @ 1.0008 on 07-27) were invisible to the store
                    # and broke the recon dashboard; USDC/USDT leg tracks them
                    "USDCUSDT",
                    # added 2026-07-30 (recon sweep): WBTC 152 fills 07-17
                    # (+50k WBTC/-50k USDT break); TSLAB 07-06 break — TSLAB
                    # is absent from ClickHouse entirely, venue API only
                    "WBTCUSDT", "TSLABUSDT",
                    # added 2026-08-03 (day-by-day walk): BNB fee top-up on
                    # 06-11 (BUY 0.2 @ 599.04, id 1522852330) was invisible —
                    # BNB balance moves only via these buys + fee burn
                    "BNBUSDT")
BIN_SPOT_ACCT = "TK810@BINANCE_SPOT"


def _bin_spot_instrument(symbol):
    """Spot symbol -> store instrument label (quote-aware via sym[-4:])."""
    return f"{symbol[:-4]}/{symbol[-4:]}@BINANCE_SPOT"


_BNB_1M = {}


def _bnb_usdt_at(ms):
    """BNBUSDT 1m close at the fill minute (public klines, cached) — spot
    commissions are charged in BNB (fee discount) and must be valued at
    fill time, not treated as USD."""
    minute = ms - ms % 60000
    if minute not in _BNB_1M:
        r = urllib.request.urlopen(
            "https://api.binance.com/api/v3/klines?symbol=BNBUSDT&interval=1m"
            f"&startTime={minute}&limit=1000", timeout=20)
        for k in json.loads(r.read()):
            _BNB_1M[int(k[0])] = D(str(k[4]))
    if minute in _BNB_1M:
        return _BNB_1M[minute]
    older = [t for t in _BNB_1M if t <= minute]
    return _BNB_1M[max(older)] if older else None


def binance_spot_events(symbol, instrument=None):
    """myTrades for one plain-spot symbol -> canonical fill dicts (fromId walk,
    resumed from the last stored NUMERIC trade id — the ETH RFQ leg mixes these
    with 0x…:ETH chain ids, which the numeric filter skips). BNB commissions
    are converted to USDT at the fill-minute BNBUSDT close."""
    key, secret = env("810.BINANCE_API_KEY"), env("810.BINANCE_API_SECRET")
    H = {"X-MBX-APIKEY": key}

    def sget(path, params):
        p = dict(params)
        p["timestamp"] = int(time.time() * 1000)
        p["recvWindow"] = 60000
        qs = urllib.parse.urlencode(p)
        sig = hmac.new(secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
        r = urllib.request.urlopen(urllib.request.Request(
            f"https://api.binance.com{path}?{qs}&signature={sig}", headers=H), timeout=20)
        return json.loads(r.read())

    inst = instrument or _bin_spot_instrument(symbol)
    fills, seen = [], set()
    last = _stored_max("external_trade_id::bigint", inst,
                       extra="AND external_trade_id ~ '^[0-9]+$'")
    if last is not None:
        from_id = int(last)          # re-fetch the last id; dedup drops it
    else:
        seed = sget("/api/v3/myTrades", {"symbol": symbol, "limit": 1000,
                                         "startTime": 1781000000000})
        if not seed:
            return []
        from_id = min(int(f["id"]) for f in seed)
    while True:
        batch = sget("/api/v3/myTrades", {"symbol": symbol, "limit": 1000, "fromId": from_id})
        if not batch:
            break
        new = [f for f in batch if int(f["id"]) not in seen]
        for f in new:
            seen.add(int(f["id"]))
        fills += new
        if len(batch) < 1000:
            break
        from_id = max(int(f["id"]) for f in batch) + 1
    base = symbol[:-4]                                  # SPCXBUSDT -> SPCXB
    out = []
    for f in fills:
        sign = D(1) if f["isBuyer"] else D(-1)
        fee, fa = D(f["commission"]), f.get("commissionAsset", "USDT")
        # convert BNB fees to USDT — EXCEPT on the BNB leg itself, where BNB
        # is the base and the recon deducts base-denominated fees from the
        # base balance (same shape as HL spot HYPE fees)
        if fee and fa == "BNB" and base != "BNB":
            px = _bnb_usdt_at(int(f["time"]))
            if px is not None:
                fee, fa = fee * px, "USDT"
        out.append({
            "external_trade_id": str(f["id"]),
            "trade_date_ms": int(f["time"]),
            "signed_qty": D(f["qty"]) * sign,
            "price": D(f["price"]),
            "fee_amount": fee,
            "fee_asset": fa,
            "base_asset": "ETH" if inst.startswith("ETH/") else base,
            "source": "api",
        })
    return out


def binance_funding_by_day():
    """Signed FUNDING_FEE income per (day, symbol), all UM symbols."""
    key, secret = env("810.BINANCE_API_KEY"), env("810.BINANCE_API_SECRET")
    H = {"X-MBX-APIKEY": key}

    def sget(params):
        p = dict(params)
        p["timestamp"] = int(time.time() * 1000)
        p["recvWindow"] = 60000
        qs = urllib.parse.urlencode(p)
        sig = hmac.new(secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
        r = urllib.request.urlopen(urllib.request.Request(
            "https://papi.binance.com/papi/v1/um/income?" + qs + "&signature=" + sig,
            headers=H), timeout=20)
        return json.loads(r.read())

    rows, cursor = [], 1781000000000
    while True:
        batch = sget({"incomeType": "FUNDING_FEE", "startTime": cursor, "limit": 1000})
        if not batch:
            break
        rows += batch
        if len(batch) < 1000:
            break
        cursor = max(int(r["time"]) for r in batch) + 1
    by_day = {}
    for r in rows:
        k = (day_of(int(r["time"])), str(r.get("symbol", "")))
        by_day[k] = by_day.get(k, ZERO) + D(str(r["income"]))
    return by_day


# ── Hyperliquid SPCXD spot fills + mints ───────────────────────────────
def hl_spcxd_events():
    addr = env("TRADING_06@HYPERLIQUID")

    def info(b):
        for attempt in range(8):
            try:
                r = urllib.request.urlopen(urllib.request.Request(
                    "https://api.hyperliquid.xyz/info",
                    data=json.dumps(b).encode(),
                    headers={"Content-Type": "application/json"}), timeout=30)
                return json.loads(r.read())
            except urllib.error.HTTPError as e:
                if e.code != 429 or attempt == 7:
                    raise
            time.sleep(min(30, 5 * (attempt + 1)))

    fills, seen = [], set()
    start = _hl_start("SPCXD/USDC@HYPERLIQUID_SPOT",
                      extra="AND venue = 'HYPERLIQUID'")
    while True:
        batch = info({"type": "userFillsByTime", "user": addr,
                      "startTime": start, "endTime": _hl_end_ms(), "aggregateByTime": False})
        if not batch:
            break
        fresh = [f for f in batch if f["tid"] not in seen]
        for f in fresh:
            seen.add(f["tid"])
        fills += [f for f in fresh if f["coin"] == "@465"]
        bmax = max(int(f["time"]) for f in batch)
        if len(batch) < 2000 or bmax <= start:
            break
        start = bmax + 1
    fills_out = []
    for f in fills:
        sign = D(1) if f["side"] == "B" else D(-1)
        fills_out.append({
            "external_trade_id": str(f["tid"]),
            "trade_date_ms": int(f["time"]),
            "signed_qty": D(f["sz"]) * sign,
            "price": D(f["px"]),
            "fee_amount": D(f["fee"]),
            "fee_asset": f.get("feeToken", "USDC"),
            "base_asset": "SPCXD",
            "source": "api",
        })
    return fills_out


def hl_perp_events_by_coin():
    """HL futures fills (HYPE, xyz:*) grouped by coin -> canonical fill dicts.
    Fees on perps are USDC (already USD)."""
    addr = env("TRADING_06@HYPERLIQUID")

    def info(b):
        for attempt in range(8):
            try:
                r = urllib.request.urlopen(urllib.request.Request(
                    "https://api.hyperliquid.xyz/info",
                    data=json.dumps(b).encode(),
                    headers={"Content-Type": "application/json"}), timeout=30)
                return json.loads(r.read())
            except urllib.error.HTTPError as e:
                if e.code != 429 or attempt == 7:
                    raise
            time.sleep(min(30, 5 * (attempt + 1)))

    fills, seen = [], set()
    start = _hl_start("%@HYPERLIQUID_FUTURES")
    while True:
        batch = info({"type": "userFillsByTime", "user": addr,
                      "startTime": start, "endTime": _hl_end_ms(),
                      "aggregateByTime": False})
        if not batch:
            break
        fresh = [f for f in batch if f["tid"] not in seen]
        for f in fresh:
            seen.add(f["tid"])
        fills += [f for f in fresh if not f["coin"].startswith("@")]
        bmax = max(int(f["time"]) for f in batch)
        if len(batch) < 2000 or bmax <= start:
            break
        start = bmax + 1
    by_coin = defaultdict(list)
    for f in fills:
        sign = D(1) if f["side"] == "B" else D(-1)
        by_coin[f["coin"]].append({
            "external_trade_id": str(f["tid"]),
            "trade_date_ms": int(f["time"]),
            "signed_qty": D(f["sz"]) * sign,
            "price": D(f["px"]),
            "fee_amount": D(f["fee"]) if f.get("feeToken") == "USDC" else D("0"),
            "fee_asset": "USDC",
            "base_asset": f["coin"],
            "source": "api",
        })
    return by_coin


# ── Robinhood-chain RFQ maker fills (Blockscout = chain truth) ─────────
# PRO key: metered ONLY via the api.blockscout.com/<chain_id> gateway —
# instance domains (robinhoodchain./eth.blockscout.com) silently IGNORE the
# apikey param (verified 2026-07-21: zero dashboard usage). Free tier =
# 100K credits/day @ 5 RPS, ~20 credits/call. Unset key → anonymous instance.
BLOCKSCOUT_KEY = env("BLOCKSCOUT_API_KEY")


def _bs_url(url):
    """Route a Blockscout instance URL through the metered PRO gateway."""
    if not BLOCKSCOUT_KEY:
        return url
    url = url.replace("https://robinhoodchain.blockscout.com/",
                      "https://api.blockscout.com/4663/")
    url = url.replace("https://eth.blockscout.com/",
                      "https://api.blockscout.com/1/")
    return url + ("&" if "?" in url else "?") + "apikey=" + BLOCKSCOUT_KEY


RH_ACCT = "WALLET_CRB_EVM_02_ROBINHOOD"
RH_WALLET = "0x9f736f87e6293ac1bd9142e257dbfac8b7acf1ae"
RH_USDG = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"   # quote token, 6 dp
RH_API = ("https://robinhoodchain.blockscout.com/api/v2/addresses/"
          + RH_WALLET + "/token-transfers")


def _rh_ts(item):
    return datetime.strptime(item["timestamp"].split(".")[0],
                             "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


RH_PULL_WORKERS = 8


def _rh_parallel_transfers(get, cutoff):
    """Token transfers newest -> cutoff via parallel keyset-cursor workers.

    Blockscout's token-transfers cursor is a plain (block_number, index)
    keyset and ACCEPTS FABRICATED CURSORS (verified 2026-07-21): a cursor at
    block B returns items strictly below B. So the gap's block range is split
    into disjoint sub-ranges paged concurrently — same transfer set as the
    serial walk, ~Nx faster. Worker i starts at (top+1, 0) and keeps only
    items above its floor (= next worker's top), so ranges tile exactly with
    no boundary holes; identity-dedup guards any residue. The oldest worker
    ignores its floor and stops on the cutoff timestamp, mirroring the serial
    loop's semantics (extra already-stored fills are absorbed by id-dedup).
    8 workers x ~4.4s/page ~= 2 req/s, well under the PRO tier's 5 req/s."""
    first = get(None)
    items0 = first.get("items", [])
    if not items0 or not first.get("next_page_params") \
            or _rh_ts(items0[-1]) < cutoff:
        return items0                       # whole gap fits in one page
    head_blk = items0[0]["block_number"]
    head_ts = _rh_ts(items0[0])
    # binary-search the cutoff block: newest transfer below `mid` older than
    # cutoff => floor can sit at mid. ~13 probes (~260 credits) — far cheaper
    # than the hundreds of overshoot pages a padded rate estimate costs.
    lo, hi = 0, head_blk
    while hi - lo > 2000:
        mid = (lo + hi) // 2
        pr = get({"block_number": mid, "index": 0}).get("items", [])
        if pr and _rh_ts(pr[0]) >= cutoff:
            hi = mid       # needed fills still below mid -> floor is lower
        else:
            lo = mid       # everything below mid predates cutoff
    lo_blk = lo
    bounds = [head_blk - (head_blk - lo_blk) * i // RH_PULL_WORKERS
              for i in range(RH_PULL_WORKERS + 1)]     # descending edges

    def pull(top, floor, is_oldest):
        out, params = [], (None if top == head_blk
                           else {"block_number": top + 1, "index": 0})
        while True:
            d = get(params)
            items = d.get("items", [])
            out += [t for t in items
                    if is_oldest or t["block_number"] > floor]
            params = d.get("next_page_params")
            if not params:
                return out
            if items and ((is_oldest and _rh_ts(items[-1]) < cutoff)
                          or (not is_oldest
                              and items[-1]["block_number"] <= floor)):
                return out

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=RH_PULL_WORKERS) as ex:
        futs = [ex.submit(pull, bounds[i], bounds[i + 1],
                          i == RH_PULL_WORKERS - 1)
                for i in range(RH_PULL_WORKERS)]
        chunks = [f.result() for f in futs]

    seen, out = set(), []
    for t in (x for c in chunks for x in c):
        k = (t.get("transaction_hash"),
             ((t.get("token") or {}).get("address_hash")),
             (t.get("from") or {}).get("hash"),
             (t.get("to") or {}).get("hash"),
             (t.get("total") or {}).get("value"),
             t.get("block_number"), t.get("index"), t.get("log_index"))
        if k not in seen:
            seen.add(k)
            out.append(t)
    print(f"  (robinhood: parallel pull {len(out)} transfers via "
          f"{RH_PULL_WORKERS} workers, blocks {lo_blk}..{head_blk})")
    return out


def robinhood_rfq_events():
    """Robinhood-chain RFQ maker fills for the CRB EVM wallet, read from the
    chain itself (Blockscout token transfers) — the venue truth. ClickHouse
    production.rfq_fill is NOT used: it records the whole RFQ service with no
    maker column, and was verified to silently drop fills (1 of 688 as of
    2026-07-02). A swap tx nets to one fill per non-USDG token: token in +
    USDG out = BUY, token out + USDG in = SELL, price = USDG/token. The maker
    wallet pays no gas and no fee leg exists on-chain, so fees are 0.
    Returns {ticker -> [canonical fill dicts]}."""
    def get(params):
        url = _bs_url(
            RH_API + (("?" + urllib.parse.urlencode(params)) if params else ""))
        for attempt in range(12):
            try:
                r = urllib.request.urlopen(urllib.request.Request(
                    url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30)
                d = json.loads(r.read())
                # require "items": a 200 error body (e.g. "Internal server
                # error" JSON) has no items key, and passing it through ends
                # pagination silently — that truncated Jul-15-2026 history
                if isinstance(d, dict) and "items" in d:
                    return d
            except (urllib.error.HTTPError, urllib.error.URLError):
                if attempt == 11:
                    raise
            time.sleep(min(30, 2 * (attempt + 1)))
        raise RuntimeError("Blockscout kept returning non-page bodies")

    cutoff = None                     # incremental: stop past known history
    last = _stored_max("trade_date", "%@ROBINHOOD")
    if last is not None:
        # bridge past the newest stored fill (dedup absorbs the overlap;
        # 2 days proved needlessly slow at ~5k fills/day chain volume)
        cutoff = last - timedelta(hours=_args.backfill_hours)
    transfers, params = [], None
    if BLOCKSCOUT_KEY and cutoff is not None:
        transfers = _rh_parallel_transfers(get, cutoff)
    else:
        while True:
            d = get(params)
            items = d.get("items", [])
            transfers += items
            params = d.get("next_page_params")
            if not params:
                break
            if cutoff is not None and items:
                oldest = datetime.strptime(      # pages run newest -> oldest
                    items[-1]["timestamp"].split(".")[0],
                    "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                if oldest < cutoff:
                    break             # older fills already stored (id-dedup)

    by_tx = defaultdict(list)
    for t in transfers:
        by_tx[t["transaction_hash"].lower()].append(t)

    by_ticker = defaultdict(list)
    for tx, ts in by_tx.items():
        ins, outs, meta = defaultdict(int), defaultdict(int), {}
        for t in ts:
            tok = t.get("token") or {}
            addr = (tok.get("address_hash") or "").lower()
            meta[addr] = (str(tok.get("symbol") or "?").upper(),
                          int(tok.get("decimals") or 18))
            frm = (t.get("from") or {}).get("hash", "").lower()
            to = (t.get("to") or {}).get("hash", "").lower()
            val = int((t.get("total") or {}).get("value") or 0)
            if frm == RH_WALLET:
                outs[addr] += val
            if to == RH_WALLET:
                ins[addr] += val
        if not (ins and outs):
            continue                      # funding transfer, not a fill
        when = ts[0]["timestamp"]         # 2026-06-30T14:02:28.000000Z
        t_ms = int(datetime.strptime(when, "%Y-%m-%dT%H:%M:%S.%fZ")
                   .replace(tzinfo=timezone.utc).timestamp() * 1000)
        for side, legs_, quote_ in (("BUY", ins, outs), ("SELL", outs, ins)):
            base = [a for a in legs_ if a != RH_USDG]
            if len(base) > 1:
                print(f"  (robinhood: tx {tx[:14]} has {len(base)} base tokens "
                      f"one way — cannot split USDG leg, SKIPPED)")
                continue
            if not base:
                continue
            usdg = quote_.get(RH_USDG, 0)
            if usdg == 0:
                print(f"  (robinhood: tx {tx[:14]} {side} has no USDG leg, "
                      f"SKIPPED — transfer combo, not a fill)")
                continue
            addr = base[0]
            ticker, dec = meta[addr]
            qty = Decimal(legs_[addr]) / Decimal(10) ** dec
            px = (Decimal(usdg) / Decimal(10) ** 6) / qty
            sign = D(1) if side == "BUY" else D(-1)
            by_ticker[ticker].append({
                "external_trade_id": tx + ":" + ticker,
                "trade_date_ms": t_ms,
                "signed_qty": qty * sign,
                "price": px,
                "fee_amount": D("0"),
                "fee_asset": "USDG",
                "base_asset": ticker,
                "source": "api",
            })
    return by_ticker


# ── EOD marks from ClickHouse ──────────────────────────────────────────
def ch_marks(codename):
    exprs = [f"toString(argMaxIf(price, ts_edge_first_seen, ts_edge_first_seen <= "
             f"toUnixTimestamp(toDateTime('{c} 23:59:59'))*1000000)) AS m{i}"
             for i, c in enumerate(MARK_CUTOFFS)]
    sql = (f"SELECT {', '.join(exprs)} FROM production.trade "
           f"WHERE codename='{codename}' "
           f"AND ts_edge_first_seen <= toUnixTimestamp(toDateTime('2026-06-14 23:59:59'))*1000000\n"
           f"FORMAT TabSeparated")
    r = urllib.request.urlopen(urllib.request.Request(CH, data=sql.encode(),
                                                      headers={"Content-Type": "text/plain"}), timeout=60)
    vals = r.read().decode().strip().split("\t")
    return {c: (D(v) if v not in ("", "\\N") else None) for c, v in zip(MARK_CUTOFFS, vals)}


def f(x, dp=2):
    return "—" if x is None else f"{float(x):,.{dp}f}"


def marks_for(account, inst_like, cutoffs):
    """EOD mark per cutoff day for (account, instrument) = the venue
    position-snapshot index/mark price at that day's ~00:0x EOD boundary.
    Same source as the recon's unsettled_pnl. Missing days are absent."""
    import psycopg2
    from pg import PG_HOST, PG_PORT, PG_USER, PG_PASS, PG_DB
    conn = psycopg2.connect(host=PG_HOST, port=PG_PORT, user=PG_USER,
                            password=PG_PASS, database=PG_DB, connect_timeout=15)
    out = {}
    try:
        cur = conn.cursor()
        for d in cutoffs:
            bnd = datetime.strptime(d, "%Y-%m-%d") + timedelta(days=1)
            cur.execute("""
                SELECT index_price FROM tq_hist_position
                WHERE account_name = %s AND instrument ILIKE %s
                  AND record_ts >= %s AND record_ts < %s
                ORDER BY record_ts LIMIT 1
            """, (account, inst_like, bnd, bnd + timedelta(minutes=60)))
            r = cur.fetchone()
            if r and r[0] is not None:
                out[d] = D(str(r[0]))
    finally:
        conn.close()
    return out


BIN_ACCT = "TK810@BINANCE_USDT_FUTURE"
HLS_ACCT = "TRADING_06@HYPERLIQUID_SPOT"
HLF_ACCT = "TRADING_06@HYPERLIQUID_FUTURES"


def hl_perp_instrument(coin):
    """HL perp coin -> instrument label (matches the venue snapshot form)."""
    return coin + "-P/USD@HYPERLIQUID_FUTURES"


def _tag(fills, venue, counterparty=None):
    """Stamp per-fill venue/counterparty so multiple sources can share one
    instrument and still record their true origin (e.g. Dinari on the HL
    spot leg). Returns the same list, fills mutated in place."""
    for f in fills:
        f["venue"] = venue
        f["counterparty"] = counterparty
    return fills


def build_legs():
    """List of (leg_labels, fills) for every stream feeding the engine.

    Fills for a shared instrument MUST be merged here so ingest folds them as
    one chronological stream — the SPCXD spot leg combines HL api fills with
    the Dinari manual cost-basis buys (which predate the api fills), each
    tagged with its own venue/counterparty."""
    def _want(label):
        return _args.only is None or _args.only.upper() in label.upper()

    legs = []
    if _want("BINANCE"):
        for sym in BIN_UM_SYMBOLS:
            legs.append((
                {"venue": venue_of(BIN_ACCT), "account": BIN_ACCT,
                 "instrument": _bin_um_instrument(sym), "product": "PERP",
                 "quote_asset": sym[-4:], "counterparty": None},
                _tag(binance_um_events(sym), venue_of(BIN_ACCT)),
            ))
    if _want("BINANCE_SPOT"):
        for sym in BIN_SPOT_SYMBOLS:
            legs.append((
                {"venue": venue_of(BIN_SPOT_ACCT), "account": BIN_SPOT_ACCT,
                 "instrument": _bin_spot_instrument(sym), "product": "SPOT",
                 "quote_asset": sym[-4:], "counterparty": None},
                _tag(binance_spot_events(sym), venue_of(BIN_SPOT_ACCT)),
            ))
    if _want("HYPERLIQUID_SPOT"):
        hl_spot_leg = {"venue": venue_of(HLS_ACCT), "account": HLS_ACCT,
                       "instrument": "SPCXD/USDC@HYPERLIQUID_SPOT", "product": "SPOT",
                       "quote_asset": "USDC", "counterparty": None}
        spot_fills = (_tag(hl_spcxd_events(), venue_of(HLS_ACCT))
                      + _tag(dinari_spcx_buys(COB), "DINARI", "DINARI"))
        legs.append((hl_spot_leg, spot_fills))
    if _want("HYPERLIQUID_FUTURES"):
        for coin, fills in hl_perp_events_by_coin().items():
            legs.append((
                {"venue": venue_of(HLF_ACCT), "account": HLF_ACCT,
                 "instrument": hl_perp_instrument(coin), "product": "PERP",
                 "quote_asset": "USDC", "counterparty": None},
                _tag(fills, venue_of(HLF_ACCT)),
            ))
    # Bitstamp Moon tokenized-equity spot legs (booked in the PROD MO DB) — one
    # leg per ticker. Each fill keeps its own booked counterparty; only the venue
    # is stamped (not via _tag, which would clobber counterparty).
    if _want("BITSTAMP"):
        # source switched 2026-07-28: venue API (order_history stock fills +
        # user_transactions USDG conversions) replaces the PROD MO DB booking
        # (bitstamp_moon_spot_buys kept above for reference/backfill)
        import bitstamp_source
        bven = venue_of(BITSTAMP_ACCT)
        _cob_end = int((datetime(int(COB[:4]), int(COB[5:7]), int(COB[8:10]),
                                 tzinfo=timezone.utc)
                        + timedelta(days=1)).timestamp() * 1000)
        _bs_fills = bitstamp_source.stock_fills(before_ms=_cob_end)
        _, _bs_convs = bitstamp_source.fetch_activity()
        _bs_fills += [c for c in _bs_convs if c["trade_date_ms"] < _cob_end]
        by_ticker = defaultdict(list)
        for bf in _bs_fills:
            by_ticker[bf["base_asset"]].append(bf)
        for ticker, tf in sorted(by_ticker.items()):
            for bf in tf:
                bf["venue"] = bven
            legs.append((
                {"venue": bven, "account": BITSTAMP_ACCT,
                 "instrument": ticker + "/USD@BITSTAMP", "product": "SPOT",
                 "quote_asset": "USD", "counterparty": None},
                tf,
            ))
    # Robinhood-chain RFQ maker legs (chain = venue truth, via Blockscout) —
    # one leg per ticker, quoted in USDG ($1 stable). A Blockscout outage is
    # non-fatal: stored RH fills remain and only the incremental top-up is
    # skipped — but the day being computed may then be missing fresh RH fills.
    rh_events = {}
    if _want("ROBINHOOD"):
        try:
            # source switched 2026-07-28: ClickHouse rfq_fill (maker column
            # live since ~07-06, covers zerox + arcus) replaces the Blockscout
            # walk; same '{tx}:{TICKER}' ids so the store dedups the overlap.
            # robinhood_rfq_events (chain) kept below as explicit fallback.
            import robinhood_ch_source
            _rh_last = _stored_max("trade_date", "%@ROBINHOOD")
            _rh_since = (int((_rh_last - timedelta(hours=_args.backfill_hours))
                             .timestamp() * 1000) if _rh_last else None)
            rh_events = robinhood_ch_source.ch_rfq_events(_rh_since)
            # chain backfill: ClickHouse is primary but has verified gaps
            # (879 chain-only fills incl the whole 06-29 first trading day);
            # walk the chain over the same window and add anything CH lacks,
            # tagged source='chain' so the gap stays measurable.
            try:
                import chain_transfers
                _ch_ids = {f["external_trade_id"]
                           for fl in rh_events.values() for f in fl}
                _bf_start = (_rh_last - timedelta(hours=_args.backfill_hours)
                             if _rh_last else datetime(2026, 6, 29,
                                                       tzinfo=timezone.utc))
                _added = 0
                for _tk, _fl in chain_transfers.chain_fills(
                        "ROBINHOOD", _bf_start).items():
                    for _f in _fl:
                        if _f["external_trade_id"] not in _ch_ids:
                            rh_events.setdefault(_tk, []).append(_f)
                            _added += 1
                if _added:
                    print(f"  (robinhood: +{_added} chain-only fills "
                          "backfilled)")
            except Exception as e:
                print(f"  WARNING: RH chain backfill skipped ({e})")
        except Exception as e:
            print(f"  WARNING: Robinhood chain pull FAILED ({e}) — RH top-up "
                  "SKIPPED this run; stored fills only")
    for ticker, rf in sorted(rh_events.items()):
        legs.append((
            {"venue": "ROBINHOOD", "account": RH_ACCT,
             "instrument": ticker + "/USDG@ROBINHOOD", "product": "SPOT",
             "quote_asset": "USDG", "counterparty": None},
            _tag(rf, "ROBINHOOD"),
        ))
    # Ethereum-mainnet RFQ maker legs (1inch). Source switched 2026-07-29:
    # ClickHouse rfq_fill (all FIVE pairs: ETH/WBTC/CBBTC vs USDC/USDT — the
    # old eth.blockscout walk covered ETH/USDC only). Full-history pull every
    # run (volume is small); '{tx}:{BASE}' ids dedup against stored rows.
    if _want("ETHEREUM"):
        try:
            import eth_ch_source
            eth_events = eth_ch_source.ch_rfq_events()
            try:
                _ids = {f["external_trade_id"]
                        for fl in eth_events.values() for f in fl}
                _added = 0
                for _f in ethereum_rfq_events():
                    if _f["external_trade_id"] not in _ids:
                        _f["source"] = "chain"
                        eth_events.setdefault(("ETH", "USDC"), []).append(_f)
                        _added += 1
                if _added:
                    print(f"  (eth rfq: +{_added} chain-only fills backfilled)")
            except Exception as e:
                print(f"  WARNING: ETH chain backfill skipped ({e})")
        except Exception as e:
            print(f"  WARNING: Ethereum ClickHouse pull FAILED ({e}) — ETH "
                  "RFQ top-up SKIPPED this run; stored fills only")
            eth_events = {}
        # tk810 plain-spot ETHUSDC buys are this wallet's inventory: bought on
        # Binance 2026-07-10, withdrawn via master to the RFQ wallet the same
        # hour — folded into the SAME leg (Dinari-on-HL pattern) so avg cost is
        # real and the leg position ties to the wallet's ETH+WETH balance.
        try:
            bin_eth = binance_spot_events("ETHUSDC",
                                          instrument="ETH/USDC@ETHEREUM_RFQ")
        except Exception as e:
            print(f"  WARNING: Binance spot ETHUSDC pull FAILED ({e}) — "
                  "cost-basis top-up SKIPPED this run; stored fills only")
            bin_eth = []
        eth_events.setdefault(("ETH", "USDC"), [])
        for (base, quote), ef in sorted(eth_events.items()):
            extra = (_tag(bin_eth, "BINANCE")
                     if (base, quote) == ("ETH", "USDC") else [])
            legs.append((
                {"venue": "ETHEREUM", "account": ETH_RFQ_ACCT,
                 "instrument": f"{base}/{quote}@ETHEREUM_RFQ",
                 "product": "SPOT", "quote_asset": quote,
                 "counterparty": None},
                _tag(ef, "ETHEREUM") + extra,
            ))
    legs += stored_native_legs({lg["instrument"] for lg, _ in legs})
    return legs


def stored_native_legs(have):
    """Native legs read from the stored avg-cost table, with EMPTY fills.

    Native's userFills retention is ~8 min, so a per-report pull can't rebuild a
    day — Native enters the PnL purely via what stream_native_fills.py has
    accumulated into trades_spot_avgcost. Empty fills => ingest is a no-op; the
    PnL loop still reads each leg's stored realized / position / avg-cost."""
    out = []
    try:
        conn = adb.connect()
        try:
            for inst, acct, prod, quote in adb.distinct_instruments(conn):
                if "@NATIVECORE" in inst and inst not in have:
                    out.append(({"venue": ntv.EXCH, "account": acct, "instrument": inst,
                                 "product": prod, "quote_asset": quote,
                                 "counterparty": None}, []))
        finally:
            conn.close()
    except Exception as e:
        print(f"  (native legs skipped: {e})")
    return out


# Fold + insert one leg. Shared with the Native fills collector (single code
# path; self-heals back-dated fills / position drift via a chronological refold).
ingest_leg = adb.ingest_leg


if _args.verify:
    _conn = adb.connect()
    try:
        report = adb.verify_legs(_conn)
    finally:
        _conn.close()
    bad = [r for r in report if r[3] != 0]
    print(f"avgcost health check — {len(report)} legs, {len(bad)} DRIFTED")
    print(f"  {'instrument':40} {'tip_qty':>16} {'net_sum':>16} {'drift':>14}")
    for inst, tip, net, drift in report:
        flag = "  <-- DRIFT (run --rebuild)" if drift != 0 else ""
        print(f"  {inst[:40]:40} {float(tip):>16,.4f} {float(net):>16,.4f} "
              f"{float(drift):>14,.4f}{flag}")
    sys.exit(1 if bad else 0)

if _args.rebuild:
    _conn = adb.connect()
    try:
        if _args.rebuild.upper() == "ALL":
            targets = [r[0] for r in adb.verify_legs(_conn) if r[3] != 0]
            print(f"--rebuild ALL: {len(targets)} drifted leg(s) to re-fold")
        else:
            targets = [_args.rebuild]
        for inst in targets:
            n, tip = adb.refold_leg(_conn, inst)
            print(f"  re-folded {inst:42} {n} rows -> tip qty {float(tip):,.4f}")
        if not targets:
            print("  nothing to rebuild (no drift).")
    finally:
        _conn.close()
    sys.exit(0)

if _args.no_pull:
    print("--no-pull: skipping venue trade ingest; computing from STORED trades "
          "only (marks from internal snapshot DB).")
    _conn = adb.connect()
    try:
        LEGS = [({"venue": venue_of(acct), "account": acct, "instrument": inst,
                  "product": prod, "quote_asset": quote, "counterparty": None}, [])
                for inst, acct, prod, quote in adb.distinct_instruments(_conn)]
    finally:
        _conn.close()
    print(f"  {len(LEGS)} instruments read from trades_spot_avgcost")
else:
    print("Ingesting venue fills into trades_spot_avgcost (incremental top-up)...")
    # connect AFTER the (slow) venue pull — a connection opened first idles
    # through ~30min of API walks and gets killed by the server (seen 2026-07-16)
    LEGS = build_legs()
    _conn = adb.connect()
    try:
        for leg, fills in LEGS:
            ins, fresh, reason = ingest_leg(_conn, leg, fills)
            tag = f"  [SELF-HEALED: re-folded ({reason})]" if reason else ""
            print(f"  {leg['instrument']:42} +{ins} new (of {fresh} fresh, "
                  f"{len(fills)} pulled){tag}")
    finally:
        _conn.close()

if _args.ingest_only:
    print("--ingest-only: trades pulled, folded and saved to DB. Done.")
    sys.exit(0)

# ── FULL-ACCOUNT PnL (ALL trades) for the COB day, then the recon ───────
day = DAYS[-1]
w0 = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
w1 = w0 + timedelta(days=1)
sod_day = (w0 - timedelta(days=1)).strftime("%Y-%m-%d")

import account_recon as ar  # noqa: E402
spcx_marks = marks_for(BIN_ACCT, "%SPCX%", MARK_CUTOFFS)
for _d, _m in PINNED_MARKS.items():
    spcx_marks.setdefault(_d, D(_m))
if _args.mark:
    spcx_marks[COB] = D(_args.mark)
fund = binance_funding_by_day()
hl_fund = defaultdict(lambda: ZERO)
for r in ar.hl_funding():
    if w0.timestamp() * 1000 <= int(r["time"]) < w1.timestamp() * 1000:
        hl_fund[r["delta"]["coin"]] += D(str(r["delta"]["usdc"]))

mo_map = ar.instrument_mo_map()


def _xyz_hist_mark(ticker, date_iso):
    """HL xyz historical EOD index_price for a ticker on date_iso (tq_hist_position
    on the HL futures account), or None where 8041 does not also hold the perp."""
    return marks_for(HLF_ACCT, "xyz:" + ticker + "%", [date_iso]).get(date_iso)


def _bitstamp_mark(ticker, date_iso, *, is_cob):
    """EOD mark for a Bitstamp tokenized-equity ticker: pinned --bmark -> Yahoo
    (ETFs) -> HL xyz historical EOD -> live xyz oraclePx (COB only) -> None."""
    return eqm.resolve_mark(ticker, date_iso, is_cob=is_cob, pinned=BMARK,
                            hist_fn=_xyz_hist_mark)


_conn = adb.connect()
pnl_rows = []
try:
    for leg, _fills in LEGS:
        inst = leg["instrument"]
        realized, fee_usd, n_api, n_man = adb.window_agg(_conn, inst, w0, w1)
        sod_q, sod_a = adb.pos_at(_conn, inst, w0)
        eod_q, eod_a = adb.pos_at(_conn, inst, w1)
        if "@NATIVECORE" in inst:
            # Native equity legs are marked off the matching HL xyz: perp index
            # (agreed mark source); cash/unmapped legs carry no mark.
            hl = ntv.hl_instrument_for(inst.split("/")[0])
            if hl:
                cm = marks_for(HLF_ACCT, hl.split("-P/")[0] + "%", MARK_CUTOFFS)
                em = cm.get(day)
                sm = cm.get(sod_day)
            else:
                em = sm = None
        elif "@BITSTAMP" in inst or "@ROBINHOOD" in inst:
            # Tokenized-equity spot leg: HL xyz oracle / Yahoo (ETFs) EOD mark.
            ticker = inst.split("/")[0]
            em = _bitstamp_mark(ticker, day, is_cob=True)
            sm = _bitstamp_mark(ticker, sod_day, is_cob=False) if D(str(sod_q)) != 0 else None
        elif "SPCX" in inst:
            em = spcx_marks.get(day)
            sm = spcx_marks.get(sod_day)
        elif "@BINANCE_SPOT" in inst:
            # B-token tokenized equity — underlying ticker's xyz/Yahoo EOD mark
            # (SPCXB never lands here: caught by the SPCX branch above).
            ticker = std_asset(inst.split("/")[0])
            em = _bitstamp_mark(ticker, day, is_cob=True)
            sm = _bitstamp_mark(ticker, sod_day, is_cob=False) if D(str(sod_q)) != 0 else None
        elif "@ETHEREUM_RFQ" in inst:
            # ETH inventory leg — marked off the tk810 ETH perp snapshot index
            # (same source as the ETH-P/USDC@BINANCE_USDT_FUTURE hedge leg).
            cm = marks_for(BIN_ACCT, "ETH%", MARK_CUTOFFS)
            em = cm.get(day)
            sm = cm.get(sod_day)
        elif "@BINANCE" in inst:
            # non-SPCX Binance UM perp — marked off its own snapshot index
            coin = inst.split("-P/")[0]
            cm = marks_for(BIN_ACCT, coin + "%", MARK_CUTOFFS)
            em = cm.get(day)
            sm = cm.get(sod_day)
        else:
            coin = inst.split("-P/")[0]
            cm = marks_for(HLF_ACCT, coin + "%", MARK_CUTOFFS)
            em = cm.get(day)
            sm = cm.get(sod_day)
        sod_pos = Position(D(str(sod_q)), D(str(sod_a)))
        eod_pos = Position(D(str(eod_q)), D(str(eod_a)))
        su = unrealized(sod_pos, sm) if (sm and sod_pos.qty != 0) else ZERO
        eu = unrealized(eod_pos, em) if (em and eod_pos.qty != 0) else ZERO
        du = eu - su
        if "@BINANCE" in inst and "-P/" in inst:     # UM perps only (spot: no funding)
            fnd = fund.get((day, inst.split("-P/")[0]
                            + inst.split("-P/")[1].split("@")[0]), ZERO)
        elif leg["product"] == "PERP":
            fnd = hl_fund.get(inst.split("-P/")[0], ZERO)
        else:
            fnd = ZERO
        net = D(str(realized)) + du + fnd - D(str(fee_usd))
        pnl_rows.append((
            leg["venue"], leg["account"], inst, n_api, n_man,
            D(str(sod_q)), D(str(eod_q)), em, D(str(realized)), du, fnd,
            D(str(fee_usd)), net,
        ))
finally:
    _conn.close()
pnl_total = sum((r[12] for r in pnl_rows), ZERO)
real_total = sum((r[8] for r in pnl_rows), ZERO)
unr_total = sum((r[9] for r in pnl_rows), ZERO)
fnd_total = sum((r[10] for r in pnl_rows), ZERO)
fee_total = sum((r[11] for r in pnl_rows), ZERO)


def _to_mo(inst):
    """Map an instrument label to instrument_mo (HL spot/perp fallbacks)."""
    if inst in mo_map:
        return mo_map[inst]
    if "@BITSTAMP" in inst or "@ROBINHOOD" in inst or "@BINANCE_SPOT" in inst:
        return inst.split("/")[0]                  # AAPL/USD@BITSTAMP -> AAPL
    if "@NATIVECORE" in inst:
        return inst.split("/")[0]                  # SPCXB/USDT@NATIVECORE -> SPCXB
    if "/USDC@HYPERLIQUID_SPOT" in inst:
        return mo_map.get(inst.split("/")[0], inst.split("/")[0])
    full = inst + "-P/USD@HYPERLIQUID_FUTURES"
    return mo_map.get(full, inst)


pcols = ["venue", "account", "instrument", "Trades_API", "Trades_Manual", "SOD qty", "EOD qty",
         "EOD Px", "realized", "ΔUnreal", "funding", "fees", "net PnL"]
pdata = [[r[0], r[1], _to_mo(r[2])[:34], str(r[3]), str(r[4]), f(r[5], 4), f(r[6], 4),
          f(r[7], 4), f(r[8]), f(r[9]), f(r[10]), f(r[11]), f(r[12])]
         for r in pnl_rows]
pdata.append(["TOTAL", "", "", "", "", "", "", "", f(real_total), f(unr_total),
              f(fnd_total), f(fee_total), f(pnl_total)])
pw = [max(len(pcols[i]), *(len(r[i]) for r in pdata)) for i in range(len(pcols))]


def _pbar(a, m, c):
    return a + m.join("─" * (pw[i] + 2) for i in range(len(pw))) + c


def _pline(cs, center=False):
    return "│" + "│".join(" " + (cs[i].center(pw[i]) if center else
                                 (cs[i].ljust(pw[i]) if i in (0, 1, 2) else cs[i].rjust(pw[i]))) + " "
                          for i in range(len(cs))) + "│"


print(f"\n{'='*108}\nPORTFOLIO 8041 — DAILY PnL (ALL TRADES) — COB {day} 23:59:59 UTC")
print(_pbar("┌", "┬", "┐"))
print(_pline(pcols, True))
print(_pbar("├", "┼", "┤"))
for r in pdata:
    print(_pline(r))
print(_pbar("└", "┴", "┘"))
_spcx_book = sum((r[12] for r in pnl_rows if "SPCX" in r[2]), ZERO)
print(f"ALL-TRADES NET PnL {day} = {f(pnl_total)} USD   "
      f"(SPCX book {f(_spcx_book)} + HL perps)")
# Combined with Native Core MTM (NAV Δ marked off the same HL perp index).
try:
    import native_pnl_snapshot as _nmtm  # noqa: E402
    _native_nav = _nmtm.nav_delta(day)
except Exception as _e:
    _native_nav = None
    print(f"(native MTM unavailable: {_e})")
if _native_nav is not None:
    print(f"ALL-TRADES + NATIVE MTM {day} = {f(pnl_total + _native_nav)} USD   "
          f"(all-trades {f(pnl_total)} + native NAV Δ {f(_native_nav)})")

if _args.no_pull and not _args.recon:
    print("\n(recon skipped: --no-pull; pass --recon to run it with live venue data)")
else:
    try:
        ar.run_recon(day)
    except Exception as e:
        print(f"\n(recon skipped: {e})")
    try:
        ar.run_position_recon(day)
    except Exception as e:
        print(f"\n(position recon skipped: {e})")
