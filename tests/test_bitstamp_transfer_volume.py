"""Tests for scripts/bitstamp_transfer_volume.py -- the pure parts.

No network, no DB. What must hold:
  * a duplicated .env key resolves to the LAST value (dotenv rule), because
    taking the first one is how a live key got reported as dead;
  * fiat vs crypto is decided by what the row carries, and non-transfer
    types never become legs;
  * a partial month is scaled up to a full one before months are averaged.
"""
from pathlib import Path
import datetime as dt
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import bitstamp_transfer_volume as btv  # noqa: E402


# ── credentials ────────────────────────────────────────────────────────
def test_env_last_takes_the_last_duplicate():
    text = "\n".join([
        "BITSTAMP_API_KEY=stale",
        "OTHER=x",
        "# --- prod block ---",
        "BITSTAMP_API_KEY=live",
    ])
    assert btv.env_last(text, "BITSTAMP_API_KEY") == "live"


def test_env_last_missing_is_none_and_prefix_does_not_match():
    text = "BITSTAMP_API_KEY_OLD=nope\n"
    assert btv.env_last(text, "BITSTAMP_API_KEY") is None


# ── classification ─────────────────────────────────────────────────────
def _row(kind, **amts):
    row = {"id": 1, "datetime": "2026-09-24 01:24:32.696752", "type": kind,
           "fee": "0.00000000", "btc_usd": "0.00", "usd": 0.0, "btc": 0.0,
           "eur": 0.0}
    row.update(amts)
    return row


def test_usd_only_row_is_the_fiat_rail():
    legs = btv.classify(_row("0", usd="250000.00"))
    assert len(legs) == 1
    leg = legs[0]
    assert (leg["rail"], leg["dir"], leg["asset"]) == ("fiat", "in", "USD")
    assert leg["qty"] == 250000.0
    assert leg["ts"] == dt.datetime(2026, 9, 24, 1, 24, 32)


def test_asset_row_is_crypto_and_withdrawal_sign_is_dropped():
    legs = btv.classify(_row("1", jnj="-3.91300000",
                             crypto_txid="0xabc", crypto_network="hoodeth"))
    assert len(legs) == 1
    leg = legs[0]
    assert (leg["rail"], leg["dir"], leg["asset"]) == ("crypto", "out", "JNJ")
    assert leg["qty"] == 3.913


def test_stablecoin_on_chain_is_crypto_not_fiat():
    legs = btv.classify(_row("0", usdg="15000.00", crypto_network="hoodeth"))
    assert legs[0]["rail"] == "crypto"
    assert legs[0]["asset"] == "USDG"


def test_non_transfer_types_produce_no_legs():
    # 68/69 stock-fill markers, 2 cash trade, 14 sub-account transfer
    for kind in ("68", "69", "2", "14", "11"):
        assert btv.classify(_row(kind, nvda="10")) == []


def test_amounts_ignores_schema_fields_and_zero():
    row = _row("0", nvda="0.5", fee="1.00", order_id=99, amc_usd="12",
               eur="0.0", btc="0.0")
    assert btv.amounts(row) == [("NVDA", 0.5)]


# ── pricing fallbacks ──────────────────────────────────────────────────
def test_price_of_prefers_nearest_day_then_vwap_then_zero():
    daily = {"NVDA": {dt.date(2026, 9, 1): 200.0, dt.date(2026, 9, 20): 210.0}}
    vwap = {"NVDA": 205.0, "AMC": 2.5}
    missing = btv.collections.Counter()
    assert btv.price_of("NVDA", dt.date(2026, 9, 18), daily, vwap, missing) == 210.0
    assert btv.price_of("AMC", dt.date(2026, 9, 18), daily, vwap, missing) == 2.5
    assert btv.price_of("FICO", dt.date(2026, 9, 18), daily, vwap, missing) == 0.0
    assert btv.price_of("USDC", dt.date(2026, 9, 18), daily, vwap, missing) == 1.0
    assert missing == {"FICO": 1}


# ── annualisation ──────────────────────────────────────────────────────
def _leg(ts, rail, d, usd):
    return {"ts": ts, "rail": rail, "dir": d, "usd": usd, "asset": "X",
            "qty": 1.0, "px": usd}


def test_partial_month_is_scaled_to_a_full_month_before_averaging():
    # August: 31 legs over the full month. September: 10 legs in the first
    # 10 days (partial). Sep must be normalised, not taken as-is.
    legs = [_leg(dt.datetime(2026, 8, d, 12), "fiat", "in", 100.0)
            for d in range(1, 32)]
    legs += [_leg(dt.datetime(2026, 9, d, 12), "fiat", "in", 100.0)
             for d in range(1, 11)]
    est = btv.annualise_months(legs, ["2026-08", "2026-09"])
    n_yr, u_yr = est["fiat deposit"]
    # Aug -> 31 * 30.4167/31 = 30.42 ; Sep -> 10 * 30.4167/9.0 = 33.80
    # (Sep span runs 1 Sep 00:00 -> last leg 10 Sep 12:00 = 9.5 days)
    aug = 31 * btv.MONTH_DAYS / 31.0
    sep = 10 * btv.MONTH_DAYS / 9.5
    assert abs(n_yr - (aug + sep) / 2 * 12) < 1e-6
    assert abs(u_yr - n_yr * 100.0) < 1e-6
    assert est["crypto deposit"] == (0.0, 0.0)


def test_annualise_window_scales_observed_days_to_365():
    legs = [_leg(dt.datetime(2026, 6, 22), "crypto", "in", 10.0),
            _leg(dt.datetime(2026, 9, 25), "crypto", "in", 20.0),
            _leg(dt.datetime(2026, 9, 25), "crypto", "out", 5.0)]
    est = btv.annualise_window(legs)
    days = 95.0
    assert abs(est["crypto deposit"][0] - 2 * 365 / days) < 1e-9
    assert abs(est["crypto deposit"][1] - 30 * 365 / days) < 1e-9
    assert abs(est["crypto withdrawal"][1] - 5 * 365 / days) < 1e-9
    assert est["fiat deposit"] == (0.0, 0.0)


def test_annualise_window_since_uses_the_cutoff_as_day_zero():
    last = dt.datetime(2026, 9, 25)
    legs = [_leg(last - dt.timedelta(days=40), "fiat", "out", 1.0),  # excluded
            _leg(last - dt.timedelta(days=10), "fiat", "out", 1.0),
            _leg(last, "fiat", "out", 1.0)]
    est = btv.annualise_window(legs, since=last - dt.timedelta(days=30))
    assert abs(est["fiat withdrawal"][0] - 2 * 365 / 30) < 1e-9
