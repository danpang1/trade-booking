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
