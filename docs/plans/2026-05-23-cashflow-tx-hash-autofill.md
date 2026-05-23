# Cashflow Form — Autofill from On-Chain TX Hash — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Fetch button next to the `tx_hash` field on the cashflow booking form. When the user picks an EVM network, pastes a tx hash, and clicks Fetch, the backend calls Goldrush (Covalent), parses the transaction, and auto-fills the empty cashflow fields (asset, amount, gas fee, gas asset, dates). Single-transfer txs auto-apply; multi-transfer txs surface an inline picker.

**Architecture:** One new Python script (`cashflow_tx_fetch.py`) follows the established stdin-JSON → stdout-JSON pattern and calls Goldrush via stdlib `urllib.request` (no new Python deps). One new Node route (`POST /api/cashflow/fetch-tx`) spawns the script via the existing `spawnPython` helper. Two new `code` strings (`upstream`, `no_transfers`) are added to `httpStatusFor` to map to 502 / 422. The React `TradeBookingForm.jsx` cashflow section gains a Fetch button, a loading/error state under the `tx_hash` input, a multi-transfer picker that appears when needed, and an `applyAutofill` helper that fills empty fields only.

**Tech Stack:** Python 3.11 (stdlib `urllib.request`, no `requests` dep), Node 22 (no new deps), React 19 (no new deps, `lucide-react` already in use), Goldrush (Covalent) `transaction_v2` HTTP API.

**Spec:** `docs/design/2026-05-23-cashflow-tx-hash-autofill-design.md` — read it first.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `scripts/cashflow_tx_fetch.py` | Create | stdin `{tx_hash,network}` → calls Goldrush, parses transfers/gas/timestamp → stdout JSON |
| `tests/test_cashflow_tx_fetch.py` | Create | Pure-logic unit tests with `pytest-mock` patching `urllib.request.urlopen` |
| `server.js` | Modify | Extend `httpStatusFor` with new code mappings; add `POST /api/cashflow/fetch-tx` route |
| `src/TradeBookingForm.jsx` | Modify | Cashflow section: Fetch button, loading/error state, multi-transfer picker, `applyAutofill` helper |
| `.env.example` | Modify | Add `GOLDRUSH_API_KEY=` placeholder |
| `README.md` | Modify | One-paragraph note on the new fetch feature + GOLDRUSH_API_KEY env var |
| `helm/Chart.yaml`, `version.yml` | Modify | Patch bump via `scripts/update_version.py` |

---

## Conventions inherited from this codebase

- **Script header:** docstring with manual smoke command, e.g. `echo '{…}' | python3 scripts/<name>.py`.
- **stdin/stdout contract:** scripts read JSON from stdin, write JSON to stdout. Exit code → HTTP via `server.js:httpStatusFor` (`0→200`, `3→400`, `4→404`, `6→401`; `json.code:"conflict"`→409, `json.code:"not_found"`→404; anything else→500).
- **Tests are pure-logic.** No real HTTP / DB in pytest. Use `pytest-mock` (already in `requirements-dev.txt`) to patch `urllib.request.urlopen`.
- **Commit style:** `type(scope): subject` lower-case (`feat(cashflow): …`, `fix(deps): …`, `docs(design): …`).
- **One bump per push to main.** Run `python scripts/update_version.py` and commit `chore: bump version X.Y.Z -> X.Y.(Z+1)` before `git push origin main`; ECR tag immutability gates the build.
- **Auth:** all `/api/cashflow/*` routes are session-gated by the existing middleware in `server.js`; the new fetch route inherits this for free (verify in Task 6).

---

## Task 1: Chain mapping module — pure data + tests

**Goal:** Define the 25 EVM `network → {chain_name, native_asset}` lookup as a constant inside `cashflow_tx_fetch.py`, and write tests that lock the mapping down before any HTTP code exists.

**Files:**
- Create: `scripts/cashflow_tx_fetch.py` (stub with `CHAINS` constant only)
- Create: `tests/test_cashflow_tx_fetch.py` (mapping-only tests)

**Acceptance Criteria:**
- [ ] `CHAINS` dict in `cashflow_tx_fetch.py` has exactly 25 entries.
- [ ] Each entry has keys `chain_name` (string) and `native_asset` (string).
- [ ] All 25 keys are uppercase strings matching the entries from §3.1 of the spec.
- [ ] `pytest tests/test_cashflow_tx_fetch.py -v` passes.

**Verify:**
```bash
cd ~/Projects/middle-office-tools
pytest tests/test_cashflow_tx_fetch.py -v
```
Expected: 3 tests pass.

**Steps:**

- [ ] **Step 1: Write failing tests**

Create `tests/test_cashflow_tx_fetch.py`:

```python
"""Unit tests for cashflow_tx_fetch — pure logic, urllib.request.urlopen patched.

Manual smoke / integration test lives in the script's docstring (real Goldrush call).
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import cashflow_tx_fetch  # noqa: E402


# ── §1: Chain mapping ────────────────────────────────────────────

def test_chains_has_25_entries():
    assert len(cashflow_tx_fetch.CHAINS) == 25


def test_chains_each_entry_has_chain_name_and_native_asset():
    for name, info in cashflow_tx_fetch.CHAINS.items():
        assert isinstance(name, str) and name == name.upper(), name
        assert "chain_name" in info and isinstance(info["chain_name"], str)
        assert "native_asset" in info and isinstance(info["native_asset"], str)


def test_chains_known_entries():
    assert cashflow_tx_fetch.CHAINS["ETHEREUM"] == {
        "chain_name": "eth-mainnet",
        "native_asset": "ETH",
    }
    assert cashflow_tx_fetch.CHAINS["BINANCE SMART CHAIN"] == {
        "chain_name": "bsc-mainnet",
        "native_asset": "BNB",
    }
    assert cashflow_tx_fetch.CHAINS["ARBITRUM"] == {
        "chain_name": "arbitrum-mainnet",
        "native_asset": "ETH",
    }
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_cashflow_tx_fetch.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'cashflow_tx_fetch'`.

- [ ] **Step 3: Write the stub script with CHAINS**

Create `scripts/cashflow_tx_fetch.py`:

