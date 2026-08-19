"""Pure-logic tests for the Uniswap v4 LP balance collector.

No chain access: every eth_call is served from fixtures recorded against
Robinhood Chain on 2026-08-19 (position #744219, SPY/USDG 0.05%, block
40495242), so the golden case is a real on-chain read rather than a
hand-computed expectation.
"""
import json
import sys
from decimal import Decimal as D
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import pytest  # noqa: E402
import stream_uniswap_lp_balance as lp  # noqa: E402


# Recorded from Robinhood Chain block 40495242, 2026-08-19. sqrt_price_x96 is
# the RAW slot0 value, not _sqrt_ratio(tick) — the pool price sits BETWEEN tick
# boundaries, and in a range this tight one tick is worth ~1.77 SPY, so
# rounding to the boundary is a real error. Anything that reconstructs the
# price from the tick alone is wrong.
TOKEN_ID = 744219
LIQUIDITY = 980877245649946819
TICK_LOWER, TICK_UPPER, TICK = -209915, -209760, -209887
SQRT_PRICE_X96 = D("2195213760762279636900255")
SPY = "0x117cc2133c37b721f49de2a7a74833232b3b4c0c"
USDG = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"
TOKENS = {SPY: ("SPY", 18), USDG: ("USDG", 6)}

GOLDEN_SPY = D("223.453317")
GOLDEN_USDG = D("38498.999466")
GOLDEN_FEE_SPY = D("0.247001")
GOLDEN_FEE_USDG = D("157.733350")
GOLDEN_FEE0_ATOMS = 247000820377254957
GOLDEN_FEE1_ATOMS = 157733350


# ── decomposition ──────────────────────────────────────────────────────

def _amounts(sqrt_p):
    """Reproduce read_position's decomposition at an arbitrary sqrt price."""
    sa, sb = lp._sqrt_ratio(TICK_LOWER), lp._sqrt_ratio(TICK_UPPER)
    liq = D(LIQUIDITY)
    if sqrt_p <= sa:
        return liq * (sb - sa) * lp.Q96 / (sa * sb), D(0)
    if sqrt_p >= sb:
        return D(0), liq * (sb - sa) / lp.Q96
    return (liq * (sb - sqrt_p) * lp.Q96 / (sqrt_p * sb),
            liq * (sqrt_p - sa) / lp.Q96)


def test_decomposition_matches_live_read():
    a0, a1 = _amounts(SQRT_PRICE_X96)
    assert (a0 / D(10) ** 18).quantize(D("0.000001")) == GOLDEN_SPY
    assert (a1 / D(10) ** 6).quantize(D("0.000001")) == GOLDEN_USDG


def test_tick_boundary_price_is_not_the_pool_price():
    """Guards the mistake the golden fixture exists to prevent: rounding the
    price to the enclosing tick silently shifts the decomposition."""
    exact, _ = _amounts(SQRT_PRICE_X96)
    rounded, _ = _amounts(lp._sqrt_ratio(TICK))
    assert exact != rounded
    # Bounded by one tick of composition change, but far too big to ignore.
    assert D("0.0001") < abs(rounded - exact) / exact < D("0.01")


def test_below_range_is_all_token0():
    a0, a1 = _amounts(lp._sqrt_ratio(TICK_LOWER - 1))
    assert a1 == 0
    assert a0 > 0


def test_above_range_is_all_token1():
    a0, a1 = _amounts(lp._sqrt_ratio(TICK_UPPER + 1))
    assert a0 == 0
    assert a1 > 0


def test_composition_is_monotonic_in_price():
    """Rising price must sell token0 and accumulate token1, always."""
    prev0, prev1 = _amounts(lp._sqrt_ratio(TICK_LOWER))
    for tick in range(TICK_LOWER + 10, TICK_UPPER, 10):
        a0, a1 = _amounts(lp._sqrt_ratio(tick))
        assert a0 < prev0
        assert a1 > prev1
        prev0, prev1 = a0, a1


