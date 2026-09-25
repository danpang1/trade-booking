"""Gateway account_id rule — faithful Python port of T2X's gateway.rule.ts.

Source of truth: t2x-backend-service
  libs/common/src/gateway-rule/gateway.rule.ts

The trading/gateway `account_id` is `{T2X_ID}{suffix}` (string concat, then int),
where `T2X_ID` is the row id of the account_exchange / account_wallet /
account_broker record and the 3-digit suffix encodes account category + product
(exchange) / chain (wallet) / fixed 'trading' (broker):

  * last-3 first digit 0-4  -> exchange accounts (spot=001, usdt_future=002, ...)
  * broker                  -> 201
  * last-3 first digit 5+   -> wallet accounts, keyed by chain (ethereum=501, ...)

Keep this in lockstep with gateway.rule.ts — any suffix the backend adds there
must be mirrored here, or a manual booking would compute a stale account_id.
"""
from __future__ import annotations

# Verbatim from GATEWAY_ACCOUNT_ID_RULE in gateway.rule.ts (key -> '{T2X_ID}NNN').
GATEWAY_ACCOUNT_ID_RULE: dict[str, str] = {
    "exchange-spot": "{T2X_ID}001",
    "exchange-trading": "{T2X_ID}001",
    "exchange-futures": "{T2X_ID}002",
    "exchange-usdt_future": "{T2X_ID}002",
    "exchange-coin_future": "{T2X_ID}003",
    "exchange-derivatives": "{T2X_ID}004",
    "exchange-portfolio_margin": "{T2X_ID}005",
    "exchange-funding": "{T2X_ID}006",
    "exchange-unified": "{T2X_ID}007",
    "exchange-alpha": "{T2X_ID}008",
    # Hyperliquid perps
    "exchange-futures_xyz": "{T2X_ID}009",
    "exchange-futures_flx": "{T2X_ID}010",
    "exchange-futures_km": "{T2X_ID}011",
    "exchange-futures_vntl": "{T2X_ID}012",
    "exchange-futures_cash": "{T2X_ID}013",
    "broker-trading": "{T2X_ID}201",
    "wallet-ethereum": "{T2X_ID}501",
    "wallet-bsc": "{T2X_ID}502",
    "wallet-polygon": "{T2X_ID}503",
    "wallet-avalanche": "{T2X_ID}504",
    "wallet-arbitrum": "{T2X_ID}505",
    "wallet-linea": "{T2X_ID}506",
    "wallet-base": "{T2X_ID}507",
    "wallet-zeta": "{T2X_ID}508",
    "wallet-optimism": "{T2X_ID}509",
    "wallet-zksync": "{T2X_ID}510",
    "wallet-blast": "{T2X_ID}511",
    "wallet-scroll": "{T2X_ID}512",
    "wallet-mode": "{T2X_ID}513",
    "wallet-mantle": "{T2X_ID}514",
    "wallet-celo": "{T2X_ID}515",
    "wallet-berachain": "{T2X_ID}516",
    "wallet-unichain": "{T2X_ID}517",
    "wallet-immutable": "{T2X_ID}518",
    "wallet-gnosis": "{T2X_ID}519",
    "wallet-sonic": "{T2X_ID}520",
    "wallet-hyperevm": "{T2X_ID}521",
    "wallet-peaq": "{T2X_ID}522",
    "wallet-soneium": "{T2X_ID}523",
    "wallet-xrplevm": "{T2X_ID}524",
    "wallet-plasma": "{T2X_ID}525",
    "wallet-mantra": "{T2X_ID}526",
    "wallet-sagaevm": "{T2X_ID}527",
    "wallet-citrea": "{T2X_ID}528",
    "wallet-hedera": "{T2X_ID}529",
    "wallet-tempo": "{T2X_ID}530",
    "wallet-filecoin": "{T2X_ID}531",
    "wallet-robinhood": "{T2X_ID}532",
    "wallet-kaia": "{T2X_ID}533",
    "wallet-kubchain": "{T2X_ID}534",
    "wallet-xlayer": "{T2X_ID}535",
    "wallet-ink": "{T2X_ID}536",
    "wallet-arc": "{T2X_ID}537",
    "wallet-fraxtal": "{T2X_ID}538",
    "wallet-kava": "{T2X_ID}539",
    "wallet-ton": "{T2X_ID}601",
    "wallet-chainflip": "{T2X_ID}602",
    "wallet-sui": "{T2X_ID}603",
    "wallet-aptos": "{T2X_ID}604",
    "wallet-solana": "{T2X_ID}701",
    "wallet-bitcoin": "{T2X_ID}801",
    "wallet-doge": "{T2X_ID}802",
    "wallet-cardano": "{T2X_ID}803",
    "wallet-bch": "{T2X_ID}804",
    "wallet-polkadot": "{T2X_ID}805",
    "wallet-stellar": "{T2X_ID}806",
    "wallet-canton": "{T2X_ID}807",
    "wallet-tron": "{T2X_ID}811",
    "wallet-ripple": "{T2X_ID}821",
    "wallet-hypercore": "{T2X_ID}831",
    "wallet-shadow_simulation": "{T2X_ID}999",
}