```python
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
    "ETHEREUM":            {"chain_name": "eth-mainnet",        "native_asset": "ETH"},
    "BINANCE SMART CHAIN": {"chain_name": "bsc-mainnet",        "native_asset": "BNB"},
    "POLYGON":             {"chain_name": "matic-mainnet",      "native_asset": "MATIC"},
    "ARBITRUM":            {"chain_name": "arbitrum-mainnet",   "native_asset": "ETH"},
    "OPTIMISM":            {"chain_name": "optimism-mainnet",   "native_asset": "ETH"},
    "BASE":                {"chain_name": "base-mainnet",       "native_asset": "ETH"},
    "AVALANCHE":           {"chain_name": "avalanche-mainnet",  "native_asset": "AVAX"},
    "LINEA":               {"chain_name": "linea-mainnet",      "native_asset": "ETH"},
    "SCROLL":              {"chain_name": "scroll-mainnet",     "native_asset": "ETH"},
    "MANTLE":              {"chain_name": "mantle-mainnet",     "native_asset": "MNT"},
    "BLAST":               {"chain_name": "blast-mainnet",      "native_asset": "ETH"},
    "MODE":                {"chain_name": "mode-mainnet",       "native_asset": "ETH"},
    "CELO":                {"chain_name": "celo-mainnet",       "native_asset": "CELO"},
    "ZKSYNC":              {"chain_name": "zksync-mainnet",     "native_asset": "ETH"},
    "SONIC":               {"chain_name": "sonic-mainnet",      "native_asset": "S"},
    "GNOSIS":              {"chain_name": "gnosis-mainnet",     "native_asset": "xDAI"},
    "BERACHAIN":           {"chain_name": "berachain-mainnet",  "native_asset": "BERA"},
    "HYPEREVM":            {"chain_name": "hyperevm-mainnet",   "native_asset": "HYPE"},
    "UNICHAIN":            {"chain_name": "unichain-mainnet",   "native_asset": "ETH"},
    "SONEIUM":             {"chain_name": "soneium-mainnet",    "native_asset": "ETH"},
    "ZETA":                {"chain_name": "zetachain-mainnet",  "native_asset": "ZETA"},
    "PLASMA":              {"chain_name": "plasma-mainnet",     "native_asset": "XPL"},
    "TEMPO":               {"chain_name": "tempo-mainnet",      "native_asset": "TEMPO"},
    "SAGAEVM":             {"chain_name": "sagaevm-mainnet",    "native_asset": "SAGA"},
    "XRPLEVM":             {"chain_name": "xrplevm-mainnet",    "native_asset": "XRP"},
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_cashflow_tx_fetch.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/cashflow_tx_fetch.py tests/test_cashflow_tx_fetch.py
git commit -m "feat(cashflow): add tx_fetch chain mapping stub"
```

---

## Task 2: Input validation (hash format + network allowlist)

**Goal:** Add `validate_input(payload)` that rejects malformed hashes or non-EVM networks. Pure-function, no HTTP yet.

**Files:**
- Modify: `scripts/cashflow_tx_fetch.py` (add `validate_input` + exit constants)
- Modify: `tests/test_cashflow_tx_fetch.py` (add validation tests)

**Acceptance Criteria:**
- [ ] `validate_input({"tx_hash": "0x" + "a"*64, "network": "ETHEREUM"})` returns the normalized payload.
- [ ] Anything else raises `ValidationError` (a new class in the script).
- [ ] All new tests pass; existing 3 still pass.

**Verify:**
```bash
pytest tests/test_cashflow_tx_fetch.py -v
```
Expected: 9 tests pass (3 existing + 6 new).

**Steps:**

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cashflow_tx_fetch.py`:

```python
import pytest  # noqa: E402


# ── §2: Input validation ─────────────────────────────────────────

VALID_HASH = "0x" + "a" * 64


def test_validate_input_accepts_valid_hash_and_network():
    out = cashflow_tx_fetch.validate_input(
        {"tx_hash": VALID_HASH, "network": "ETHEREUM"}
    )
    assert out["tx_hash"] == VALID_HASH.lower()
    assert out["network"] == "ETHEREUM"


def test_validate_input_lowercases_hex():
    out = cashflow_tx_fetch.validate_input(
        {"tx_hash": "0x" + "A" * 64, "network": "BASE"}
    )
    assert out["tx_hash"] == "0x" + "a" * 64


@pytest.mark.parametrize("bad_hash", [
    "",
    "0x123",                  # too short
    "0x" + "z" * 64,          # non-hex
    "abc" + "a" * 61,         # missing 0x prefix
    "0x" + "a" * 65,          # too long
    None,
])
def test_validate_input_rejects_bad_hash(bad_hash):
    with pytest.raises(cashflow_tx_fetch.ValidationError):
        cashflow_tx_fetch.validate_input({"tx_hash": bad_hash, "network": "ETHEREUM"})


@pytest.mark.parametrize("bad_network", [
    "",
    None,
    "SOLANA",         # non-EVM, not in CHAINS
    "BITCOIN",        # non-EVM
    "ethereum",       # case matters — we standardised on uppercase keys
    "MADE_UP_CHAIN",
])
def test_validate_input_rejects_bad_network(bad_network):
    with pytest.raises(cashflow_tx_fetch.ValidationError):
        cashflow_tx_fetch.validate_input({"tx_hash": VALID_HASH, "network": bad_network})


def test_validate_input_rejects_missing_keys():
    with pytest.raises(cashflow_tx_fetch.ValidationError):
        cashflow_tx_fetch.validate_input({"tx_hash": VALID_HASH})  # no network
    with pytest.raises(cashflow_tx_fetch.ValidationError):
        cashflow_tx_fetch.validate_input({"network": "ETHEREUM"})  # no hash


def test_validation_error_carries_message():
    try:
        cashflow_tx_fetch.validate_input({"tx_hash": "nope", "network": "ETHEREUM"})
    except cashflow_tx_fetch.ValidationError as e:
        assert "hash" in str(e).lower()
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_cashflow_tx_fetch.py -v
```
Expected: 6 new tests FAIL with `AttributeError: module 'cashflow_tx_fetch' has no attribute 'ValidationError'`.

- [ ] **Step 3: Add validation + exit constants to the script**

Append to `scripts/cashflow_tx_fetch.py` (after the `CHAINS` constant):

```python
import re


# Exit codes — map to HTTP via server.js:httpStatusFor.
EXIT_OK         = 0
EXIT_VALIDATION = 3   # → 400
EXIT_NOT_FOUND  = 4   # → 404
EXIT_UPSTREAM   = 5   # → 502 (via json.code="upstream")
EXIT_MISCONFIG  = 6   # → 500 (via fallback)
EXIT_NO_XFERS   = 7   # → 422 (via json.code="no_transfers")


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
```

- [ ] **Step 4: Run to verify all pass**

```bash
pytest tests/test_cashflow_tx_fetch.py -v
```
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/cashflow_tx_fetch.py tests/test_cashflow_tx_fetch.py
git commit -m "feat(cashflow): validate tx_fetch input shape"
```

---

## Task 3: Parse Goldrush response — single ERC-20 transfer

**Goal:** Add a pure `parse_goldrush(response_json, network)` function that takes the Covalent transaction_v2 response shape and returns the normalized `{transfers, gas_fee, gas_asset, timestamp, block_number, tx_from, tx_to}`. Cover the most common case first: one ERC-20 Transfer log event.

**Files:**
- Modify: `scripts/cashflow_tx_fetch.py` (add `parse_goldrush`)
- Modify: `tests/test_cashflow_tx_fetch.py` (add parse tests with fixture)

**Acceptance Criteria:**
- [ ] `parse_goldrush(USDT_ON_ETH_FIXTURE, "ETHEREUM")` returns a single transfer with `asset="USDT"`, `amount="100.000000"`, `decimals=6`, the correct from/to addresses, and `gas_asset="ETH"`.
- [ ] `gas_fee` is computed as `(gas_spent * gas_price) / 10**18`, returned as a decimal string (no scientific notation, trims trailing zeros only past the radix point).

**Verify:**
```bash
pytest tests/test_cashflow_tx_fetch.py -v
```
Expected: 11 tests pass (9 existing + 2 new).

