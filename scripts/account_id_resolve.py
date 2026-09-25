"""Resolve a booking's gateway `account_id`, for storage on the trade row.

`account_id` used to be computed only when mirroring into the tech DB, and
recomputed from scratch each time. Storing it on the trade makes it a fact of
the booking: re-deriving it later silently changes answer if the account is
renamed, deactivated, or the gateway rule is amended.

TWO CALLERS, ONE RULE:
  * the insert/amend scripts, via `resolve()`, to stamp the column
  * the booking form, via `main()` on stdin/stdout, to show what will be stored

NEVER RAISES, NEVER BLOCKS A BOOKING. T2X being unreachable, or an account the
gateway rule has no code for (REYA, STARKNET, FUTURES2, FUTURES3 as of
2026-09-25), yields None and the column stays NULL. A trade must not fail
because a mirror-id lookup timed out -- same posture as the manual dual-write.

Manual smoke:
    echo '{"account":"ECT001@BINANCE","account_type":"EXCHANGE","product":"spot"}' \\
      | python3 trade-booking/scripts/account_id_resolve.py
"""
from __future__ import annotations
import json
import sys

# `account_type` on a booking is the venue-type label the form uses
# (EXCHANGE / WALLET / BROKER / BANK). The gateway rule keys on the lowercase
# T2X account-table name, and BANK has no gateway account at all.
_TYPE_MAP = {
    "EXCHANGE": "exchange",
    "WALLET": "wallet",
    "BROKER": "broker",
}


def _log(msg: str) -> None:
    print(f"account_id: {msg}", file=sys.stderr)


def resolve(account, account_type, product):
    """Gateway account_id as a string, or None.

    None covers every failure: no account, a type with no gateway account
    (BANK), a product/chain the rule has no code for, T2X unreachable, or the
    driver missing. The caller stores NULL and carries on.
    """
    if not account:
        return None
    at = _TYPE_MAP.get(str(account_type or "").strip().upper())
    if at is None:
        return None
    try:
        import t2x_mysql

        with t2x_mysql.connect() as conn:
            return t2x_mysql.resolve_account_id(
                conn.cursor(), account, at, product
            )
    except Exception as e:  # noqa: BLE001
        # Loud but harmless: spawnPython captures stderr into Grafana, so an
        # unresolvable account is searchable rather than merely absent.
        _log(
            f"could not resolve account={account!r} type={account_type!r} "
            f"product={product!r}: {e!r}"
        )
        return None


def reverse(account_id):
    """Gateway account_id -> {account, account_type, product}, or None.

    The inverse of `resolve`, for the bulk editor: a user pastes an id and the
    account and product fill themselves in.

    The code alone is AMBIGUOUS -- 001 is both `spot` and `trading`, 002 both
    `futures` and `usdt_future`. It is disambiguated by the account's own
    products/chains list, which resolves it cleanly: across all 219 exchange
    accounts and 443 wallets in T2X, no account lists both halves of a
    colliding pair.

    Should that ever stop being true, the round-trip check at the end catches
    it: whatever comes back must forward-resolve to the id we were given, or
    this returns None. A refusal is recoverable; a wrong product silently
    attached to a trade is not.
    """
    s = str(account_id or "").strip()
    if not s.isdigit() or len(s) <= 3:
        return None
    code, row_id = s[-3:], int(s[:-3])

    try:
        import gateway_rule
        import t2x_mysql

        with t2x_mysql.connect() as conn:
            cur = conn.cursor()
            codes = t2x_mysql._rule_codes(cur)
            # Every {account_type}-{suffix} key sharing this 3-digit code.
            keys = [k for k, v in codes.items() if v == code]
            if not keys:
                return None
            for key in keys:
                at, _, suffix = key.partition("-")
                row = _fetch_by_id(cur, at, row_id)
                if row is None:
                    continue
                # Match the account's own options against the key's suffix
                # THROUGH the aliases: a wallet lists "BINANCE SMART CHAIN"
                # but the rule keys it as `wallet-bsc`, so a literal compare
                # would reject a perfectly valid chain.
                product = _option_for_suffix(row.get("options"), suffix)
                # Broker has no sub-account choice; its suffix is fixed.
                if at != "broker" and (row.get("options") or []) and product is None:
                    continue
                if product is None:
                    product = suffix
                # Round-trip: the answer must rebuild the id it came from.
                back = gateway_rule.generate_trading_account_id(
                    row_id, at, product or suffix, codes
                )
                if back is None or str(back) != s:
                    continue
                return {
                    "account": row["name"],
                    "account_type": at.upper(),
                    "product": None if at == "broker" else product,
                }
        return None
    except Exception as e:  # noqa: BLE001
        _log(f"could not reverse account_id={account_id!r}: {e!r}")
        return None


