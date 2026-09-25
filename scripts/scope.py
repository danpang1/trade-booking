"""Portfolio scoping for the scripts server.js spawns.

server.js decides WHO the caller is and WHICH portfolios they may touch, then
puts the answer in the stdin JSON as `_scope`. This module is the other half:
it turns that into a SQL predicate for reads and a check for writes.

The contract, and why it is shaped this way:

  `_scope` ABSENT   -> no filter. An admin, or a route that discloses nothing
                       portfolio-specific. server.js only ever omits it
                       deliberately.
  `_scope` PRESENT  -> the COMPLETE set of portfolios this caller may touch.
                       An empty list is legal and means "nothing": the caller
                       is a real user who happens to own no book.

An empty list must therefore filter everything OUT, not fall through to
unfiltered -- the usual `if not scope:` reflex is exactly backwards here and
would hand a portfolio-less user the whole firm.
"""
from __future__ import annotations


class ScopeError(Exception):
    """A write naming a portfolio outside the caller's scope."""


def read_scope(params: dict):
    """`None` (unfiltered) or the list of portfolio ids as TEXT.

    `portfolio_id` is TEXT in trades_cashflow / trades_loan / trades_spot and
    holds the portfolio NUMBER, so the scope is compared as text.
    """
    if "_scope" not in params or params["_scope"] is None:
        return None
    raw = params["_scope"]
    if not isinstance(raw, (list, tuple, set)):
        raise ScopeError("_scope must be a list of portfolio numbers")
    return [str(n).strip() for n in raw]


def where_clause(scope, column: str = "portfolio_id", alias: str = ""):
    """`(sql_fragment, args)` to AND into a query. `("", [])` when unfiltered."""
    if scope is None:
        return ("", [])
    col = f"{alias}.{column}" if alias else column
    return (f" AND {col} = ANY(%s) ", [scope])


def allows(scope, portfolio_id) -> bool:
    """True if this portfolio is inside the caller's scope."""
    if scope is None:
        return True
    if portfolio_id is None:
        return False
    return str(portfolio_id).strip() in scope


def check_write(scope, portfolio_id, what: str = "portfolio") -> None:
    """Raise ScopeError unless the caller may write this portfolio."""
    if not allows(scope, portfolio_id):
        raise ScopeError(
            f"{what} {portfolio_id} is outside your portfolios"
        )


def _pid(leg, key):
    v = (leg or {}).get(key)
    return None if v is None else str(v).strip()


def check_insert_legs(scope, legs) -> None:
    """Gate a multi-leg insert, exempting the mirror leg of a transfer.

    The plain rule -- every leg in scope -- breaks the one operation that is
    SUPPOSED to cross a boundary. An INTER PTF FUNDING is two legs, one per
    portfolio, and the whole point is that the far side is someone else's
    book: Francis moving cash from 8041 to 8888 must be able to write the
    8888 leg or the transfer does not balance.

    So a leg outside the caller's scope is allowed only as the exact mirror
    of a leg that IS in scope -- its portfolio is that leg's counterparty and
    its counterparty is that leg's portfolio. That pairing is read from the
    payload itself, never from `_meta.mirror_leg`, which the client sends and
    could therefore set on anything.

    What this does and does not concede: a caller can create a row in a book
    they cannot see, but only as the balancing half of a movement out of
    their own, and they still cannot read it back. A lone leg in someone
    else's portfolio, with nothing of theirs opposite it, stays refused.
    """
    if scope is None:
        return
    legs = [leg for leg in legs if isinstance(leg, dict)]
    inside = [leg for leg in legs if allows(scope, leg.get("portfolio_id"))]
    outside = [leg for leg in legs if not allows(scope, leg.get("portfolio_id"))]
    if not outside:
        return
    if not inside:
        raise ScopeError(
            f"portfolio {_pid(outside[0], 'portfolio_id')} is outside your "
            f"portfolios"
        )
    for leg in outside:
        partner = next(
            (
                p for p in inside
                if _pid(p, "counterparty") == _pid(leg, "portfolio_id")
                and _pid(leg, "counterparty") == _pid(p, "portfolio_id")
                and _pid(leg, "portfolio_id") is not None
            ),
            None,
        )
        if partner is None:
            raise ScopeError(
                f"portfolio {_pid(leg, 'portfolio_id')} is outside your "
                f"portfolios, and this leg is not the mirror of one that is"
            )


def refusal(e) -> dict:
    """The JSON a script prints when a write falls outside the caller's scope.

    `code` maps to HTTP 403 in server.js httpStatusFor -- a scope violation is
    a refusal, not a malformed request, and the difference matters when the
    front end decides whether to show a validation error or a permission one.
    """
    return {"ok": False, "error": str(e), "code": "forbidden"}


def narrow_requested(scope, requested):
    """Intersect a caller-supplied portfolio filter with their scope.

    An unfiltered caller keeps whatever they asked for. A scoped caller who
    asked for nothing in particular gets their whole scope; one who named
    portfolios gets only the named ones they actually own.

    The result can be empty, and an empty result from a SCOPED caller means
    "no rows" -- never "no filter". Both export scripts build their SQL as
    `if params["portfolio_ids"]: ... IN (...)`, so handing them an empty list
    would widen the export to the whole firm. Callers must check
    `is_empty_scope()` and emit an empty result instead.
    """
    if scope is None:
        return list(requested or [])
    if requested:
        return [p for p in requested if p in scope]
    return list(scope)


def is_empty_scope(scope, narrowed) -> bool:
    """True when a scoped caller is left with no portfolios at all."""
    return scope is not None and not narrowed


def check_amend(scope, existing_portfolio_id, incoming_portfolio_id) -> None:
    """Both ends of an amend must be in scope.

    An amend addresses a row by deal_ref, so checking one end is not enough:

      - checking only the incoming value lets a caller pull someone else's
        deal into their own book;
      - checking only the existing value lets a caller push their own deal
        out to a portfolio they cannot see.

    `incoming_portfolio_id` may be None when the amend does not restate the
    portfolio, in which case only the existing row is checked.
    """
    check_write(scope, existing_portfolio_id, "the deal's portfolio")
    if incoming_portfolio_id is not None:
        check_write(scope, incoming_portfolio_id, "target portfolio")