**Steps:**

- [ ] **Step 1: Add fixture + failing test**

Append to `tests/test_cashflow_tx_fetch.py`:

```python
# ── §3: Goldrush response parsing — single ERC-20 transfer ────────

# Trimmed shape of the Goldrush /v1/{chain}/transaction_v2/{hash}/ response
# for a 100 USDT transfer on Ethereum mainnet. Field names match Covalent docs.
USDT_TRANSFER_FIXTURE = {
    "data": {
        "items": [{
            "block_signed_at": "2026-05-22T14:23:11Z",
            "block_height": 19234567,
            "tx_hash": "0x" + "a" * 64,
            "from_address": "0x1111111111111111111111111111111111111111",
            "to_address":   "0xdac17f958d2ee523a2206206994597c13d831ec7",  # USDT contract
            "value": "0",
            "gas_spent": 65000,
            "gas_price": 20_000_000_000,  # 20 gwei
            "log_events": [{
                "sender_contract_decimals": 6,
                "sender_contract_ticker_symbol": "USDT",
                "sender_address": "0xdac17f958d2ee523a2206206994597c13d831ec7",
                "decoded": {
                    "name": "Transfer",
                    "signature": "Transfer(indexed address from, indexed address to, uint256 value)",
                    "params": [
                        {"name": "from",  "type": "address", "value": "0x1111111111111111111111111111111111111111"},
                        {"name": "to",    "type": "address", "value": "0x2222222222222222222222222222222222222222"},
                        {"name": "value", "type": "uint256", "value": "100000000"},  # 100 * 10^6
                    ],
                },
            }],
        }],
    },
}


def test_parse_single_erc20_transfer():
    out = cashflow_tx_fetch.parse_goldrush(USDT_TRANSFER_FIXTURE, "ETHEREUM")
    assert out["transfers"] == [{
        "asset": "USDT",
        "amount": "100.000000",
        "from": "0x1111111111111111111111111111111111111111",
        "to":   "0x2222222222222222222222222222222222222222",
        "decimals": 6,
        "contract_address": "0xdac17f958d2ee523a2206206994597c13d831ec7",
    }]
    assert out["gas_asset"] == "ETH"
    assert out["timestamp"] == "2026-05-22T14:23:11Z"
    assert out["block_number"] == 19234567
    assert out["tx_from"] == "0x1111111111111111111111111111111111111111"
    assert out["tx_to"]   == "0xdac17f958d2ee523a2206206994597c13d831ec7"


def test_parse_gas_fee_arithmetic():
    out = cashflow_tx_fetch.parse_goldrush(USDT_TRANSFER_FIXTURE, "ETHEREUM")
    # 65000 * 20_000_000_000 = 1.3e15 wei = 0.0013 ETH
    assert out["gas_fee"] == "0.0013"
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_cashflow_tx_fetch.py -v
```
Expected: 2 new tests FAIL with `AttributeError: module 'cashflow_tx_fetch' has no attribute 'parse_goldrush'`.

- [ ] **Step 3: Implement `parse_goldrush`**

Append to `scripts/cashflow_tx_fetch.py`:

```python
from decimal import Decimal


_ERC20_TRANSFER_SIG = "Transfer(indexed address from, indexed address to, uint256 value)"


def _wei_to_str(wei_int: int, decimals: int) -> str:
    """Convert integer minor units → decimal string, no scientific notation.

    decimals=18 with wei_int=1_300_000_000_000_000 → "0.0013"
    Trailing zeros past the radix point are stripped, BUT we keep them for
    token amounts so callers can preserve advertised precision (caller's choice
    by passing the right `decimals`).
    """
    if decimals == 0:
        return str(wei_int)
    quant = Decimal(10) ** decimals
    return format(Decimal(wei_int) / quant, "f")


def _normalize_amount(raw: str | int, decimals: int) -> str:
    """Token amount: keep declared precision (don't strip trailing zeros)."""
    raw_int = int(raw)
    if decimals == 0:
        return str(raw_int)
    whole, frac = divmod(raw_int, 10 ** decimals)
    return f"{whole}.{str(frac).zfill(decimals)}"


def parse_goldrush(resp: dict, network: str) -> dict:
    """Parse Covalent /transaction_v2 response into our normalized shape.

    Caller is responsible for checking that `resp` is the success-shape (data.items
    non-empty) before calling — see fetch_tx() for the error-mapping layer.
    """
    item = resp["data"]["items"][0]
    gas_spent = int(item["gas_spent"])
    gas_price = int(item["gas_price"])
    gas_fee_wei = gas_spent * gas_price
    gas_fee = _wei_to_str(gas_fee_wei, 18).rstrip("0").rstrip(".")
    if gas_fee == "" or gas_fee == "-":
        gas_fee = "0"

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
            # Non-standard token (no decimals/symbol in response) — skip.
            continue
        transfers.append({
            "asset": ticker,
            "amount": _normalize_amount(params["value"], int(decimals)),
            "from": params["from"],
            "to": params["to"],
            "decimals": int(decimals),
            "contract_address": contract,
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
```

- [ ] **Step 4: Run to verify all pass**

```bash
pytest tests/test_cashflow_tx_fetch.py -v
```
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/cashflow_tx_fetch.py tests/test_cashflow_tx_fetch.py
git commit -m "feat(cashflow): parse single ERC-20 transfer from Goldrush"
```

---

## Task 4: Native transfer fallback + multi-transfer support

**Goal:** When the tx has no Transfer logs but `value > 0`, synthesize a single native transfer (e.g., 0.5 ETH). When the tx has multiple Transfer logs, return them all in order.

**Files:**
- Modify: `scripts/cashflow_tx_fetch.py` (extend `parse_goldrush`)
- Modify: `tests/test_cashflow_tx_fetch.py` (add 2 fixtures + 3 tests)

**Acceptance Criteria:**
- [ ] Tx with `log_events=[]` and `value="500000000000000000"` (0.5 ETH) → one synthetic transfer with `asset="ETH"`, `amount="0.5"`, `decimals=18`, `contract_address=None`.
- [ ] Tx with two Transfer logs → both returned in fixture order.
- [ ] Native transfer's `from`/`to` mirror the tx-level `from_address`/`to_address`.

**Verify:**
```bash
pytest tests/test_cashflow_tx_fetch.py -v
```
Expected: 14 tests pass.

**Steps:**

- [ ] **Step 1: Add fixtures + failing tests**

Append to `tests/test_cashflow_tx_fetch.py`:

```python
# ── §4: Native transfer + multi-transfer ─────────────────────────

NATIVE_ETH_FIXTURE = {
    "data": {
        "items": [{
            "block_signed_at": "2026-05-22T15:00:00Z",
            "block_height": 19234600,
            "tx_hash": "0x" + "b" * 64,
            "from_address": "0xaaaa000000000000000000000000000000000000",
            "to_address":   "0xbbbb000000000000000000000000000000000000",
            "value": "500000000000000000",   # 0.5 ETH
            "gas_spent": 21000,
            "gas_price": 10_000_000_000,
            "log_events": [],
        }],
    },
}


