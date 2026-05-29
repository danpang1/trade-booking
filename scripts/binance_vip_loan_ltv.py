"""Fetch the current Binance VIP loan LTV for the Loan Enquiry tile.

Reads `{}` (or nothing) from stdin — takes no parameters today; the
empty-object contract is kept so the server's spawnPython wrapper and any
future filters stay uniform with the other scripts.

Writes one JSON object to stdout:

    {"ok": true, "ltv": 0.4230, "ltv_pct": 42.30,
     "status": "healthy|warn|danger|none",
     "warn_ltv": 0.71, "margin_call_ltv": 0.77, "liquidation_ltv": 0.91,
     "order_count": 2, "as_of": "2026-05-29T08:00:00Z"}

`ltv` is the worst-case (max) currentLTV across all ongoing VIP loan
orders on the account. Binance reports the same LTV on every order of a
single account, but taking the max is safe if that ever stops holding.
When there are no ongoing orders, `ltv` is null and `status` is "none".

Credential precedence (first hit wins):
  1. /vault/secrets/gw_secret.json  (Vault agent-inject sidecar, prod)
  2. BINANCE_API_KEY / BINANCE_API_SECRET env vars (k8s Secret)
  3. .env `# BINANCE VIP` marker block (local dev)

Exit codes: 0 success (including the no-orders "none" case); 5 on a
credential/upstream error (the server maps json.code=="upstream" -> 502).
"""
from __future__ import annotations
import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

try:
    import requests
except ImportError:
    print(json.dumps({
        "ok": False,
        "error": "missing 'requests' package — pip install requests",
    }))
    sys.exit(5)


REPO = Path(__file__).resolve().parents[1]
ENV = REPO / ".env"
# Vault agent-inject writes to /vault/secrets/ (PLURAL) by default, and the
# chart sets no secret-volume-path override. The singular /vault/secret/ path
# is kept as a fallback. Override the full path with VAULT_SECRET_PATH.
_VAULT_SECRET_ENV = os.environ.get("VAULT_SECRET_PATH")
if _VAULT_SECRET_ENV:
    VAULT_SECRET_CANDIDATES = [Path(_VAULT_SECRET_ENV)]
else:
    VAULT_SECRET_CANDIDATES = [
        Path("/vault/secrets/gw_secret.json"),
        Path("/vault/secret/gw_secret.json"),
    ]

# gw_secret.json holds many CEX accounts keyed by an internal id; "135" is
# the Binance VIP (tk818) read-only sub-account. Override via env if the id
# ever changes, so the account selection stays out of code/secrets.
VAULT_ACCOUNT_ID = os.environ.get("BINANCE_VAULT_ACCOUNT_ID", "135")

BASE_URL = "https://api.binance.com"
ONGOING_ORDERS_PATH = "/sapi/v1/loan/vip/ongoing/orders"
ACCOUNT_PATH = "/api/v3/account"
COLLATERAL_DATA_PATH = "/sapi/v1/loan/vip/collateral/data"
TICKER_PRICE_PATH = "/api/v3/ticker/price"

# LTV bands. Binance fixes margin-call at 77% and liquidation at 91% for
# VIP loans; 71% is our own early-warning line below the margin call.
WARN_LTV = 0.71
MARGIN_CALL_LTV = 0.77
LIQUIDATION_LTV = 0.91

# Collateral assets pegged to USD — their price doesn't move, so they don't
# participate in the volatile-drop trigger maths (mirrors the MO dashboard).
STABLE_ASSETS = frozenset({"USDT", "USDC", "BUSD", "FDUSD", "TUSD", "DAI"})


# ---------------------------------------------------------------------------
# Credential loading
# ---------------------------------------------------------------------------

