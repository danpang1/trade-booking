"""Read-only Binance gateway for the middle-office tools.

The Colossus Slack bot (and any other authenticated caller) asks this route
for a Binance READ on its behalf. Every request is forwarded as a GET to
api.binance.com, signed for the requested account when `signed` is true, and
the JSON comes back verbatim under "data". Credential selection is the VIP
loan script's job (binance_vip_loan_ltv.creds_for_account); nothing here
reads a secret file.

Stdin (server mode):
  {"account": "135",                  internal id of the CEX account
   "path": "/sapi/v1/loan/vip/request/interestRate",
   "params": {"loanCoin": "USDT"},    query parameters, all strings
   "signed": true,                    add timestamp + HMAC signature
   "_acting_user": "danny.pang"}      for the audit line only

Stdout: {"ok": true, "account": ..., "path": ..., "data": ...}
        {"ok": false, "code": "validation"|"not_found"|"upstream", "error": ...}
Exit:   0 ok, 3 validation (bad path / method), 4 no credential for that
        account, 5 Binance refused or did not answer.

Policy, in this order:
  1. GET only. Binance performs every write (orders, withdrawals, transfers,
     borrows) with POST/DELETE, so a GET-only gateway cannot move anything
     whatever the key permits.
  2. The path must start with one of ALLOWED_PREFIXES and must not match
     DENY: reads that expose material we do not want relayed into a chat
     (deposit/withdrawal addresses, API-key details, sub-account keys,
     listen keys, broker admin).
  3. An account the deployment holds no credential for fails closed.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sys
import time
from urllib.parse import urlencode

import requests

import binance_vip_loan_ltv as vip

BASE_URL = vip.BASE_URL
# Binance splits its read API over several hosts; the path prefix says which.
# Portfolio Margin lives on papi.binance.com, USD-M futures on fapi, COIN-M on
# dapi. The same key signs all of them.
HOSTS = {
    "/api/": BASE_URL,
    "/sapi/": BASE_URL,
    "/papi/": "https://papi.binance.com",
    "/fapi/": "https://fapi.binance.com",
    "/dapi/": "https://dapi.binance.com",
}
ALLOWED_PREFIXES = ("/api/v3/", "/sapi/v1/", "/sapi/v2/", "/sapi/v3/", "/sapi/v4/",
                    "/papi/v1/", "/fapi/v1/", "/fapi/v2/", "/fapi/v3/", "/dapi/v1/")


def host_for(path: str) -> str:
    for prefix, host in HOSTS.items():
        if path.startswith(prefix):
            return host
    return BASE_URL


DENY = re.compile(
    r"(/address\b|/deposit/address|/withdraw/address|apiRestrictions|/apiKey\b|"
    r"api-key|/subAccountApi|/managed-subaccount/(deposit|withdraw)|"
    r"/userDataStream|/listenKey|/broker/|/apiReferral|/rebate/|"
    r"/account/info\b|/capital/config/getall)", re.I)
# Binance serves a handful of pure READS over POST (the wallet listings).
# These, and only these, may be sent with POST; each carries no side effect.
READ_POST = frozenset({
    "/sapi/v1/asset/get-funding-asset",
    "/sapi/v3/asset/getUserAsset",
})
RECV_WINDOW = int(os.environ.get("BINANCE_PROXY_RECV_WINDOW", "10000"))
TIMEOUT = float(os.environ.get("BINANCE_PROXY_TIMEOUT", "15"))
MAX_BYTES = 2_000_000

# One loader for the whole app: which key answers for which account is the
# VIP loan script's rule, reused here so the two can never disagree.
creds_for = vip.creds_for_account


class Refused(ValueError):
    """The request violates the gateway policy; nothing was sent."""


def check_path(path: str) -> str:
    """The validated path, or Refused."""
    p = str(path or "").strip()
    if not p.startswith("/") or ".." in p or "?" in p or "#" in p:
        raise Refused("path must be an absolute Binance API path without a query")
    if not p.startswith(ALLOWED_PREFIXES):
        raise Refused("path must start with one of %s" % ", ".join(ALLOWED_PREFIXES))
    if DENY.search(p):
        raise Refused("that endpoint is not relayed through the gateway")
    return p


def check_params(params) -> dict:
    if params in (None, ""):
        return {}
    if not isinstance(params, dict):
        raise Refused("params must be an object")
    out = {}
    for k, v in params.items():
        k = str(k)
        if k.lower() in ("signature", "timestamp"):
            continue          # the gateway owns these
        if isinstance(v, bool):
            v = "true" if v else "false"
        if v is None:
            continue
        if isinstance(v, (list, dict)):
            v = json.dumps(v, separators=(",", ":"))
        out[k] = str(v)
    return out


def forward(path: str, params: dict, key: str, secret: str, signed: bool,
            method: str = "GET") -> object:
    """One request to Binance. Raises requests.RequestException on failure.
    `method` is GET, or POST for the READ_POST wallet listings; the
    parameters travel in the query string either way, as Binance expects."""
    headers = {"X-MBX-APIKEY": key}
    q = dict(params)
    if signed:
        q["timestamp"] = int(time.time() * 1000)
        q["recvWindow"] = RECV_WINDOW
        q["signature"] = hmac.new(secret.encode("utf-8"), urlencode(q).encode("utf-8"),
                                  hashlib.sha256).hexdigest()
    call = requests.post if method == "POST" else requests.get
    resp = call(host_for(path) + path, params=q, headers=headers, timeout=TIMEOUT,
                stream=True)
    body = resp.raw.read(MAX_BYTES + 1, decode_content=True)
    if len(body) > MAX_BYTES:
        raise Refused("Binance answered with more than %d bytes; narrow the query" % MAX_BYTES)
    # The stream is consumed; hand the bytes back to the Response so a
    # raise_for_status() error still carries Binance's reason in .text.
    resp._content = body
    resp._content_consumed = True
    resp.raise_for_status()
    try:
        return json.loads(body.decode("utf-8"))
    except ValueError:
        return body.decode("utf-8", "replace")


def run(body: dict) -> tuple[int, dict]:
    account = str(body.get("account") or vip.VAULT_ACCOUNT_ID)
    method = str(body.get("method") or "GET").upper()
    try:
        path = check_path(body.get("path"))
        params = check_params(body.get("params"))
    except Refused as e:
        return 3, {"ok": False, "code": "validation", "error": str(e)}
    if method == "POST" and path in READ_POST:
        pass                       # a read that Binance happens to serve over POST
    elif method != "GET":
        return 3, {"ok": False, "code": "validation", "error": "the gateway relays GET only"}
    signed = body.get("signed", True)
    signed = signed if isinstance(signed, bool) else str(signed).lower() not in ("0", "false", "no")
    creds = creds_for(account)
    if not creds:
        return 4, {"ok": False, "code": "not_found",
                   "error": "no Binance credential for account %s on this deployment" % account}
    key, secret = creds
    try:
        data = forward(path, params, key, secret, signed, method)
    except Refused as e:
        return 3, {"ok": False, "code": "validation", "error": str(e)}
    except requests.RequestException as e:
        resp = getattr(e, "response", None)
        err = {"ok": False, "code": "upstream", "account": account, "path": path,
               "api_key": vip._mask_key(key)}
        if resp is not None:
            err["binance_status"] = resp.status_code
            err["binance_body"] = (resp.text or "")[:300]
            err["error"] = "Binance HTTP %s: %s" % (resp.status_code, (resp.text or "")[:300])
        else:
            err["error"] = "Binance request failed: %s" % str(e)[:200]
        return 5, err
    print("binance_proxy: user=%s account=%s path=%s params=%s signed=%s" % (
        body.get("_acting_user"), account, path, json.dumps(params, sort_keys=True), signed),
        file=sys.stderr)
    return 0, {"ok": True, "account": account, "path": path, "params": params, "data": data}


def main() -> int:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig").strip() or "{}"
        body = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "code": "validation", "error": "invalid JSON on stdin",
                          "detail": str(e)}))
        return 2
    code, out = run(body if isinstance(body, dict) else {})
    print(json.dumps(out, default=str))
    return code


if __name__ == "__main__":
    sys.exit(main())