def test_parse_native_transfer_synthesized_when_no_logs():
    out = cashflow_tx_fetch.parse_goldrush(NATIVE_ETH_FIXTURE, "ETHEREUM")
    assert out["transfers"] == [{
        "asset": "ETH",
        "amount": "0.500000000000000000",
        "from": "0xaaaa000000000000000000000000000000000000",
        "to":   "0xbbbb000000000000000000000000000000000000",
        "decimals": 18,
        "contract_address": None,
    }]


def test_parse_native_transfer_uses_chain_native_asset():
    out = cashflow_tx_fetch.parse_goldrush(NATIVE_ETH_FIXTURE, "BINANCE SMART CHAIN")
    assert out["transfers"][0]["asset"] == "BNB"


# Two-transfer fixture: a USDC withdraw that also moves a small fee token.
MULTI_TRANSFER_FIXTURE = {
    "data": {
        "items": [{
            "block_signed_at": "2026-05-22T16:00:00Z",
            "block_height": 19234700,
            "tx_hash": "0x" + "c" * 64,
            "from_address": "0xcccc000000000000000000000000000000000000",
            "to_address":   "0xdddd000000000000000000000000000000000000",
            "value": "0",
            "gas_spent": 120000,
            "gas_price": 25_000_000_000,
            "log_events": [
                {
                    "sender_contract_decimals": 6,
                    "sender_contract_ticker_symbol": "USDC",
                    "sender_address": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
                    "decoded": {
                        "name": "Transfer",
                        "signature": _ERC20_SIG := "Transfer(indexed address from, indexed address to, uint256 value)",
                        "params": [
                            {"name": "from",  "type": "address", "value": "0xcccc000000000000000000000000000000000000"},
                            {"name": "to",    "type": "address", "value": "0xdddd000000000000000000000000000000000000"},
                            {"name": "value", "type": "uint256", "value": "1000000000"},  # 1000 USDC
                        ],
                    },
                },
                {
                    "sender_contract_decimals": 18,
                    "sender_contract_ticker_symbol": "FEE",
                    "sender_address": "0xfee0000000000000000000000000000000000000",
                    "decoded": {
                        "name": "Transfer",
                        "signature": _ERC20_SIG,
                        "params": [
                            {"name": "from",  "type": "address", "value": "0xcccc000000000000000000000000000000000000"},
                            {"name": "to",    "type": "address", "value": "0xfee1111111111111111111111111111111111111"},
                            {"name": "value", "type": "uint256", "value": "5000000000000000000"},  # 5 FEE
                        ],
                    },
                },
            ],
        }],
    },
}


def test_parse_multi_transfer_returns_all_in_order():
    out = cashflow_tx_fetch.parse_goldrush(MULTI_TRANSFER_FIXTURE, "ETHEREUM")
    assert len(out["transfers"]) == 2
    assert out["transfers"][0]["asset"] == "USDC"
    assert out["transfers"][0]["amount"] == "1000.000000"
    assert out["transfers"][1]["asset"] == "FEE"
    assert out["transfers"][1]["amount"] == "5.000000000000000000"
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_cashflow_tx_fetch.py -v
```
Expected: `test_parse_native_transfer_synthesized_when_no_logs` and `test_parse_native_transfer_uses_chain_native_asset` FAIL (empty transfers list). `test_parse_multi_transfer_returns_all_in_order` PASSES (the existing loop already handles multiple).

- [ ] **Step 3: Extend `parse_goldrush` for native fallback**

In `scripts/cashflow_tx_fetch.py`, inside `parse_goldrush`, after the `for log in item.get("log_events") or []:` loop and BEFORE the `return` statement, insert:

```python
    if not transfers and int(item.get("value", "0")) > 0:
        native_value = int(item["value"])
        transfers.append({
            "asset": CHAINS[network]["native_asset"],
            "amount": _normalize_amount(native_value, 18),
            "from": item["from_address"],
            "to": item["to_address"],
            "decimals": 18,
            "contract_address": None,
        })
```

- [ ] **Step 4: Run to verify all pass**

```bash
pytest tests/test_cashflow_tx_fetch.py -v
```
Expected: 14 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/cashflow_tx_fetch.py tests/test_cashflow_tx_fetch.py
git commit -m "feat(cashflow): synthesize native transfer when no Transfer logs"
```

---

## Task 5: HTTP layer — `fetch_tx` orchestration + error mapping

**Goal:** Add `fetch_tx(payload)` which orchestrates `validate_input → call_goldrush → parse_goldrush`, mapping every failure mode to the right exit code + JSON shape. Mock `urllib.request.urlopen` so tests are pure-logic.

**Files:**
- Modify: `scripts/cashflow_tx_fetch.py` (add `call_goldrush`, `fetch_tx`, `main`)
- Modify: `tests/test_cashflow_tx_fetch.py` (add `urlopen` mocking tests)

**Acceptance Criteria:**
- [ ] Happy path: `fetch_tx({tx_hash, network})` returns `(EXIT_OK, {"ok": True, ...parsed...})`.
- [ ] Validation fail → `(EXIT_VALIDATION, {"ok": False, "error": ...})`.
- [ ] Goldrush 404 → `(EXIT_NOT_FOUND, {"ok": False, "error": "tx not found", "code": "not_found"})`.
- [ ] Goldrush 5xx or `URLError` → `(EXIT_UPSTREAM, {"ok": False, "error": "upstream unavailable", "code": "upstream"})`.
- [ ] Missing `GOLDRUSH_API_KEY` env → `(EXIT_MISCONFIG, {"ok": False, "error": "server misconfigured"})`.
- [ ] Empty transfers + zero native value → `(EXIT_NO_XFERS, {"ok": False, "error": "no transfers", "code": "no_transfers"})`.

**Verify:**
```bash
pytest tests/test_cashflow_tx_fetch.py -v
```
Expected: 21 tests pass.

**Steps:**

- [ ] **Step 1: Add failing tests**

Append to `tests/test_cashflow_tx_fetch.py`:

```python
# ── §5: HTTP orchestration ───────────────────────────────────────

import io
import json as _json
from urllib.error import HTTPError, URLError


def _fake_urlopen_json(body: dict):
    """Build a fake urlopen() return value with .read() yielding the JSON body."""
    return io.BytesIO(_json.dumps(body).encode("utf-8"))


def test_fetch_tx_happy_path(monkeypatch):
    monkeypatch.setenv("GOLDRUSH_API_KEY", "test-key")
    monkeypatch.setattr(
        cashflow_tx_fetch.urllib.request, "urlopen",
        lambda req, timeout=None: _fake_urlopen_json(USDT_TRANSFER_FIXTURE),
    )
    code, out = cashflow_tx_fetch.fetch_tx({"tx_hash": VALID_HASH, "network": "ETHEREUM"})
    assert code == cashflow_tx_fetch.EXIT_OK
    assert out["ok"] is True
    assert out["transfers"][0]["asset"] == "USDT"
    assert out["gas_fee"] == "0.0013"


def test_fetch_tx_validation_fail_no_http_call(monkeypatch):
    monkeypatch.setenv("GOLDRUSH_API_KEY", "test-key")
    def _boom(*a, **k):
        raise AssertionError("urlopen must not be called on validation failure")
    monkeypatch.setattr(cashflow_tx_fetch.urllib.request, "urlopen", _boom)
    code, out = cashflow_tx_fetch.fetch_tx({"tx_hash": "nope", "network": "ETHEREUM"})
    assert code == cashflow_tx_fetch.EXIT_VALIDATION
    assert out["ok"] is False


def test_fetch_tx_goldrush_404(monkeypatch):
    monkeypatch.setenv("GOLDRUSH_API_KEY", "test-key")
    def _raise_404(req, timeout=None):
        raise HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(b""))
    monkeypatch.setattr(cashflow_tx_fetch.urllib.request, "urlopen", _raise_404)
    code, out = cashflow_tx_fetch.fetch_tx({"tx_hash": VALID_HASH, "network": "ETHEREUM"})
    assert code == cashflow_tx_fetch.EXIT_NOT_FOUND
    assert out == {"ok": False, "error": "tx not found", "code": "not_found"}


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_fetch_tx_goldrush_5xx_maps_to_upstream(monkeypatch, status):
    monkeypatch.setenv("GOLDRUSH_API_KEY", "test-key")
    def _raise_5xx(req, timeout=None):
        raise HTTPError(req.full_url, status, "Server Error", {}, io.BytesIO(b""))
    monkeypatch.setattr(cashflow_tx_fetch.urllib.request, "urlopen", _raise_5xx)
    code, out = cashflow_tx_fetch.fetch_tx({"tx_hash": VALID_HASH, "network": "ETHEREUM"})
    assert code == cashflow_tx_fetch.EXIT_UPSTREAM
    assert out["code"] == "upstream"


def test_fetch_tx_network_unreachable_maps_to_upstream(monkeypatch):
    monkeypatch.setenv("GOLDRUSH_API_KEY", "test-key")
    def _urlerror(req, timeout=None):
        raise URLError("DNS lookup failed")
    monkeypatch.setattr(cashflow_tx_fetch.urllib.request, "urlopen", _urlerror)
    code, out = cashflow_tx_fetch.fetch_tx({"tx_hash": VALID_HASH, "network": "ETHEREUM"})
    assert code == cashflow_tx_fetch.EXIT_UPSTREAM
    assert out["code"] == "upstream"


def test_fetch_tx_missing_api_key(monkeypatch):
    monkeypatch.delenv("GOLDRUSH_API_KEY", raising=False)
    code, out = cashflow_tx_fetch.fetch_tx({"tx_hash": VALID_HASH, "network": "ETHEREUM"})
    assert code == cashflow_tx_fetch.EXIT_MISCONFIG


def test_fetch_tx_no_transfers_and_zero_value(monkeypatch):
    monkeypatch.setenv("GOLDRUSH_API_KEY", "test-key")
    empty = {"data": {"items": [{
        "block_signed_at": "2026-05-22T17:00:00Z", "block_height": 1, "tx_hash": VALID_HASH,
        "from_address": "0x0", "to_address": "0x1",
        "value": "0", "gas_spent": 21000, "gas_price": 1, "log_events": [],
    }]}}
    monkeypatch.setattr(
        cashflow_tx_fetch.urllib.request, "urlopen",
        lambda req, timeout=None: _fake_urlopen_json(empty),
    )
    code, out = cashflow_tx_fetch.fetch_tx({"tx_hash": VALID_HASH, "network": "ETHEREUM"})
    assert code == cashflow_tx_fetch.EXIT_NO_XFERS
    assert out["code"] == "no_transfers"
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_cashflow_tx_fetch.py -v
```
Expected: 7 new tests FAIL (`fetch_tx` doesn't exist yet, `urllib` not imported at module level).

- [ ] **Step 3: Implement `call_goldrush` + `fetch_tx` + `main`**

Append to `scripts/cashflow_tx_fetch.py`:

```python
import json
import os
import sys
import urllib.request
import urllib.error


GOLDRUSH_BASE = "https://api.covalenthq.com/v1"
GOLDRUSH_TIMEOUT_SEC = 15


def call_goldrush(tx_hash: str, network: str, api_key: str) -> dict:
    """Single HTTP GET to Goldrush. Returns decoded JSON. Raises HTTPError/URLError."""
    chain = CHAINS[network]["chain_name"]
    url = f"{GOLDRUSH_BASE}/{chain}/transaction_v2/{tx_hash}/"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    with urllib.request.urlopen(req, timeout=GOLDRUSH_TIMEOUT_SEC) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_tx(payload: dict) -> tuple[int, dict]:
    """Top-level: validate → call → parse → map errors. Returns (exit_code, json_body)."""
    api_key = os.environ.get("GOLDRUSH_API_KEY")
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

    return EXIT_OK, {"ok": True, **parsed}


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
```

- [ ] **Step 4: Run to verify all pass**

```bash
pytest tests/test_cashflow_tx_fetch.py -v
```
Expected: 21 passed.

- [ ] **Step 5: Lint**

```bash
bash scripts/lint_python.sh
```
Expected: no errors. (If `lint_python.sh` complains about unused imports, fix and re-run pytest.)

- [ ] **Step 6: Commit**

```bash
git add scripts/cashflow_tx_fetch.py tests/test_cashflow_tx_fetch.py
git commit -m "feat(cashflow): wire tx_fetch HTTP orchestration with error mapping"
```

---

## Task 6: Wire `POST /api/cashflow/fetch-tx` in `server.js`

**Goal:** Add the Node route. Extend `httpStatusFor` so the script's new `code` strings (`upstream`, `no_transfers`) map to 502 and 422. Verify the route is session-gated (admin/operator session required, same as other `/api/cashflow/*` routes).

**Files:**
- Modify: `server.js` (extend `httpStatusFor`, add `CASHFLOW_TX_FETCH_SCRIPT` const + route handler)

**Acceptance Criteria:**
- [ ] `node -e "require('./server.js')"` doesn't throw (syntax check).
- [ ] `httpStatusFor(0, {})` still returns 200, `httpStatusFor(3, {})` returns 400, `httpStatusFor(99, {code:"upstream"})` returns 502, `httpStatusFor(99, {code:"no_transfers"})` returns 422.
- [ ] Hitting the route without a session cookie returns 401 (uses the same session middleware as `/api/cashflow/insert`).
- [ ] Hitting the route with a session cookie, a valid hash, and a Goldrush mock returns the parsed JSON.

**Verify:**
```bash
# Boot server in one shell:
PYTHON=python3 GOLDRUSH_API_KEY=$GOLDRUSH_API_KEY node server.js

# In another shell, unauthenticated:
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8080/api/cashflow/fetch-tx \
  -H "Content-Type: application/json" \
  -d '{"tx_hash":"0xaaaa...","network":"ETHEREUM"}'
# Expected: 401

# Authenticated (replace SID with a real cookie value from a logged-in session):
curl -s -X POST http://localhost:8080/api/cashflow/fetch-tx \
  -H "Content-Type: application/json" \
  -H "Cookie: mo_sid=<SID>" \
  -d '{"tx_hash":"0x<real_eth_tx>","network":"ETHEREUM"}' | jq .
# Expected: {"ok": true, "transfers": [...], ...}
```

**Steps:**

- [ ] **Step 1: Extend `httpStatusFor`**

Find `function httpStatusFor(exitCode, json)` (around line 238). Replace it with:

```javascript
// Map a Python exit code → HTTP status code.
function httpStatusFor(exitCode, json) {
  if (exitCode === 0) return 200;
  if (json && json.code === "conflict") return 409;
  if (json && json.code === "not_found") return 404;
  if (json && json.code === "no_transfers") return 422;
  if (json && json.code === "upstream") return 502;
  if (exitCode === 3) return 400;  // validation
  if (exitCode === 4) return 404;  // not_found (fallback if code missing)
  if (exitCode === 6) return 401;  // auth failure
  return 500;
}
```

- [ ] **Step 2: Add the script-path constant**

Find the block where other `*_SCRIPT` constants are defined (search for `CASHFLOW_INSERT_SCRIPT` around line 18). Add right next to it, matching the existing `resolve(...)` style (the file already imports `resolve` from `"path"` at the top):

```javascript
const CASHFLOW_TX_FETCH_SCRIPT = resolve(__dirname, "scripts", "cashflow_tx_fetch.py");
```

- [ ] **Step 3: Add the route handler**

Find the existing `// POST /api/cashflow/insert` block (around line 576). Immediately after that handler's closing `}` (and before the next route), add:

```javascript
  // POST /api/cashflow/fetch-tx
  //   Body: { tx_hash, network }
  //   Calls Goldrush via scripts/cashflow_tx_fetch.py and returns parsed transfers.
  //   Session-gated like all /api/cashflow/* — the global middleware already enforces it.
  if (req.url === "/api/cashflow/fetch-tx" && req.method === "POST") {
    const rawBody = await readBody(req);
    const { code, json, stderr } = await spawnPython(CASHFLOW_TX_FETCH_SCRIPT, rawBody);
    if (stderr) {
      // surfaced in spawnPython's own structured log when code !== 0; nothing extra here.
    }
    res.statusCode = httpStatusFor(code, json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(json));
    return;
  }
```

> **Verify the session-gating story:** open `server.js`, search for the block that bypasses auth for public routes (look for `/api/auth/login`, `/api/auth/register`, `/api/health`). Confirm `/api/cashflow/fetch-tx` is NOT in that bypass list. If a `/api/cashflow/*` prefix check protects all cashflow routes uniformly, no further change is needed — the new route inherits the same gate. If you find a per-route allowlist instead, add `/api/cashflow/fetch-tx` to it alongside the other cashflow routes.

- [ ] **Step 4: Syntax-check**

```bash
node -e "require('./server.js')"
```
Expected: silent (no output, no error). If it throws, fix the syntax issue and retry.

- [ ] **Step 5: Manual smoke (requires real `GOLDRUSH_API_KEY` and a logged-in session)**

Boot the server:
```bash
PYTHON=python3 GOLDRUSH_API_KEY=<your_key> node server.js
```

In a browser, log in normally to mint a session cookie, then in DevTools console:
```javascript
fetch('/api/cashflow/fetch-tx', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    tx_hash: '0x<real_ethereum_tx_hash>',
    network: 'ETHEREUM',
  }),
}).then(r => r.json()).then(console.log)
```
Expected: `{ok: true, transfers: [...], gas_fee: "...", ...}` printed.

Also try with a known-bad hash → expect 400. Unauthenticated (Incognito tab without login) → expect 401.

- [ ] **Step 6: Commit**

```bash
git add server.js
git commit -m "feat(cashflow): add POST /api/cashflow/fetch-tx route"
```

---

## Task 7: Frontend — Fetch button + loading/error state

**Goal:** Add the Fetch button beside the `tx_hash` input in the cashflow section of `TradeBookingForm.jsx`. Disabled until network is EVM AND hash matches `/^0x[0-9a-fA-F]{64}$/`. Click → POST `/api/cashflow/fetch-tx`. Loading spinner. Inline red error on failure. (Multi-transfer picker comes in Task 9. Field auto-fill comes in Task 8.)

**Files:**
- Modify: `src/TradeBookingForm.jsx` (cashflow section — find by searching for `cf_direction` or `tx_hash` field declaration)

**Acceptance Criteria:**
- [ ] Picking a non-EVM network (e.g., SOLANA, BITCOIN) disables the button; hover shows the tooltip "Tx fetch only supports EVM chains for now".
- [ ] An invalid hash (wrong length / non-hex / no `0x`) disables the button; tooltip: "Enter a valid 0x… hash".
- [ ] Clicking Fetch shows a spinner inside the button and disables it until the response returns.
- [ ] On 4xx/5xx, a small red one-liner appears under the input with the user-facing string from §5 of the spec.
- [ ] On 200, the response JSON is stashed in component state (verified via DevTools); fields do NOT yet auto-fill (Task 8).

**Verify:**
```bash
npm run dev
# Open the cashflow form in browser, exercise the disabled states, click Fetch
# with a real hash, observe spinner + JSON response in React DevTools.
```

**Steps:**

- [ ] **Step 1: Locate the cashflow section**

```bash
grep -n "cf_direction\|tx_hash\|cashflow" src/TradeBookingForm.jsx | head -30
```

Identify (a) the React state setter for the cashflow form (look for `setCashflowForm` or similar around line 5598-5670 per the design), and (b) the JSX block rendering the `tx_hash` input.

- [ ] **Step 2: Add the validation helper + EVM-chain set**

Near the top of `TradeBookingForm.jsx` (alongside any other module-scope constants), add:

```javascript
import { Loader2 } from "lucide-react";

const EVM_NETWORKS = new Set([
  "ETHEREUM", "BINANCE SMART CHAIN", "POLYGON", "ARBITRUM", "OPTIMISM",
  "BASE", "AVALANCHE", "LINEA", "SCROLL", "MANTLE", "BLAST", "MODE",
  "CELO", "ZKSYNC", "SONIC", "GNOSIS", "BERACHAIN", "HYPEREVM",
  "UNICHAIN", "SONEIUM", "ZETA", "PLASMA", "TEMPO", "SAGAEVM", "XRPLEVM",
]);

const TX_HASH_RE = /^0x[0-9a-fA-F]{64}$/;

function fetchButtonDisabledReason(network, txHash) {
  if (!network) return "Pick a network first";
  if (!EVM_NETWORKS.has(network)) return "Tx fetch only supports EVM chains for now";
  if (!txHash || !TX_HASH_RE.test(txHash.trim())) return "Enter a valid 0x… hash";
  return null;
}
```

> **Note on the Set duplication:** the canonical list lives in `scripts/cashflow_tx_fetch.py:CHAINS`. We duplicate it client-side so the button disabled state can be computed instantly without a round-trip. If a chain is ever added/removed, update both. Accept this duplication — it's cheap and the alternative (fetching the EVM list at boot) adds latency to the first form render for no real benefit.

- [ ] **Step 3: Add the fetch state + handler in the cashflow form component**

Inside the cashflow form component (next to where `cashflowForm` and `setCashflowForm` are defined), add:

```javascript
const [txFetchLoading, setTxFetchLoading] = useState(false);
const [txFetchError, setTxFetchError] = useState(null);
const [txFetchResult, setTxFetchResult] = useState(null);  // {transfers, gas_fee, ...} | null

async function handleFetchTx() {
  setTxFetchError(null);
  setTxFetchResult(null);
  setTxFetchLoading(true);
  try {
    const res = await fetch("/api/cashflow/fetch-tx", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({
        tx_hash: cashflowForm.tx_hash.trim(),
        network: cashflowForm.network,
      }),
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok) {
      setTxFetchError(txFetchErrorMessage(res.status, json));
      return;
    }
    setTxFetchResult(json);
    // Task 8 will hook applyAutofill here.
  } catch (e) {
    setTxFetchError("Couldn't reach the server, try again");
  } finally {
    setTxFetchLoading(false);
  }
}

function txFetchErrorMessage(status, json) {
  if (status === 400) return "Couldn't read that hash, double-check it";
  if (status === 404) return `Not found on ${cashflowForm.network} — wrong network?`;
  if (status === 422) return "No token or native transfers found in this tx";
  if (status === 502) return "Couldn't reach chain explorer, try again";
  return "Something went wrong fetching this tx";
}
```

- [ ] **Step 4: Render the Fetch button + error line under the existing tx_hash input**

Find the JSX block that renders the `tx_hash` input (search for the existing field — it's likely a labeled `<input>` bound to `cashflowForm.tx_hash` / `setCashflowForm`). Wrap the input + new button in a row, and add the error/spinner below:

```jsx
{/* existing tx_hash field — wrap input + new Fetch button in a flex row */}
<div className="flex gap-2 items-stretch">
  <input
    type="text"
    value={cashflowForm.tx_hash}
    onChange={(e) => {
      setCashflowForm({ ...cashflowForm, tx_hash: e.target.value });
      setTxFetchError(null);     // clear stale error on edit
      setTxFetchResult(null);
    }}
    className="<keep existing classes>"
    placeholder="0x…"
  />
  <button
    type="button"
    onClick={handleFetchTx}
    disabled={txFetchLoading || fetchButtonDisabledReason(cashflowForm.network, cashflowForm.tx_hash) !== null}
    title={fetchButtonDisabledReason(cashflowForm.network, cashflowForm.tx_hash) || "Fetch on-chain details"}
    className="px-3 py-1 rounded bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 text-white text-sm flex items-center gap-1"
  >
    {txFetchLoading ? <><Loader2 className="w-4 h-4 animate-spin" /> Fetching…</> : "Fetch"}
  </button>
</div>
{txFetchError && (
  <div className="text-red-600 text-xs mt-1">{txFetchError}</div>
)}
```

> Match the surrounding Tailwind classes — the snippet above uses generic colors; if the form uses a different palette (terminal green, etc.), align with neighboring buttons in the same form.

- [ ] **Step 5: Manual UI check**

```bash
npm run dev
```

In the browser:
1. Open the cashflow form. Confirm Fetch button is visible next to the tx_hash input.
2. With network empty → button disabled, tooltip "Pick a network first".
3. Pick "SOLANA" (non-EVM) → button disabled, tooltip "Tx fetch only supports EVM chains for now".
4. Pick "ETHEREUM" → button still disabled until a valid hash is typed; tooltip "Enter a valid 0x… hash".
5. Paste a real Ethereum tx hash → button enables.
6. Click → spinner shows briefly. Use React DevTools to confirm `txFetchResult` state is populated.

- [ ] **Step 6: Commit**

```bash
git add src/TradeBookingForm.jsx
git commit -m "feat(cashflow): add tx_hash fetch button with loading + error state"
```

---

## Task 8: Frontend — `applyAutofill` empty-only helper (single-transfer auto-apply)

**Goal:** When the response has exactly one transfer (or one synthetic native transfer), call `applyAutofill` to fill the empty-only fields per the spec's §4.3 table. Multi-transfer case (>1) is still skipped for now — Task 9 adds the picker.

**Files:**
- Modify: `src/TradeBookingForm.jsx` (add `applyAutofill`, wire into `handleFetchTx`)

**Acceptance Criteria:**
- [ ] After a successful fetch with one transfer, these empty fields fill: `cf_asset`, `cf_amount`, `gas_asset`, `gas_fee`, `trade_date`, `value_date`.
- [ ] If any of those were already non-empty, they stay untouched.
- [ ] `notes` always gets `\nfrom: 0x… → to: 0x… (tx 0x…)` appended (with a leading newline iff notes was non-empty).
- [ ] A small green "Filled from chain" confirmation appears under the input and auto-dismisses after 4 seconds.
- [ ] These fields are NEVER touched: `cf_direction`, `cf_type`, `counterparty`, `account_name`, `portfolio`, `status`, `fee_asset`, `fee_amount`, `cf_mirror`, `cf_loan_deal_refs`.

**Verify:**
```bash
npm run dev
# In the browser: paste a real single-transfer hash, click Fetch, confirm fields fill correctly.
# Repeat with one field pre-typed (e.g. type "999" into cf_amount first); confirm it survives.
```

**Steps:**

- [ ] **Step 1: Add `applyAutofill` helper**

In `src/TradeBookingForm.jsx`, inside the cashflow form component (near `handleFetchTx`):

```javascript
function isEmpty(v) {
  return v === "" || v === null || v === undefined;
}

function applyAutofill(transfer, result) {
  const dateOnly = (result.timestamp || "").slice(0, 10);  // "2026-05-22T…" → "2026-05-22"
  setCashflowForm((prev) => {
    const next = { ...prev };
    if (isEmpty(next.cf_asset))   next.cf_asset   = transfer.asset;
    if (isEmpty(next.cf_amount))  next.cf_amount  = transfer.amount;
    if (isEmpty(next.gas_asset))  next.gas_asset  = result.gas_asset;
    if (isEmpty(next.gas_fee))    next.gas_fee    = result.gas_fee;
    if (isEmpty(next.trade_date)) next.trade_date = dateOnly;
    if (isEmpty(next.value_date)) next.value_date = dateOnly;
    const stamp = `from: ${result.tx_from} → to: ${result.tx_to} (tx ${prev.tx_hash})`;
    next.notes = isEmpty(prev.notes) ? stamp : `${prev.notes}\n${stamp}`;
    return next;
  });
  setTxFetchSuccess("Filled from chain");
  setTimeout(() => setTxFetchSuccess(null), 4000);
}
```

- [ ] **Step 2: Add the success-message state**

Add next to `txFetchError`:

```javascript
const [txFetchSuccess, setTxFetchSuccess] = useState(null);
```

- [ ] **Step 3: Wire into `handleFetchTx`**

Inside `handleFetchTx`, replace the comment `// Task 8 will hook applyAutofill here.` with:

```javascript
    if (json.transfers && json.transfers.length === 1) {
      applyAutofill(json.transfers[0], json);
      setTxFetchResult(null);   // hide the result; the form now has the data
    } else {
      // Multi-transfer — Task 9 surfaces the picker by keeping txFetchResult set.
      setTxFetchResult(json);
    }
```

- [ ] **Step 4: Render the success line**

Below the existing `{txFetchError && …}` block:

```jsx
{txFetchSuccess && (
  <div className="text-green-600 text-xs mt-1">{txFetchSuccess}</div>
)}
```

- [ ] **Step 5: Also clear success on field-edit**

In the `onChange` of the `tx_hash` input, add `setTxFetchSuccess(null);` next to the existing clears.

- [ ] **Step 6: Manual UI check**

```bash
npm run dev
```

Test scenarios:
1. **Empty form → real single-transfer hash:** all six target fields fill; "Filled from chain" appears then disappears. Confirm `notes` shows the from→to stamp.
2. **Pre-typed `cf_amount=999` → real hash:** after Fetch, `cf_amount` is still 999; other empty fields fill.
3. **Pre-typed `notes="manual entry"` → real hash:** notes becomes `"manual entry\nfrom: 0x… → to: 0x… (tx 0x…)"`.

- [ ] **Step 7: Commit**

```bash
git add src/TradeBookingForm.jsx
git commit -m "feat(cashflow): autofill cashflow fields from tx_hash fetch"
```

---

## Task 9: Frontend — multi-transfer picker

**Goal:** When the fetch returns more than one transfer, render a small inline card list under the tx_hash input. Each card shows the transfer's asset/amount/from/to with a "Use this" button. Picking one calls `applyAutofill` for that transfer and dismisses the picker. A "Cancel" link dismisses without filling.

**Files:**
- Modify: `src/TradeBookingForm.jsx` (add picker JSX + handlers; no new files)

**Acceptance Criteria:**
- [ ] Fetching a tx with 2+ transfers shows a picker below the input listing each transfer with `{asset} {amount} — {from_short} → {to_short}` (`from_short` = first 6 + last 4 chars of address).
- [ ] Each row has a "Use this" button that fills the form and dismisses the picker.
- [ ] A "Cancel" link dismisses the picker without filling.
- [ ] If user clicks Fetch again, the picker is replaced (not stacked).

**Verify:**
```bash
npm run dev
# In the browser: paste a tx hash with multiple transfers (e.g. a Uniswap swap),
# confirm picker appears, exercise both Use this and Cancel.
```

**Steps:**

- [ ] **Step 1: Add address-shortener helper**

Near `fetchButtonDisabledReason`:

```javascript
function shortAddr(addr) {
  if (!addr || addr.length < 12) return addr || "";
  return `${addr.slice(0, 6)}…${addr.slice(-4)}`;
}
```

- [ ] **Step 2: Render the picker**

Below the `{txFetchSuccess && …}` block:

```jsx
{txFetchResult && txFetchResult.transfers && txFetchResult.transfers.length > 1 && (
  <div className="mt-2 border border-gray-300 rounded p-2 bg-gray-50">
    <div className="text-xs text-gray-600 mb-1">
      Multiple transfers in this tx — pick the one to import:
    </div>
    <ul className="space-y-1">
      {txFetchResult.transfers.map((t, i) => (
        <li key={i} className="flex items-center justify-between text-sm">
          <span>
            <span className="font-mono">{t.amount}</span> {t.asset}
            <span className="text-gray-500"> — {shortAddr(t.from)} → {shortAddr(t.to)}</span>
          </span>
          <button
            type="button"
            onClick={() => { applyAutofill(t, txFetchResult); setTxFetchResult(null); }}
            className="ml-2 px-2 py-0.5 text-xs rounded bg-blue-600 hover:bg-blue-700 text-white"
          >
            Use this
          </button>
        </li>
      ))}
    </ul>
    <button
      type="button"
      onClick={() => setTxFetchResult(null)}
      className="mt-2 text-xs text-gray-500 hover:text-gray-700 underline"
    >
      Cancel
    </button>
  </div>
)}
```

- [ ] **Step 3: Manual UI check**

```bash
npm run dev
```

Test scenarios:
1. **Multi-transfer hash (Uniswap swap):** picker shows two rows. Click "Use this" on the second → that transfer's asset/amount fills; picker dismisses.
2. **Cancel:** click Cancel → picker dismisses, no fields change.
3. **Re-fetch:** with picker open, edit the hash and click Fetch again → old picker is replaced (the `setTxFetchResult(null)` at the top of `handleFetchTx` handles this).

- [ ] **Step 4: Commit**

```bash
git add src/TradeBookingForm.jsx
git commit -m "feat(cashflow): add multi-transfer picker for tx_hash fetch"
```

---

## Task 10: Docs, `.env.example`, version bump, push

**Goal:** Document the new env var and feature, bump the version per repo convention, push.

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `helm/Chart.yaml`, `version.yml` (via the bump script)

**Acceptance Criteria:**
- [ ] `.env.example` has a `GOLDRUSH_API_KEY=` line with a one-line comment.
- [ ] `README.md` has a short section under the existing feature list mentioning the new "Fetch from tx hash" cashflow capability and the `GOLDRUSH_API_KEY` env var.
- [ ] `python scripts/update_version.py` ran cleanly and the new patch version is committed.
- [ ] `git push origin main` succeeded.

**Steps:**

- [ ] **Step 1: Add the env var placeholder**

Append to `.env.example` (under the existing block):

```
# Goldrush (Covalent) API key for the cashflow tx-hash auto-fill feature.
# Get one at https://goldrush.dev/
GOLDRUSH_API_KEY=
```

> **Operator note:** add the real key to your local `.env` (gitignored) and to whatever secret store the k8s deploy reads from. Without it, the Fetch button returns "Something went wrong".

- [ ] **Step 2: Update README**

Find the existing cashflow / features section in `README.md` and add a short paragraph:

```markdown
### Cashflow — Auto-fill from tx hash (EVM)

In the cashflow booking form, after picking a network and pasting a transaction
hash, click **Fetch** to pull the asset, amount, gas, and timestamps directly
from chain (via Goldrush/Covalent). Only EVM chains supported in v1 — Solana,
Tron, BTC etc. need to be filled manually. Requires `GOLDRUSH_API_KEY` in env.
```

- [ ] **Step 3: Run the version bump**

```bash
python scripts/update_version.py
```
Expected: prints `bumped X.Y.Z -> X.Y.(Z+1)`. Verifies both `helm/Chart.yaml` and `version.yml` updated.

- [ ] **Step 4: Commit everything together**

```bash
git add .env.example README.md helm/Chart.yaml version.yml
git commit -m "chore: bump version X.Y.Z -> X.Y.(Z+1)"   # use the actual numbers from Step 3
```

- [ ] **Step 5: Push and confirm with the user before continuing**

```bash
git status   # confirm clean
git log --oneline -10   # confirm the 9 feat commits + 1 chore bump
```

Then ask the user: *"Ready to `git push origin main`?"* and only push after explicit OK. The user's workflow is to group thematic commits and confirm before pushing (per memory `feedback_workflow`).

---

## Out of scope (do NOT implement here)

- Non-EVM chains (Solana, Tron, BTC) — separate provider, separate plan.
- Wallet-address → counterparty registry lookup — needs a new refdata table.
- Direction (INCOMING / OUTGOING) inference — requires the wallet registry above.
- Extending Fetch to SPOT, FUTURE, LOAN forms — wait until cashflow proves valuable.
- Caching fetched txs — premature; user fetches once per booking.
- Auto-detecting "this hash was already booked" duplicate-prevention — separate concern.
