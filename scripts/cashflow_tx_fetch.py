"""Fetch a single on-chain transaction from Goldrush (Covalent) and parse
transfers + gas for autofilling the cashflow booking form.

stdin JSON:  {"tx_hash": "0x…", "network": "ETHEREUM"}
stdout JSON: {"ok": true, "transfers": [...], "gas_fee": "...", "gas_asset": "...",
              "timestamp": "...", "block_number": N, "tx_from": "0x…", "tx_to": "0x…"}
On failure:  {"ok": false, "error": "...", "detail?": "...", "code?": "..."}
             plus non-zero exit code (see EXIT_* constants below).

Manual smoke (requires GOLDRUSH_API_KEY in env):

    echo '{"tx_hash":"0x<real_tx>","network":"ETHEREUM"}' \
        | GOLDRUSH_API_KEY=$GOLDRUSH_API_KEY python3 scripts/cashflow_tx_fetch.py
"""
from __future__ import annotations
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path


# 25 EVM chains we support, mapped to Goldrush chain names + native asset.
# Source: docs/design/2026-05-23-cashflow-tx-hash-autofill-design.md §3.1.
# Verify Goldrush names against https://api.covalenthq.com/v1/chains/ before shipping.
CHAINS: dict[str, dict[str, str]] = {
    "ETHEREUM": {"chain_name": "eth-mainnet", "native_asset": "ETH"},
    "BINANCE SMART CHAIN": {"chain_name": "bsc-mainnet", "native_asset": "BNB"},
    "POLYGON": {"chain_name": "matic-mainnet", "native_asset": "MATIC"},
    "ARBITRUM": {"chain_name": "arbitrum-mainnet", "native_asset": "ETH"},
    "OPTIMISM": {"chain_name": "optimism-mainnet", "native_asset": "ETH"},
    "BASE": {"chain_name": "base-mainnet", "native_asset": "ETH"},
    "AVALANCHE": {"chain_name": "avalanche-mainnet", "native_asset": "AVAX"},
    "LINEA": {"chain_name": "linea-mainnet", "native_asset": "ETH"},
    "SCROLL": {"chain_name": "scroll-mainnet", "native_asset": "ETH"},
    "MANTLE": {"chain_name": "mantle-mainnet", "native_asset": "MNT"},
    "BLAST": {"chain_name": "blast-mainnet", "native_asset": "ETH"},
    "MODE": {"chain_name": "mode-mainnet", "native_asset": "ETH"},
    "CELO": {"chain_name": "celo-mainnet", "native_asset": "CELO"},
    "ZKSYNC": {"chain_name": "zksync-mainnet", "native_asset": "ETH"},
    "SONIC": {"chain_name": "sonic-mainnet", "native_asset": "S"},
    "GNOSIS": {"chain_name": "gnosis-mainnet", "native_asset": "xDAI"},
    "BERACHAIN": {"chain_name": "berachain-mainnet", "native_asset": "BERA"},
    "HYPEREVM": {"chain_name": "hyperevm-mainnet", "native_asset": "HYPE"},
    "UNICHAIN": {"chain_name": "unichain-mainnet", "native_asset": "ETH"},
    "SONEIUM": {"chain_name": "soneium-mainnet", "native_asset": "ETH"},
    "ZETA": {"chain_name": "zetachain-mainnet", "native_asset": "ZETA"},
    "PLASMA": {"chain_name": "plasma-mainnet", "native_asset": "XPL"},
    "TEMPO": {"chain_name": "tempo-mainnet", "native_asset": "TEMPO"},
    "SAGAEVM": {"chain_name": "sagaevm-mainnet", "native_asset": "SAGA"},
    "XRPLEVM": {"chain_name": "xrplevm-mainnet", "native_asset": "XRP"},
}

# Exit codes — map to HTTP via server.js:httpStatusFor.
EXIT_OK = 0
EXIT_VALIDATION = 3   # → 400
EXIT_NOT_FOUND = 4    # → 404
EXIT_UPSTREAM = 5     # → 502 (via json.code="upstream")
EXIT_MISCONFIG = 8    # → 500 (no mapping in server.js:httpStatusFor → default 500)
EXIT_NO_XFERS = 7     # → 422 (via json.code="no_transfers")