def _option_for_suffix(options, suffix):
    """The account's own spelling of `suffix`, or None if it offers no match.

    Compared through gateway_rule._SUFFIX_ALIASES so a display name maps to
    the short form the rule keys on ("BINANCE SMART CHAIN" -> bsc).
    """
    import gateway_rule

    want = str(suffix).strip().lower()
    for o in options or []:
        raw = str(o)
        alias = gateway_rule._SUFFIX_ALIASES.get(raw, raw)
        if raw.strip().lower() == want or str(alias).strip().lower() == want:
            return raw
    return None


def _fetch_by_id(cur, account_type, row_id):
    """{name, options} for a row id in the account table `account_type` names.

    `options` is the sub-account list the gateway suffix must belong to:
    `products` for an exchange, deposit chains for a wallet, nothing for a
    broker. Kept here rather than in t2x_mysql because that module looks
    accounts up by NAME; this is the only by-id path.
    """
    import json

    if account_type == "exchange":
        cur.execute(
            "SELECT name, products FROM account_exchange "
            " WHERE id = %s AND deletedAt IS NULL", (row_id,)
        )
        r = cur.fetchone()
        if not r:
            return None
        opts = [p.strip() for p in str(r[1] or "").split(",") if p.strip()]
        return {"name": r[0], "options": opts}

    if account_type == "broker":
        cur.execute(
            "SELECT name FROM account_broker "
            " WHERE id = %s AND deletedAt IS NULL", (row_id,)
        )
        r = cur.fetchone()
        return {"name": r[0], "options": []} if r else None

    if account_type == "wallet":
        cur.execute(
            "SELECT name, deposits FROM account_wallet "
            " WHERE id = %s AND deletedAt IS NULL", (row_id,)
        )
        r = cur.fetchone()
        if not r:
            return None
        try:
            arr = r[1] if isinstance(r[1], list) else json.loads(r[1] or "[]")
        except (ValueError, TypeError):
            arr = []
        seen, opts = set(), []
        for d in arr or []:
            ch = (d or {}).get("chain")
            if ch and ch not in seen:
                seen.add(ch)
                opts.append(ch)
        return {"name": r[0], "options": opts}

    return None


def stamp(payload: dict) -> None:
    """Set `payload['account_id']` in place, for a single booking leg.

    An account_id already on the payload is overwritten: the row's account and
    product are the truth, not whatever a client sent.
    """
    if not isinstance(payload, dict):
        return
    payload["account_id"] = resolve(
        payload.get("account"),
        payload.get("account_type"),
        payload.get("product"),
    )


def stamp_all(payload) -> None:
    """`stamp` every leg, whether the payload is one dict or a list of them."""
    for leg in (payload if isinstance(payload, list) else [payload]):
        stamp(leg)


def main() -> int:
    raw = sys.stdin.read().strip() or "{}"
    try:
        params = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": "invalid JSON on stdin",
                          "detail": str(e)}))
        return 2
    # Reverse mode: {"account_id": "3001"} -> account + product.
    if params.get("account_id") and not params.get("account"):
        hit = reverse(params.get("account_id"))
        print(json.dumps({"ok": True, "resolved": hit}))
        return 0
    account_id = resolve(
        params.get("account"),
        params.get("account_type"),
        params.get("product"),
    )
    print(json.dumps({"ok": True, "account_id": account_id}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
