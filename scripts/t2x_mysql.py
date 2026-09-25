"""Read-only client + account-id resolver for the T2X reference_data MySQL.

The manual_* `account_id` is the gateway account id `{T2X_ID}{suffix}`, where
`T2X_ID` is the row id of the account_exchange / account_wallet / account_broker
record and the 3-digit suffix is chosen per account type + product/chain by the
shared rule in `gateway_rule.py` (a faithful port of T2X's gateway.rule.ts):

  * exchange -> product : spot=001, usdt_future=002, coin_future=003, ...
  * broker              : trading=201
  * wallet   -> chain   : ethereum=501, solana=701, bitcoin=801, ...

This matches the account id the position service keys balances on. The old
hardcoded '001' suffix was only ever correct for spot; a perp/margin/wallet
booking needs the type- and product/chain-specific suffix.

Cred convention mirrors sync_accounts.py: T2X_RO_MYSQL_* env vars first, else
the `# t2x-ro-mysql` block in .env (keys ABOVE the marker; lookback-window parse).
"""
from __future__ import annotations
import json
import os
from pathlib import Path

import gateway_rule

REPO = Path(__file__).resolve().parents[1]
ENV = REPO / ".env"

# Process cache of the gateway-rule code map, loaded once from
# reference_data.gateway_rule (the DB source of truth). Falls back to the
# hardcoded port when the table is absent/empty.
_RULE_CODES: dict[str, str] | None = None


def load_gateway_rule_codes(cur) -> dict[str, str] | None:
    """{'exchange-spot': '001', ...} from reference_data.gateway_rule.

    Returns None if the table is missing/empty so the caller can fall back to the
    hardcoded port (an env whose reference_data predates the table still works).
    """
    try:
        cur.execute("SELECT accountType, suffix, code FROM gateway_rule")
        rows = cur.fetchall()
    except Exception:
        return None
    return gateway_rule.codes_from_rows(rows) or None


def _rule_codes(cur) -> dict[str, str]:
    """DB rule codes (cached per process), else the hardcoded port."""
    global _RULE_CODES
    if _RULE_CODES is None:
        _RULE_CODES = load_gateway_rule_codes(cur) or gateway_rule.hardcoded_codes()
    return _RULE_CODES


def load_creds() -> dict[str, str]:
    """Env vars (T2X_RO_MYSQL_*) take precedence; `# t2x-ro-mysql` .env block fallback."""
    env_creds = {
        k: os.environ[f"T2X_RO_MYSQL_{k.upper()}"]
        for k in ("host", "port", "username", "password")
        if f"T2X_RO_MYSQL_{k.upper()}" in os.environ
    }
    if all(k in env_creds for k in ("host", "username", "password")):
        return env_creds

    if not ENV.exists():
        raise FileNotFoundError(
            f".env not found at {ENV} and T2X_RO_MYSQL_* env vars are incomplete"
        )

    lines = ENV.read_text(encoding="utf-8", errors="replace").splitlines()
    creds: dict[str, str] = {}
    for i, ln in enumerate(lines):
        if "t2x-ro-mysql" in ln.lower():
            for j in range(max(0, i - 5), min(len(lines), i + 3)):
                s = lines[j].strip()
                if not s or s.startswith("#"):
                    continue
                if ":" in s:
                    k, _, v = s.partition(":")
                    creds[k.strip().lower()] = v.strip()
            break
    if not all(k in creds for k in ("username", "password", "host")):
        raise RuntimeError("t2x-ro-mysql credentials missing in .env")
    return creds


def connect():
    """Open a pymysql connection to reference_data and pin the session READ-ONLY.

    Creds are the T2X read-only user; the session is additionally forced
    read-only client-side so this service can never write to reference_data.
    """
    import pymysql
    c = load_creds()
    conn = pymysql.connect(
        host=c["host"],
        port=int(c.get("port", "3306")),
        user=c["username"],
        password=c["password"],
        database="reference_data",
        connect_timeout=15,
    )
    with conn.cursor() as cur:
        cur.execute("SET SESSION TRANSACTION READ ONLY")
    return conn


def _parse_simple_array(v) -> list[str]:
    """TypeORM `simple-array` text ('spot,usdt_future') -> ['spot','usdt_future']."""
    if not v:
        return []
    return [s.strip() for s in str(v).split(",") if s.strip()]