_HASH_RE = re.compile(r"^0x[0-9a-f]{64}$")


class ValidationError(ValueError):
    """Raised for malformed inputs. Maps to EXIT_VALIDATION (HTTP 400)."""


def validate_input(payload: dict) -> dict:
    """Validate and normalize stdin payload. Returns a new dict with lower-case hash."""
    if not isinstance(payload, dict):
        raise ValidationError("payload must be a JSON object")
    tx_hash = payload.get("tx_hash")
    network = payload.get("network")
    if not isinstance(tx_hash, str):
        raise ValidationError("tx_hash is required")
    tx_hash = tx_hash.lower()
    if not _HASH_RE.match(tx_hash):
        raise ValidationError("tx_hash must be 0x + 64 hex chars")
    if not isinstance(network, str) or network not in CHAINS:
        raise ValidationError(
            f"network must be one of: {', '.join(sorted(CHAINS))}"
        )
    return {"tx_hash": tx_hash, "network": network}


_ERC20_TRANSFER_SIG = (
    "Transfer(indexed address from, indexed address to, uint256 value)"
)


def _minor_to_decimal(raw: int | str, decimals: int, *, strip_zeros: bool = False) -> str:
    """Convert integer minor units (wei, satoshi, USDT-base-units, etc.) to a decimal string.

    No scientific notation. `decimals=0` returns the int verbatim. With strip_zeros=True,
    trailing zeros past the radix point are removed (and a bare "0" is returned for 0);
    without it, the full declared precision is preserved (so 100 USDT → "100.000000").
    """
    raw_int = int(raw)
    if decimals == 0:
        return str(raw_int)
    whole, frac = divmod(raw_int, 10 ** decimals)
    out = f"{whole}.{str(frac).zfill(decimals)}"
    if strip_zeros:
        out = out.rstrip("0").rstrip(".")
        if out == "":
            out = "0"
    return out


def parse_goldrush(resp: dict, network: str) -> dict:
    """Parse Covalent /transaction_v2 response into our normalized shape.

    Caller is responsible for checking that `resp` is the success-shape (data.items
    non-empty) before calling — see fetch_tx() for the error-mapping layer.
    """
    item = resp["data"]["items"][0]
    gas_spent = int(item["gas_spent"])
    gas_price = int(item["gas_price"])
    gas_fee_wei = gas_spent * gas_price
    gas_fee = _minor_to_decimal(gas_fee_wei, 18, strip_zeros=True)

    transfers: list[dict] = []
    for log in item.get("log_events") or []:
        decoded = log.get("decoded") or {}
        if decoded.get("signature") != _ERC20_TRANSFER_SIG:
            continue
        params = {p["name"]: p["value"] for p in decoded.get("params", [])}
        if not all(k in params for k in ("from", "to", "value")):
            continue
        decimals = log.get("sender_contract_decimals")
        ticker = log.get("sender_contract_ticker_symbol")
        contract = log.get("sender_address")
        if decimals is None or ticker is None or contract is None:
            print(
                f"[cashflow_tx_fetch] skipping non-standard token log "
                f"(decimals={decimals!r}, ticker={ticker!r}, contract={contract!r})",
                file=sys.stderr,
            )
            continue
        transfers.append({
            "asset": ticker,
            "amount": _minor_to_decimal(params["value"], int(decimals)),
            "from": params["from"],
            "to": params["to"],
            "decimals": int(decimals),
            "contract_address": contract,
        })

    if not transfers and int(item.get("value", "0")) > 0:
        native_value = int(item["value"])
        transfers.append({
            "asset": CHAINS[network]["native_asset"],
            "amount": _minor_to_decimal(native_value, 18),
            "from": item["from_address"],
            "to": item["to_address"],
            "decimals": 18,
            "contract_address": None,
        })

    return {
        "transfers": transfers,
        "gas_fee": gas_fee,
        "gas_asset": CHAINS[network]["native_asset"],
        "timestamp": item["block_signed_at"],
        "block_number": int(item["block_height"]),
        "tx_from": item["from_address"],
        "tx_to": item["to_address"],
    }


