"""Pure-logic tests for the read-only Binance gateway (no network, no Vault)."""
import hashlib
import hmac
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlencode

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import binance_proxy as gw  # noqa: E402
import binance_vip_loan_ltv as vip  # noqa: E402


# ── path policy ─────────────────────────────────────────────────────

@pytest.mark.parametrize("path", [
    "/sapi/v1/loan/vip/request/interestRate",
    "/sapi/v1/loan/vip/ongoing/orders",
    "/api/v3/account",
    "/sapi/v1/asset/get-funding-asset",
    "/sapi/v1/capital/withdraw/history",
    "/sapi/v1/capital/deposit/hisrec",
    "/api/v3/myTrades",
    "/api/v3/openOrders",
    "/sapi/v1/sub-account/list",
])
def test_reads_are_allowed(path):
    assert gw.check_path(path) == path


@pytest.mark.parametrize("path", [
    "/sapi/v1/capital/deposit/address",
    "/sapi/v1/capital/withdraw/address/list",
    "/sapi/v1/account/apiRestrictions",
    "/sapi/v1/sub-account/subAccountApi/ipRestriction",
    "/api/v3/userDataStream",
    "/sapi/v1/broker/subAccount",
    "/sapi/v1/capital/config/getall",
    "/wapi/v3/depositAddress.html",
    "/api/v3/../sapi/x",
    "/sapi/v1/account?x=1",
    "sapi/v1/loan",
    "",
])
def test_sensitive_and_malformed_paths_are_refused(path):
    with pytest.raises(gw.Refused):
        gw.check_path(path)


def test_only_get_is_relayed(monkeypatch):
    monkeypatch.setattr(gw, "creds_for", lambda a: ("K", "S"))
    code, out = gw.run({"path": "/api/v3/order", "method": "POST"})
    assert code == 3 and out["code"] == "validation" and "GET only" in out["error"]
    code, out = gw.run({"path": "/api/v3/order", "method": "delete"})
    assert code == 3


def test_wallet_listings_may_use_post_but_nothing_else(monkeypatch):
    """Binance serves the funding-wallet listing over POST; it is a read."""
    seen = {}
    monkeypatch.setattr(gw.requests, "post",
                        lambda url, params=None, headers=None, timeout=None, stream=None:
                        seen.update(url=url) or _Resp(b'[{"asset":"CRCLB","free":"1.3"}]'))
    monkeypatch.setattr(gw.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("GET used")))
    monkeypatch.setattr(gw, "creds_for", lambda a: ("K", "S"))
    code, out = gw.run({"path": "/sapi/v1/asset/get-funding-asset", "method": "POST"})
    assert code == 0 and out["data"][0]["asset"] == "CRCLB"
    assert seen["url"].endswith("/sapi/v1/asset/get-funding-asset")
    # the same verb on any other path is still refused before anything is sent
    code, out = gw.run({"path": "/sapi/v1/asset/transfer", "method": "POST"})
    assert code == 3 and "GET only" in out["error"]


# ── params ──────────────────────────────────────────────────────────

def test_params_are_stringified_and_reserved_keys_dropped():
    out = gw.check_params({"loanCoin": "USDT", "limit": 5, "flag": True, "skip": None,
                           "signature": "spoof", "timestamp": 1})
    assert out == {"loanCoin": "USDT", "limit": "5", "flag": "true"}
    assert gw.check_params(None) == {} and gw.check_params("") == {}
    with pytest.raises(gw.Refused):
        gw.check_params(["not", "a", "dict"])


# ── credentials ─────────────────────────────────────────────────────

def test_creds_come_from_the_vault_map_by_account(monkeypatch, tmp_path):
    f = tmp_path / "gw_secret.json"
    f.write_text('{"135": {"ak": "K135", "sk": "S135"}, "118": {"ak": "K118", "sk": "S118"}}')
    monkeypatch.setattr(vip, "VAULT_SECRET_CANDIDATES", [f])
    monkeypatch.setattr(vip, "_from_env", lambda: ("ENVK", "ENVS"))
    monkeypatch.setattr(vip, "_from_dotenv", lambda: None)
    assert gw.creds_for("118") == ("K118", "S118")
    assert gw.creds_for("135") == ("K135", "S135")
    # an id the Vault file lacks must NOT fall back to the env credential
    assert gw.creds_for("999") is None
    assert gw.creds_for("") is None


def test_env_fallback_only_for_the_default_account(monkeypatch, tmp_path):
    monkeypatch.setattr(vip, "VAULT_SECRET_CANDIDATES", [tmp_path / "missing.json"])
    monkeypatch.setattr(vip, "VAULT_ACCOUNT_ID", "135")
    monkeypatch.setattr(vip, "_from_env", lambda: ("ENVK", "ENVS"))
    monkeypatch.setattr(vip, "_from_dotenv", lambda: None)
    assert gw.creds_for("135") == ("ENVK", "ENVS")
    assert gw.creds_for("118") is None


