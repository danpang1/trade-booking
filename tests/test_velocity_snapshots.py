"""Pure-logic tests for the Velocity balance + position collectors.

No network: payloads were recorded from the public Data API on 2026-10-01
(`/user/H6JKgKwUaMmGo9XcynpVqTg8ABcTJVtD3qRmSWRMMpt4` and `/stats/markets`)
so the expectations are real venue output, not hand-built fixtures.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import pytest  # noqa: E402
import stream_velocity as pos  # noqa: E402
import stream_velocity_balance as bal  # noqa: E402

FETCH_DT = datetime(2026, 10, 1, 7, 0, tzinfo=timezone.utc)
ACC_ID, ACC_NAME = 999002, "TRADING01@VELOCITY-0"

USER = {
    "account": {
        "balance": "1003900.062500", "totalCollateral": "1002737.114064",
        "freeCollateral": "992166.494209", "health": "99",
        "initialMargin": "10564.599435", "maintenanceMargin": "5689.537288",
        "leverage": "0.2106",
    },
    "positions": [
        {"symbol": "SOL-PERP", "marketIndex": 0, "marginMode": "cross",
         "baseAssetAmount": "-211.440000000", "quoteEntryAmount": "25537.555900",
         "settledPnl": "-1139.997307", "feesAndFunding": "39.451415",
         "liquidationPrice": "4723.417827"},
        {"symbol": "BTC-PERP", "marketIndex": 1, "marginMode": "cross",
         "baseAssetAmount": "-0.059000000", "quoteEntryAmount": "4890.964271",
         "settledPnl": "-144.353757", "feesAndFunding": "48.446623",
         "liquidationPrice": "0.000000"},
        {"symbol": "HYPE-PERP", "marketIndex": 3, "marginMode": "cross",
         "baseAssetAmount": "0.000000000", "quoteEntryAmount": "0.000000",
         "settledPnl": "0", "feesAndFunding": "0", "liquidationPrice": "0"},
    ],
    "balances": [
        {"symbol": "USDT", "marketIndex": 0, "balance": "1003403.373905",
         "openOrders": 0, "liquidationPrice": "0.004512"},
        {"symbol": "SOL", "marketIndex": 1, "balance": "-12.5",
         "openOrders": 0, "liquidationPrice": "0"},
    ],
    "orders": [{"orderId": 1}],
}

MARKETS = {
    "SOL-PERP": {"mark": 118.064, "oracle": 117.95802},
    "BTC-PERP": {"mark": 83678.984783, "oracle": 83437.735201},
}


# ── position collector ─────────────────────────────────────────────────

def test_position_short_entry_mark_upnl():
    r = pos.normalize_position(ACC_ID, ACC_NAME, FETCH_DT, USER["positions"][0], MARKETS)
    assert r["side"] == "short"
    assert r["pos_qty"] == pytest.approx(211.44)
    assert r["avg_entry_price"] == pytest.approx(25537.5559 / 211.44)
    assert r["last_trade_price"] == pytest.approx(118.064)
    assert r["index_price"] == pytest.approx(117.95802)
    # short: mark above entry → negative uPnL
    expected = (118.064 - 25537.5559 / 211.44) * -211.44
    assert r["unsettled_pnl"] == pytest.approx(expected)
    assert r["liquidation_price"] == pytest.approx(4723.417827)
    assert r["instrument"] == "SOL-P/USDT@VELOCITY_FUTURES"
    assert r["instrument_mo"] == "SOLUSDT"
    assert r["instrument_exch"] == "SOL-PERP"
    assert r["exch"] == "VELOCITY_FUTURES"
    assert r["margin"] is None and r["leverage"] is None
    assert r["sync_ts"] == r["update_ts"] == FETCH_DT.replace(tzinfo=None)
    assert json.loads(r["original_data"])["settledPnl"] == "-1139.997307"


def test_position_zero_liq_is_null_and_flat_dropped():
    r = pos.normalize_position(ACC_ID, ACC_NAME, FETCH_DT, USER["positions"][1], MARKETS)
    assert r["liquidation_price"] is None
    assert pos.normalize_position(ACC_ID, ACC_NAME, FETCH_DT, USER["positions"][2], MARKETS) is None


def test_position_without_mark_feed_has_null_prices():
    r = pos.normalize_position(ACC_ID, ACC_NAME, FETCH_DT, USER["positions"][0], {})
    assert r["last_trade_price"] is None
    assert r["index_price"] is None
    assert r["unsettled_pnl"] is None
    assert r["avg_entry_price"] == pytest.approx(25537.5559 / 211.44)


def test_perp_marks_match_on_symbol_not_index(monkeypatch):
    # spot USDT and SOL-PERP both carry marketIndex 0 — must key on perp symbol
    payload = {"markets": [
        {"symbol": "USDT", "marketIndex": 0, "marketType": "spot", "oraclePrice": "0.99935"},
        {"symbol": "SOL-PERP", "marketIndex": 0, "marketType": "perp",
         "oraclePrice": "117.958020", "markPrice": "118.064000"},
    ]}
    monkeypatch.setattr(pos, "_get", lambda path, attempts=5: payload)
    m = pos.fetch_perp_marks()
    assert set(m) == {"SOL-PERP"}
    assert m["SOL-PERP"] == {"mark": 118.064, "oracle": 117.95802}


def test_insert_refused_while_account_id_unset():
    rows = [{"account_id": None, "account_name": ACC_NAME}]
    with pytest.raises(RuntimeError, match="refusing to INSERT"):
        pos._check_account_ids(rows)
    pos._check_account_ids([{"account_id": 1, "account_name": ACC_NAME}])


def test_iter_accounts_skips_unmapped_and_raises_on_empty(monkeypatch):
    listing = [
        {"accountId": "H6JKgKwUaMmGo9XcynpVqTg8ABcTJVtD3qRmSWRMMpt4", "subAccountId": 0, "name": "tokka-labs-0"},
        {"accountId": "NEWSUBACCOUNTxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "subAccountId": 9, "name": "tokka-labs-9"},
    ]
    monkeypatch.setattr(pos, "fetch_subaccounts", lambda: listing)
    monkeypatch.setattr(pos, "fetch_user", lambda acc_id: {"account": {}, "_id": acc_id})
    got = list(pos._iter_accounts())
    assert [g[0] for g in got] == ["H6JKgKwUaMmGo9XcynpVqTg8ABcTJVtD3qRmSWRMMpt4"]
    assert got[0][1]["name"] == "TRADING01@VELOCITY-0"

    monkeypatch.setattr(pos, "fetch_subaccounts", lambda: [])
    with pytest.raises(RuntimeError, match="no sub-accounts"):
        list(pos._iter_accounts())


# ── balance collector ──────────────────────────────────────────────────

def test_equity_row():
    r = bal.normalize_equity(ACC_ID, ACC_NAME, FETCH_DT, USER)
    assert r["instrument"] == "USDT" and r["instrument_type"] == "INST_TYPE_SPOT"
    assert r["total_qty"] == pytest.approx(1003900.0625)
    assert r["avail_qty"] == pytest.approx(992166.494209)
    assert r["frozen_qty"] == pytest.approx(10564.599435)
    raw = json.loads(r["original_data"])
    assert set(raw) == {"account", "balances"}
    assert raw["balances"][0]["balance"] == "1003403.373905"
    assert r["borrowed_qty"] == 0 and r["interest_qty"] == 0


def test_asset_rows_skip_quote_and_flag_borrow():
    assert bal.normalize_asset_row(ACC_ID, ACC_NAME, FETCH_DT, USER["balances"][0]) is None
    r = bal.normalize_asset_row(ACC_ID, ACC_NAME, FETCH_DT, USER["balances"][1])
    assert r["instrument"] == "SOL@VELOCITY_FUTURES"
    assert r["side"] == "short"
    assert r["total_qty"] == pytest.approx(12.5)
    assert r["borrowed_qty"] == pytest.approx(12.5)


def test_balance_position_row():
    r = bal.normalize_position_row(ACC_ID, ACC_NAME, FETCH_DT, USER["positions"][0])
    assert r["instrument"] == "SOL-P/USDT@VELOCITY_FUTURES"
    assert r["instrument_type"] == "INST_TYPE_PERP"
    assert r["side"] == "short"
    assert r["total_qty"] == r["avail_qty"] == pytest.approx(211.44)
    assert r["borrowed_qty"] is None and r["interest_qty"] is None
    assert bal.normalize_position_row(ACC_ID, ACC_NAME, FETCH_DT, USER["positions"][2]) is None


def test_balance_snap_once_dry_run_row_count(monkeypatch):
    meta = {"account_id": ACC_ID, "name": ACC_NAME, "sub": 0}
    empty_meta = {"account_id": ACC_ID, "name": "TRADING01@VELOCITY-1", "sub": 1}
    empty = {"account": {"balance": "0.000000"}, "positions": [], "balances": [], "orders": []}
    monkeypatch.setattr(
        bal, "_iter_accounts", lambda: iter([("H6JK", meta, USER), ("4JiX", empty_meta, empty)])
    )
    # equity + 1 non-quote asset + 2 open positions; empty sub contributes nothing
    assert bal.snap_once(None, dry_run=True) == 4


def test_is_empty():
    assert pos.is_empty({"account": {"balance": "0"}, "positions": [], "balances": []})
    assert not pos.is_empty(USER)
    # a flat account that still holds a non-quote asset is NOT empty
    assert not pos.is_empty({"account": {"balance": "0"}, "positions": [],
                             "balances": [{"symbol": "SOL", "balance": "1"}]})


def test_position_snap_once_dry_run_row_count(monkeypatch):
    meta = {"account_id": ACC_ID, "name": ACC_NAME, "sub": 0}
    monkeypatch.setattr(pos, "_iter_accounts", lambda: iter([("H6JK", meta, USER)]))
    monkeypatch.setattr(pos, "fetch_perp_marks", lambda: MARKETS)
    assert pos.snap_once(None, dry_run=True) == 2