GOLDRUSH_BASE = "https://api.covalenthq.com/v1"
GOLDRUSH_TIMEOUT_SEC = 15
# Goldrush sits behind a WAF that 403s requests with the default
# `Python-urllib/X.Y` User-Agent. Any explicit UA works.
GOLDRUSH_USER_AGENT = "middle-office-tools/cashflow-tx-fetch"

_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def _read_api_key() -> str | None:
    """Process env wins; fall back to a simple KEY=VALUE lookup in repo .env.

    Matches the env-precedence convention used by cashflow_db.load_creds.
    Single-key lookup (we only need GOLDRUSH_API_KEY) so no block parsing
    needed — just scan for the first matching uncommented line.
    """
    val = os.environ.get("GOLDRUSH_API_KEY")
    if val:
        return val
    if not _ENV_FILE.exists():
        return None
    for line in _ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key.strip() == "GOLDRUSH_API_KEY":
            return value.strip() or None
    return None


def call_goldrush(tx_hash: str, network: str, api_key: str) -> dict:
    """Single HTTP GET to Goldrush. Returns decoded JSON. Raises HTTPError/URLError."""
    chain = CHAINS[network]["chain_name"]
    url = f"{GOLDRUSH_BASE}/{chain}/transaction_v2/{tx_hash}/"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {api_key}",
        "User-Agent": GOLDRUSH_USER_AGENT,
    })
    with urllib.request.urlopen(req, timeout=GOLDRUSH_TIMEOUT_SEC) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ── Address resolution against reference_data MySQL ────────────────

# Tables we resolve against, in priority order. Each must expose
# (address, blockchain, ownerName, name, status, deletedAt).
_RESOLVE_TABLES: tuple[tuple[str, str], ...] = (
    ("counterparty_settlement_crypto", "counterparty"),
    ("account_wallet_deposit", "our_wallet"),
    ("account_exchange_deposit", "our_exchange_deposit"),
)


def _load_refdata_creds() -> dict[str, str] | None:
    """Read t2x-ro-mysql creds. Env vars (T2X_RO_MYSQL_*) take precedence;
    .env file parsed as fallback for local dev. Returns None if neither source
    supplies a complete set — callers should skip resolution silently rather
    than fail the whole fetch.

    Anchors on the host name (`sg-ro-mysql`) rather than the comment text so
    it works for both `# t2x-ro-mysql` and `#MYSQL RO` block conventions.
    """
    env_creds = {
        k: os.environ[f"T2X_RO_MYSQL_{k.upper()}"]
        for k in ("host", "username", "password")
        if f"T2X_RO_MYSQL_{k.upper()}" in os.environ
    }
    if all(k in env_creds for k in ("host", "username", "password")):
        return env_creds

    if not _ENV_FILE.exists():
        return None
    lines = _ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    anchor = None
    for i, ln in enumerate(lines):
        if "sg-ro-mysql" in ln.lower():
            anchor = i
            break
    if anchor is None:
        return None
    creds: dict[str, str] = {}
    for j in range(max(0, anchor - 5), min(len(lines), anchor + 5)):
        s = lines[j].strip()
        if not s or s.startswith("#") or ":" not in s or "=" in s:
            continue
        k, _, v = s.partition(":")
        key = k.strip().lower()
        if key in ("host", "username", "password"):
            creds[key] = v.strip()
    return creds if all(k in creds for k in ("host", "username", "password")) else None