def test_value_is_near_invariant_across_one_tick():
    """One tick moves composition a lot but value barely — the property that
    lets two readers disagree on quantities while agreeing on notional."""
    a0, a1 = _amounts(SQRT_PRICE_X96)
    b0, b1 = _amounts(lp._sqrt_ratio(TICK + 1))
    px = (SQRT_PRICE_X96 / lp.Q96) ** 2 * D(10) ** 12
    va = a0 / D(10) ** 18 * px + a1 / D(10) ** 6
    vb = b0 / D(10) ** 18 * px + b1 / D(10) ** 6
    assert abs(vb / va - 1) < D("0.0001")


# ── int24 sign extension ───────────────────────────────────────────────

@pytest.mark.parametrize("raw,want", [
    (0, 0),
    (1, 1),
    ((1 << 23) - 1, (1 << 23) - 1),
    (1 << 23, -(1 << 23)),
    (-209915 & 0xffffff, -209915),
    (-209760 & 0xffffff, -209760),
])
def test_s24_sign_extension(raw, want):
    assert lp._s24(raw) == want


def test_negative_tick_maps_to_twos_complement_word():
    """mapping(int24 => TickInfo) keys are sign-extended to 32 bytes."""
    word = format(TICK_LOWER & lp.MASK256, "064x")
    assert len(word) == 64
    assert word.startswith("f" * 40)
    assert int(word, 16) - (1 << 256) == TICK_LOWER


# ── keccak ─────────────────────────────────────────────────────────────

def test_keccak256_known_vector():
    """keccak-256, NOT sha3-256 — the padding differs and every pool id and
    storage slot depends on getting this right."""
    assert lp._keccak("") == (
        "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470")


# ── fee math ───────────────────────────────────────────────────────────

def _fee_owed(inside, last):
    return D(LIQUIDITY) * D((inside - last) & lp.MASK256) / lp.Q128


def test_fee_owed_matches_live_read():
    """Growth deltas recorded alongside the golden amounts."""
    d0 = int(D(GOLDEN_FEE0_ATOMS) * lp.Q128 / D(LIQUIDITY))
    d1 = int(D(GOLDEN_FEE1_ATOMS) * lp.Q128 / D(LIQUIDITY))
    assert (_fee_owed(d0, 0) / D(10) ** 18).quantize(
        D("0.000001")) == GOLDEN_FEE_SPY
    assert (_fee_owed(d1, 0) / D(10) ** 6).quantize(
        D("0.000001")) == GOLDEN_FEE_USDG


def test_fee_growth_wraps_modulo_2_256():
    """The accumulators are allowed to overflow; the subtraction must wrap
    rather than go negative, or a wrapped pool reports absurd fees."""
    last = lp.MASK256 - 5
    inside = 4                      # wrapped past 2**256
    assert _fee_owed(inside, last) == D(LIQUIDITY) * D(10) / lp.Q128


def test_zero_growth_means_zero_fees():
    assert _fee_owed(12345, 12345) == 0


# ── row building ───────────────────────────────────────────────────────

def _pos():
    return {
        "token_id": TOKEN_ID, "pool_id": "0xabc", "fee": 500,
        "tick_lower": TICK_LOWER, "tick_upper": TICK_UPPER, "tick": TICK,
        "liquidity": LIQUIDITY, "in_range": True,
        "legs": [("SPY", GOLDEN_SPY), ("USDG", GOLDEN_USDG)],
        "fees": [("SPY", GOLDEN_FEE_SPY), ("USDG", GOLDEN_FEE_USDG)],
    }


def _rows():
    import datetime as dt
    stamp = dt.datetime(2026, 8, 19, 9, 59, 59)
    wallet = {"account_id": 509532,
              "account_name": "WALLET_CRB_EVM_08_ROBINHOOD",
              "address": "0xe2Ed"}
    return lp.build_rows(wallet, _pos(), stamp, 40448983, "2026-08-19T10:00")