# t2x-name -> gateway-suffix aliases (verbatim from generateTradingAccountId).
_SUFFIX_ALIASES = {
    "BINANCE SMART CHAIN": "bsc",
    "BITCOIN CASH": "bch",
}

AccountType = str  # 'exchange' | 'wallet' | 'broker'

# The hardcoded rule as {key: 3-digit code} (fallback when the DB table is
# absent). Derived once from GATEWAY_ACCOUNT_ID_RULE by dropping the template.
_HARDCODED_CODES: dict[str, str] | None = None


def hardcoded_codes() -> dict[str, str]:
    """{'exchange-spot': '001', ...} from the ported constant (fallback)."""
    global _HARDCODED_CODES
    if _HARDCODED_CODES is None:
        _HARDCODED_CODES = {
            k: v.replace("{T2X_ID}", "") for k, v in GATEWAY_ACCOUNT_ID_RULE.items()
        }
    return _HARDCODED_CODES


def codes_from_rows(rows) -> dict[str, str]:
    """Build the code map from `reference_data.gateway_rule` rows.

    `rows` is an iterable of (accountType, suffix, code) tuples. Keys are
    normalised to lowercase `{accountType}-{suffix}`, matching the lookup in
    generate_trading_account_id. This is the DB source of truth for the rule.
    """
    out: dict[str, str] = {}
    for at, sfx, code in rows:
        if at and sfx and code:
            out[f"{str(at).strip().lower()}-{str(sfx).strip().lower()}"] = str(code).strip()
    return out


def generate_trading_account_id(
    t2x_id: int,
    account_type: AccountType,
    suffix_raw: str,
    codes: dict[str, str] | None = None,
) -> int | None:
    """`{T2X_ID}{code}` -> int, per the gateway rule. None on no-match.

    Faithful port of generateTradingAccountId(T2X_ID, accountType, suffixRaw):
    applies the t2x->gateway suffix aliases, lowercases the
    `{account_type}-{suffix}` key, and int-parses `f"{t2x_id}{code}"`
    (e.g. id 218 + 'spot' -> 218001). Unknown key -> None (caller skips).

    `codes` is the {key: code} map — pass the DB-loaded map
    (t2x_mysql.load_gateway_rule_codes) to use `reference_data.gateway_rule` as
    the source of truth; omitted -> the hardcoded port (fallback).
    """
    if t2x_id is None or account_type is None or suffix_raw is None:
        return None
    if codes is None:
        codes = hardcoded_codes()
    suffix = _SUFFIX_ALIASES.get(suffix_raw, suffix_raw)
    key = f"{account_type.lower()}-{suffix.lower()}"
    code = codes.get(key)
    if code is None:
        return None
    return int(f"{t2x_id}{code}")