def _creds_from_root(root: object, account_id: str) -> tuple[str, str] | None:
    """Extract (api_key, api_secret) from one candidate root dict.

    Tolerant of these shapes, tried in priority order:
      1. The prod gw_secret.json shape — accounts keyed by internal id under
         exchange-credentials → binance:
         {"exchange-credentials": {"binance": {"118": {"ak": ..., "sk": ...}}}}
      2. A flat multi-account map keyed by internal id:
         {"135": {"ak": ..., "sk": ...}, "136": {...}}.
      3. Nested {"binance": {"api_key": ..., "api_secret": ...}}.
      4. Flat {"binance_api_key": ..., "binance_api_secret": ...}.
    Returns None if no usable key+secret pair is found.
    """
    if not isinstance(root, dict):
        return None

    # Prod shape descends through exchange-credentials → binance to the
    # id-keyed account map; older shapes key the account map at the root.
    account_map = root
    ec = root.get("exchange-credentials")
    if isinstance(ec, dict) and isinstance(ec.get("binance"), dict):
        account_map = ec["binance"]

    acct = account_map.get(account_id)
    if isinstance(acct, dict):
        key = acct.get("ak") or acct.get("api_key") or acct.get("API_KEY")
        secret = acct.get("sk") or acct.get("api_secret") \
            or acct.get("API_SECRET")
        if key and secret:
            return str(key), str(secret)

    nested = root.get("binance")
    if isinstance(nested, dict):
        key = nested.get("api_key") or nested.get("API_KEY")
        secret = nested.get("api_secret") or nested.get("API_SECRET")
        if key and secret:
            return str(key), str(secret)

    key = root.get("binance_api_key") or root.get("BINANCE_API_KEY")
    secret = root.get("binance_api_secret") or root.get("BINANCE_API_SECRET")
    if key and secret:
        return str(key), str(secret)
    return None


def _creds_from_doc(doc: object, account_id: str) -> tuple[str, str] | None:
    """Extract (api_key, api_secret) from a parsed gw_secret.json document.

    KV v2 wraps the payload under a "data" key (alongside "metadata"), so we
    try both the document itself and its unwrapped "data" child as candidate
    roots. See _creds_from_root for the accepted per-root shapes.
    Returns None if no usable key+secret pair is found.
    """
    if not isinstance(doc, dict):
        return None

    roots = [doc]
    # Unwrap the KV v2 envelope. Done unconditionally when "data" is a dict —
    # the rendered file may or may not carry the "metadata" sibling.
    if isinstance(doc.get("data"), dict):
        roots.append(doc["data"])

    for root in roots:
        hit = _creds_from_root(root, account_id)
        if hit:
            return hit
    return None


def _from_vault() -> tuple[str, str] | None:
    """Read creds from the Vault agent-inject file, if present.

    The prod gw_secret.json carries every CEX account keyed by internal id;
    VAULT_ACCOUNT_ID selects the Binance one. See _creds_from_doc for the
    accepted shapes. Tries each candidate path (Vault's default mount is
    /vault/secrets/, plural). Returns None if no path yields usable creds.
    """
    for path in VAULT_SECRET_CANDIDATES:
        if not path.exists():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        creds = _creds_from_doc(doc, VAULT_ACCOUNT_ID)
        if creds:
            return creds
    return None


def _from_env() -> tuple[str, str] | None:
    key = os.environ.get("BINANCE_API_KEY")
    secret = os.environ.get("BINANCE_API_SECRET")
    if key and secret:
        return key, secret
    return None


def _from_dotenv() -> tuple[str, str] | None:
    """Read Binance creds from .env (local dev).

    Tolerant of the in-repo layout, which prefixes the account number and
    uses `=` (e.g. `818.BINANCE_API_KEY=...`): every non-comment line is
    split on the first `:` or `=`, the key is matched by SUFFIX so the
    `818.` prefix is ignored, and the value's surrounding whitespace is
    stripped. First match for each of KEY/SECRET wins.
    """
    if not ENV.exists():
        return None
    key = None
    secret = None
    for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        sep = min(
            (s.index(c) for c in (":", "=") if c in s),
            default=-1,
        )
        if sep < 0:
            continue
        name = s[:sep].strip().upper()
        val = s[sep + 1:].strip()
        if not val:
            continue
        if key is None and name.endswith("BINANCE_API_KEY"):
            key = val
        elif secret is None and name.endswith("BINANCE_API_SECRET"):
            secret = val
    if key and secret:
        return key, secret
    return None


def load_creds() -> tuple[str, str]:
    """Resolve (api_key, api_secret) by precedence. Raises on miss."""
    for source in (_from_vault, _from_env, _from_dotenv):
        hit = source()
        if hit:
            return hit
    raise RuntimeError(
        "Binance creds not found in /vault/secrets/gw_secret.json, "
        "BINANCE_API_* env vars, or .env '# BINANCE VIP' block"
    )


# ---------------------------------------------------------------------------
# Binance request
# ---------------------------------------------------------------------------

