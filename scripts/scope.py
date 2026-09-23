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