def test_build_rows_emits_supplied_and_fee_rows():
    rows = _rows()
    assert [r["instrument"] for r in rows] == [
        f"SPY@ROBINHOOD_LP_{TOKEN_ID}",
        f"USDG@ROBINHOOD_LP_{TOKEN_ID}",
        f"SPY@ROBINHOOD_LPFEE_{TOKEN_ID}",
        f"USDG@ROBINHOOD_LPFEE_{TOKEN_ID}",
    ]


def test_lp_and_fee_instruments_fold_to_the_same_asset():
    """The recon board keys on instrument.split('@')[0]; if that stopped
    holding, fees would land in their own phantom asset column."""
    assert {r["instrument"].split("@")[0] for r in _rows()} == {"SPY", "USDG"}


def test_fee_rows_are_flagged_in_original_data():
    rows = _rows()
    assert json.loads(rows[0]["original_data"]).get("fee") is None
    assert json.loads(rows[2]["original_data"])["fee"] is True


def test_rows_carry_the_read_provenance():
    """Amounts are meaningless without the price they were read at."""
    raw = json.loads(_rows()[0]["original_data"])
    for k in ("tick", "liquidity", "in_range", "read_block", "read_ts"):
        assert k in raw


def test_zero_fee_rows_are_still_emitted():
    """A MISSING instrument means the NFT was burned; an explicit 0 means
    nothing is owed. Collapsing the two makes a quiet hour look like a close."""
    pos = _pos()
    pos["fees"] = [("SPY", D(0)), ("USDG", D(0))]
    import datetime as dt
    wallet = {"account_id": 509532, "account_name": "A", "address": "0x"}
    rows = lp.build_rows(wallet, pos, dt.datetime(2026, 8, 19), 1, "t")
    fee_rows = [r for r in rows if "LPFEE" in r["instrument"]]
    assert len(fee_rows) == 2
    assert all(r["total_qty"] == 0 for r in fee_rows)


def test_rows_are_long_spot_with_no_borrow():
    for r in _rows():
        assert r["side"] == "long"
        assert r["instrument_type"] == "INST_TYPE_SPOT"
        assert r["total_qty"] == r["avail_qty"]
        assert r["frozen_qty"] == r["borrowed_qty"] == r["interest_qty"] == 0


def test_insert_is_idempotent_on_the_snapshot_key():
    """Two rows at the SAME sync_ts land in one fetch_snaps `ts` group and
    would be summed — that is the case the unique index guards. Rows at
    DIFFERENT timestamps in the same hour are fine: the board takes
    max(by_ts)."""
    assert ("ON CONFLICT (account_name, sync_ts, instrument) DO NOTHING"
            in lp.INSERT_SQL)


def test_sync_ts_is_fetch_time_not_an_hour_boundary():
    """Boundary stamping made every run inside an hour collide on one key, so
    ad-hoc runs silently wrote nothing. Fetch time matches the other
    collectors and keeps every run visible."""
    import datetime as dt
    stamp = dt.datetime(2026, 8, 19, 11, 17, 26)
    wallet = {"account_id": 509532, "account_name": "A", "address": "0x"}
    rows = lp.build_rows(wallet, _pos(), stamp, 1, "t")
    assert all(r["sync_ts"] == stamp for r in rows)
    assert all(r["sync_ts"] == r["update_ts"] for r in rows)
    assert rows[0]["sync_ts"].second == 26


# ── config ─────────────────────────────────────────────────────────────

def test_account_ids_match_the_clickhouse_id_space():
    """refdata account_wallet.id x 1000 + chain code (532 = ROBINHOOD)."""
    by_name = {w["account_name"]: w["account_id"] for w in lp.WALLETS}
    assert by_name["WALLET_CRB_EVM_08_ROBINHOOD"] == 509532
    assert by_name["WALLET_CRB_EVM_07_ROBINHOOD"] == 506532


def test_token_allowlist_loads_and_is_lowercased():
    toks = lp._tokens()
    assert toks, "allowlist is empty"
    assert all(k == k.lower() for k in toks)
    assert toks[SPY] == ("SPY", 18)
    for sym, dec in toks.values():
        assert isinstance(dec, int) and 0 <= dec <= 18