def test_unknown_account_is_not_found(monkeypatch):
    monkeypatch.setattr(gw, "creds_for", lambda a: None)
    code, out = gw.run({"account": "777", "path": "/api/v3/account"})
    assert code == 4 and out["code"] == "not_found" and "777" in out["error"]


# ── forwarding ──────────────────────────────────────────────────────

class _Resp:
    def __init__(self, body=b'{"ok":1}', status=200):
        self._body, self.status_code, self.text = body, status, body.decode()
        self.raw = self

    def read(self, n, decode_content=True):
        return self._body[:n]

    def raise_for_status(self):
        if self.status_code >= 400:
            err = requests.HTTPError("HTTP %d" % self.status_code)
            err.response = self
            raise err


def test_signed_get_carries_key_header_and_valid_signature(monkeypatch):
    seen = {}

    def fake_get(url, params=None, headers=None, timeout=None, stream=None):
        seen.update(url=url, params=params, headers=headers)
        return _Resp(b'{"annualInterestRate": "0.0400"}')

    monkeypatch.setattr(gw.requests, "get", fake_get)
    monkeypatch.setattr(gw, "creds_for", lambda a: ("KEY", "SECRET"))
    code, out = gw.run({"account": "135", "path": "/sapi/v1/loan/vip/request/interestRate",
                        "params": {"loanCoin": "USDT"}, "signed": True, "_acting_user": "danny"})
    assert code == 0 and out["ok"] and out["data"] == {"annualInterestRate": "0.0400"}
    assert seen["url"] == gw.BASE_URL + "/sapi/v1/loan/vip/request/interestRate"
    assert seen["headers"] == {"X-MBX-APIKEY": "KEY"}
    p = seen["params"]
    assert p["loanCoin"] == "USDT" and "timestamp" in p and "recvWindow" in p
    unsigned = {k: v for k, v in p.items() if k != "signature"}
    expect = hmac.new(b"SECRET", urlencode(unsigned).encode(), hashlib.sha256).hexdigest()
    assert p["signature"] == expect


def test_unsigned_get_adds_no_timestamp(monkeypatch):
    seen = {}
    monkeypatch.setattr(gw.requests, "get",
                        lambda url, params=None, headers=None, timeout=None, stream=None:
                        seen.update(params=params) or _Resp(b'[{"symbol":"BTCUSDT","price":"1"}]'))
    monkeypatch.setattr(gw, "creds_for", lambda a: ("KEY", "SECRET"))
    code, out = gw.run({"path": "/api/v3/ticker/price", "params": {"symbol": "BTCUSDT"},
                        "signed": False})
    assert code == 0 and out["data"][0]["symbol"] == "BTCUSDT"
    assert seen["params"] == {"symbol": "BTCUSDT"}


def test_binance_error_is_upstream_with_body_and_masked_key(monkeypatch):
    monkeypatch.setattr(gw.requests, "get",
                        lambda *a, **k: _Resp(b'{"code":-1121,"msg":"Invalid symbol."}', 400))
    monkeypatch.setattr(gw, "creds_for", lambda a: ("ABCDEFGHIJKL", "SECRET"))
    code, out = gw.run({"path": "/api/v3/ticker/price", "params": {"symbol": "NOPE"}})
    assert code == 5 and out["code"] == "upstream" and out["binance_status"] == 400
    assert "Invalid symbol" in out["error"] and "SECRET" not in str(out)
    assert out["api_key"] != "ABCDEFGHIJKL"


def test_network_failure_is_upstream(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("dns")
    monkeypatch.setattr(gw.requests, "get", boom)
    monkeypatch.setattr(gw, "creds_for", lambda a: ("K", "S"))
    code, out = gw.run({"path": "/api/v3/account"})
    assert code == 5 and out["code"] == "upstream" and "dns" in out["error"]


def test_oversized_reply_is_refused(monkeypatch):
    monkeypatch.setattr(gw, "MAX_BYTES", 10)
    monkeypatch.setattr(gw.requests, "get", lambda *a, **k: _Resp(b"x" * 11))
    monkeypatch.setattr(gw, "creds_for", lambda a: ("K", "S"))
    code, out = gw.run({"path": "/api/v3/account"})
    assert code == 3 and "narrow the query" in out["error"]


def test_query_parsing_helper_roundtrip():
    """Sanity for the server: query string -> params dict shape the script expects."""
    qs = urlencode({"account": "135", "path": "/api/v3/account", "signed": "1", "limit": "5"})
    parsed = {k: v[0] for k, v in parse_qs(qs).items()}
    assert parsed["path"] == "/api/v3/account" and parsed["limit"] == "5"