def resolve_addresses(addresses: list[str], network: str) -> dict[str, dict]:
    """Look each address up in reference_data, scoped to the given network.

    Returns a dict keyed by LOWER-case address. Missing addresses are absent
    from the dict (callers should treat absence as "no match"). On any DB
    error or missing creds, returns an empty dict — resolution is a best-effort
    enrichment that must never block the tx fetch itself.

    Each value: {"kind": "<table-kind>", "owner": ownerName, "label": name}
    First-match wins across the table priority order.
    """
    if not addresses:
        return {}
    creds = _load_refdata_creds()
    if not creds:
        print("[cashflow_tx_fetch] skipping address resolution: refdata creds unavailable",
              file=sys.stderr)
        return {}

    lower = sorted({a.lower() for a in addresses if a})
    if not lower:
        return {}

    try:
        import pymysql  # imported lazily so the script still runs without pymysql installed
    except ImportError:
        print("[cashflow_tx_fetch] skipping address resolution: pymysql not installed",
              file=sys.stderr)
        return {}

    out: dict[str, dict] = {}
    try:
        conn = pymysql.connect(
            host=creds["host"], user=creds["username"], password=creds["password"],
            database="reference_data", connect_timeout=10,
        )
        try:
            cur = conn.cursor()
            placeholders = ", ".join(["%s"] * len(lower))
            for table, kind in _RESOLVE_TABLES:
                cur.execute(
                    f"SELECT LOWER(address), ownerName, name FROM {table} "
                    f"WHERE LOWER(address) IN ({placeholders}) "
                    f"AND blockchain = %s AND deletedAt IS NULL "
                    f"AND (status IS NULL OR status='ACTIVE')",
                    (*lower, network),
                )
                for addr, owner, label in cur.fetchall():
                    if addr not in out:
                        out[addr] = {"kind": kind, "owner": owner, "label": label}
        finally:
            conn.close()
    except Exception as e:
        print(f"[cashflow_tx_fetch] address resolution failed: {e}", file=sys.stderr)
        return {}
    return out


def fetch_tx(payload: dict) -> tuple[int, dict]:
    """Top-level: validate → call → parse → map errors. Returns (exit_code, json_body)."""
    api_key = _read_api_key()
    if not api_key:
        return EXIT_MISCONFIG, {"ok": False, "error": "server misconfigured",
                                "detail": "GOLDRUSH_API_KEY not set"}
    try:
        normalized = validate_input(payload)
    except ValidationError as e:
        return EXIT_VALIDATION, {"ok": False, "error": str(e)}

    try:
        resp = call_goldrush(normalized["tx_hash"], normalized["network"], api_key)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return EXIT_NOT_FOUND, {"ok": False, "error": "tx not found", "code": "not_found"}
        return EXIT_UPSTREAM, {"ok": False, "error": "upstream unavailable",
                               "code": "upstream", "detail": f"http {e.code}"}
    except urllib.error.URLError as e:
        return EXIT_UPSTREAM, {"ok": False, "error": "upstream unavailable",
                               "code": "upstream", "detail": str(e.reason)}

    # Covalent returns 200 + data.items=[] for unknown tx on some chains.
    items = (resp.get("data") or {}).get("items") or []
    if not items:
        return EXIT_NOT_FOUND, {"ok": False, "error": "tx not found", "code": "not_found"}

    parsed = parse_goldrush(resp, normalized["network"])
    if not parsed["transfers"]:
        return EXIT_NO_XFERS, {"ok": False, "error": "no transfers", "code": "no_transfers"}

    # Best-effort enrichment: resolve every address touched by the tx against
    # reference_data. Failures here MUST NOT fail the fetch — handled inside.
    unique_addrs: list[str] = []
    seen: set[str] = set()
    for a in [parsed["tx_from"], parsed["tx_to"]] + [t["from"] for t in parsed["transfers"]] + [t["to"] for t in parsed["transfers"]]:
        if a and a.lower() not in seen:
            seen.add(a.lower())
            unique_addrs.append(a)
    resolutions = resolve_addresses(unique_addrs, normalized["network"])

    return EXIT_OK, {"ok": True, **parsed, "resolutions": resolutions}


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError as e:
        sys.stdout.write(json.dumps({"ok": False, "error": "invalid JSON on stdin",
                                     "detail": str(e)}))
        sys.exit(EXIT_VALIDATION)
    code, body = fetch_tx(payload)
    sys.stdout.write(json.dumps(body))
    sys.exit(code)


if __name__ == "__main__":
    main()