def _signed_get(path: str, api_key: str, api_secret: str, params=None) -> dict:
    params = dict(params or {})
    params["timestamp"] = int(time.time() * 1000)
    query = urlencode(params)
    signature = hmac.new(
        api_secret.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    params["signature"] = signature
    resp = requests.get(
        f"{BASE_URL}{path}",
        params=params,
        headers={"X-MBX-APIKEY": api_key},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _to_float(val) -> float | None:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _status_for(ltv: float | None) -> str:
    if ltv is None:
        return "none"
    if ltv >= MARGIN_CALL_LTV:
        return "danger"
    if ltv >= WARN_LTV:
        return "warn"
    return "healthy"


# ---------------------------------------------------------------------------
# Collateral / trigger detail (mirrors the MO dashboard's VIP loan view)
# ---------------------------------------------------------------------------

def _public_get(path: str, params=None) -> object:
    resp = requests.get(f"{BASE_URL}{path}", params=params or {}, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_prices(assets) -> dict:
    """Map ASSET -> USD price via USDT/USDC spot pairs; stables = 1.0."""
    wanted = {a.upper() for a in assets if a}
    if not wanted:
        return {}
    raw = _public_get(TICKER_PRICE_PATH)
    pair = {}
    for item in raw:
        pair[item.get("symbol", "")] = _to_float(item.get("price")) or 0.0
    out = {}
    for asset in wanted:
        if asset in STABLE_ASSETS:
            out[asset] = 1.0
        elif f"{asset}USDT" in pair:
            out[asset] = pair[f"{asset}USDT"]
        elif f"{asset}USDC" in pair:
            out[asset] = pair[f"{asset}USDC"]
        else:
            out[asset] = 0.0
    return out


def _get_spot_balances(api_key: str, api_secret: str) -> list:
    """Non-zero spot balances of the collateral account (= VIP collateral)."""
    data = _signed_get(ACCOUNT_PATH, api_key, api_secret)
    balances = data.get("balances", []) if isinstance(data, dict) else []
    out = []
    for b in balances:
        qty = _to_float(b.get("free")) or 0.0
        if qty > 0:
            out.append({"asset": b.get("asset", ""), "qty": qty})
    return out


def _haircut_tiers(api_key: str, api_secret: str) -> dict:
    """Build { COIN: [(min_usd, max_usd, ratio), ...] } from collateral/data."""
    data = _signed_get(COLLATERAL_DATA_PATH, api_key, api_secret)
    rows = data.get("rows", []) if isinstance(data, dict) else []
    tiers = {}
    for h in rows:
        coin = h.get("collateralCoin", "")
        if not coin:
            continue
        coin_tiers = []
        for i in range(1, 20):
            ordinal = {1: "1st", 2: "2nd", 3: "3rd"}.get(i, f"{i}th")
            ratio_str = h.get(f"_{ordinal}CollateralRatio") \
                or h.get(f"{ordinal}CollateralRatio") or ""
            range_str = h.get(f"_{ordinal}CollateralRange") \
                or h.get(f"{ordinal}CollateralRange") or ""
            if not ratio_str or not range_str:
                break
            ratio = (_to_float(ratio_str.replace("%", "")) or 0.0) / 100.0
            low = range_str.lower()
            if low.startswith("above"):
                min_val = _to_float(range_str.split()[-1]) or 0.0
                max_val = float("inf")
            elif "-" in range_str:
                parts = range_str.split("-")
                min_val = _to_float(parts[0]) or 0.0
                max_val = _to_float(parts[1]) or float("inf")
            else:
                continue
            coin_tiers.append((min_val, max_val, ratio))
        if coin_tiers:
            tiers[coin] = coin_tiers
    return tiers


def _haircut_for(tiers: dict, coin: str, usd_value: float) -> float:
    coin_tiers = tiers.get(coin, [])
    if not coin_tiers:
        return 0.0
    for min_val, max_val, ratio in coin_tiers:
        if min_val <= usd_value < max_val:
            return ratio
    return coin_tiers[-1][2]


def build_detail(api_key: str, api_secret: str, rows: list) -> dict:
    """Collateral basket + per-asset margin-call/liquidation trigger prices.

    Trigger maths mirror the MO dashboard: stablecoins hold value, so the
    volatile collateral must fall to multiplier
        x = (totalLoanUSD / targetLTV - stableValue) / volatileValue
    to push LTV up to the target. Per-asset trigger price = price * x.
    """
    loan_coins = [r.get("loanCoin", "") for r in rows if r.get("loanCoin")]
    loan_prices = get_prices(loan_coins)
    total_loan_usd = 0.0
    collateral_post_haircut = 0.0
    locked_collateral = 0.0
    for r in rows:
        coin = r.get("loanCoin", "").upper()
        debt = _to_float(r.get("totalDebt")) or 0.0
        total_loan_usd += debt * loan_prices.get(coin, 1.0)
        cph = _to_float(r.get("totalCollateralValueAfterHaircut")) or 0.0
        collateral_post_haircut = max(collateral_post_haircut, cph)
        locked = _to_float(r.get("lockedCollateralValue")) or 0.0
        locked_collateral = max(locked_collateral, locked)

    # Borrowable USDT = post-haircut collateral not yet locked against a loan
    # (mirrors the MO dashboard's borrowableUSDT). Floored at 0.
    borrowable_usdt = max(0.0, collateral_post_haircut - locked_collateral)

    balances = _get_spot_balances(api_key, api_secret)
    prices = get_prices([b["asset"] for b in balances])
    tiers = _haircut_tiers(api_key, api_secret)

    collateral = []
    stable_value = 0.0
    volatile_value = 0.0
    for b in balances:
        asset = b["asset"].upper()
        qty = b["qty"]
        price = prices.get(asset, 0.0)
        value = qty * price
        if value <= 0:
            continue
        is_stable = asset in STABLE_ASSETS
        if is_stable:
            stable_value += value
        else:
            volatile_value += value
        collateral.append({
            "asset": asset,
            "qty": round(qty, 8),
            "price": round(price, 6),
            "value": round(value, 2),
            "haircut": _haircut_for(tiers, asset, value),
            "volatile": not is_stable,
        })
    collateral.sort(key=lambda c: c["value"], reverse=True)

    def trigger(target_ltv: float) -> dict:
        required = total_loan_usd / target_ltv if target_ltv else 0.0
        if volatile_value > 0:
            x = (required - stable_value) / volatile_value
        else:
            x = 1.0
        return {
            "required_collateral": round(required, 2),
            "multiplier": x,
            "pct_drop": round((1 - x) * 100, 2),
        }

    mc = trigger(MARGIN_CALL_LTV)
    liq = trigger(LIQUIDATION_LTV)
    for c in collateral:
        if c["volatile"]:
            c["mc_price"] = round(c["price"] * mc["multiplier"], 6)
            c["liq_price"] = round(c["price"] * liq["multiplier"], 6)
        else:
            c["mc_price"] = None
            c["liq_price"] = None

    return {
        "summary": {
            "total_loan_usd": round(total_loan_usd, 2),
            "collateral_post_haircut": round(collateral_post_haircut, 2),
            "collateral_raw_value": round(stable_value + volatile_value, 2),
            "locked_collateral_value": round(locked_collateral, 2),
            "borrowable_usdt": round(borrowable_usdt, 2),
            "stable_value": round(stable_value, 2),
            "volatile_value": round(volatile_value, 2),
        },
        "margin_call": mc,
        "liquidation": liq,
        "collateral": collateral,
    }


def main() -> int:
    raw = sys.stdin.read().strip() or "{}"
    try:
        req = json.loads(raw)
    except json.JSONDecodeError:
        req = {}
    want_detail = bool(isinstance(req, dict) and req.get("detail"))

    try:
        api_key, api_secret = load_creds()
    except RuntimeError as e:
        print(json.dumps({"ok": False, "code": "upstream", "error": str(e)}))
        return 5

    try:
        data = _signed_get(
            ONGOING_ORDERS_PATH, api_key, api_secret, {"limit": 50}
        )
    except requests.RequestException as e:
        print(json.dumps({
            "ok": False,
            "code": "upstream",
            "error": "Binance API request failed",
            "detail": str(e)[:300],
        }))
        return 5

    rows = data.get("rows", []) if isinstance(data, dict) else []
    ltvs = [v for v in (_to_float(r.get("currentLTV")) for r in rows) if v is not None]
    ltv = max(ltvs) if ltvs else None

    as_of = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    payload = {
        "ok": True,
        "ltv": ltv,
        "ltv_pct": round(ltv * 100, 2) if ltv is not None else None,
        "status": _status_for(ltv),
        "warn_ltv": WARN_LTV,
        "margin_call_ltv": MARGIN_CALL_LTV,
        "liquidation_ltv": LIQUIDATION_LTV,
        "order_count": len(rows),
        "as_of": as_of,
    }

    if want_detail and rows:
        try:
            payload.update(build_detail(api_key, api_secret, rows))
        except requests.RequestException as e:
            payload["detail_error"] = f"collateral fetch failed: {str(e)[:200]}"
        except Exception as e:
            payload["detail_error"] = f"collateral build failed: {str(e)[:200]}"

    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