def _fetch_exchange(cur, name: str) -> dict | None:
    """account_exchange row by name (active) -> {id, products}. None if unknown."""
    cur.execute(
        "SELECT id, products FROM account_exchange "
        "WHERE name = %s AND deletedAt IS NULL ORDER BY id LIMIT 1",
        (name,),
    )
    r = cur.fetchone()
    if not r:
        return None
    return {"id": int(r[0]), "products": _parse_simple_array(r[1])}


def _fetch_broker(cur, name: str) -> dict | None:
    """account_broker row by name (active) -> {id}. None if unknown."""
    cur.execute(
        "SELECT id FROM account_broker "
        "WHERE name = %s AND deletedAt IS NULL ORDER BY id LIMIT 1",
        (name,),
    )
    r = cur.fetchone()
    return {"id": int(r[0])} if r else None


def _fetch_wallet(cur, name: str) -> dict | None:
    """account_wallet row by name (active) -> {id, chains}. None if unknown.

    The per-chain sub-account comes from the wallet's `deposits` JSON array
    (each entry's `chain`), exactly as T2X derives wallet account ids
    (vault.service.ts: generateTradingAccountId(aw.id, 'wallet', d["chain"])).
    """
    cur.execute(
        "SELECT id, deposits FROM account_wallet "
        "WHERE name = %s AND deletedAt IS NULL ORDER BY id LIMIT 1",
        (name,),
    )
    r = cur.fetchone()
    if not r:
        return None
    chains: list[str] = []
    dep = r[1]
    if dep:
        try:
            arr = dep if isinstance(dep, list) else json.loads(dep)
            if isinstance(arr, list):
                chains = [
                    str(d["chain"]).strip()
                    for d in arr
                    if isinstance(d, dict) and d.get("chain")
                ]
        except (ValueError, TypeError):
            pass
    return {"id": int(r[0]), "chains": chains}


def resolve_account_id(
    cur, name: str, account_type: str | None = None, suffix: str | None = None
) -> str | None:
    """Account NAME (+ type and product/chain) -> gateway account_id string.

    `account_type` is 'exchange' | 'wallet' | 'broker'; when omitted it is
    inferred by looking the name up across the three account tables (exchange,
    then broker, then wallet).

    `suffix` is the sub-account selector whose meaning depends on the type:
      * exchange -> the PRODUCT (e.g. 'spot', 'usdt_future'); validated against
                    the account's `products`.
      * wallet   -> the CHAIN (e.g. 'ethereum', 'solana'); validated against the
                    wallet's deposit chains.
      * broker   -> ignored; always 'trading' (suffix 201).

    Returns e.g. '3001' (spot) or '3002' (usdt perp) or None if the name is
    unknown, the product/chain is missing, or it isn't valid for the account /
    the rule (see gateway_rule.GATEWAY_ACCOUNT_ID_RULE).
    """
    if not name:
        return None
    name = name.strip()
    # trades_* store the account as "<name>_<PRODUCT>" (e.g. "ECT001@BINANCE_SPOT")
    # but account_exchange.name is the bare name. Strip the trailing "_<suffix>"
    # so the DB lookup matches whether we're handed the bare or the suffixed name.
    if suffix and name.upper().endswith("_" + str(suffix).strip().upper()):
        name = name[: -(len(str(suffix).strip()) + 1)]
    at = (account_type or "").strip().lower() or None

    if at == "exchange":
        row = _fetch_exchange(cur, name)
    elif at == "broker":
        row = _fetch_broker(cur, name)
    elif at == "wallet":
        row = _fetch_wallet(cur, name)
    else:  # infer from whichever table the name lives in
        row = _fetch_exchange(cur, name)
        at = "exchange"
        if row is None:
            row, at = _fetch_broker(cur, name), "broker"
        if row is None:
            row, at = _fetch_wallet(cur, name), "wallet"
    if row is None:
        return None

    if at == "broker":
        suffix_raw = "trading"
    else:
        suffix_raw = (suffix or "").strip()
        if not suffix_raw:
            return None
        allowed = row.get("products") if at == "exchange" else row.get("chains")
        # Only enforce membership when the account actually lists options; an
        # empty column means "unknown", so fall through to the rule (which still
        # rejects an unmapped product/chain via a None result).
        if allowed and suffix_raw.lower() not in [a.lower() for a in allowed]:
            return None

    acct = gateway_rule.generate_trading_account_id(
        row["id"], at, suffix_raw, _rule_codes(cur)
    )
    return str(acct) if acct is not None else None
