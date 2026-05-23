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
import re
import sys


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
EXIT_MISCONFIG = 6    # → 500 (via fallback)
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
