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
    account_id = resolve(
        params.get("account"),
        params.get("account_type"),
        params.get("product"),
    )
    print(json.dumps({"ok": True, "account_id": account_id}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
