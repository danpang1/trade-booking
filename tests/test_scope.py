"""Tests for trade-booking/scripts/scope.py.

The empty-scope case and the both-ends amend rule are the two that decide
whether this control actually holds, so they get the most attention.
"""
from pathlib import Path
import sys

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import scope  # noqa: E402


# ── read_scope ────────────────────────────────────────────────────────

def test_absent_scope_means_unfiltered():
    assert scope.read_scope({}) is None
    assert scope.read_scope({"_scope": None}) is None


def test_scope_is_normalised_to_text():
    assert scope.read_scope({"_scope": [8041, "8043 "]}) == ["8041", "8043"]


def test_an_empty_scope_is_a_real_empty_list_not_none():
    """The distinction the whole module turns on: [] filters everything out,
    None filters nothing. Collapsing them hands a portfolio-less user the
    entire firm."""
    assert scope.read_scope({"_scope": []}) == []
    assert scope.read_scope({"_scope": []}) is not None


def test_a_non_list_scope_is_rejected():
    with pytest.raises(scope.ScopeError):
        scope.read_scope({"_scope": "8041"})


# ── where_clause ──────────────────────────────────────────────────────

def test_unfiltered_adds_no_sql():
    assert scope.where_clause(None) == ("", [])


def test_scoped_adds_an_any_predicate():
    sql, args = scope.where_clause(["8041"])
    assert "portfolio_id = ANY(%s)" in sql
    assert args == [["8041"]]


def test_alias_is_applied():
    sql, _ = scope.where_clause(["8041"], alias="t")
    assert "t.portfolio_id = ANY(%s)" in sql


def test_an_empty_scope_still_produces_a_predicate():
    """ANY('{}') matches nothing, which is the point."""
    sql, args = scope.where_clause([])
    assert "ANY(%s)" in sql
    assert args == [[]]


# ── allows / check_write ──────────────────────────────────────────────

def test_unfiltered_allows_everything():
    assert scope.allows(None, "8041") is True
    assert scope.allows(None, None) is True


def test_in_scope_is_allowed_and_out_of_scope_is_not():
    assert scope.allows(["8041", "8043"], "8041") is True
    assert scope.allows(["8041", "8043"], 8041) is True
    assert scope.allows(["8041", "8043"], "8888") is False


def test_a_null_portfolio_is_never_in_scope():
    assert scope.allows(["8041"], None) is False


def test_an_empty_scope_allows_nothing():
    assert scope.allows([], "8041") is False


def test_check_write_raises_out_of_scope():
    with pytest.raises(scope.ScopeError, match="8888"):
        scope.check_write(["8041"], "8888")
    scope.check_write(["8041"], "8041")  # no raise


# ── check_amend: both ends ────────────────────────────────────────────

def test_amend_within_scope_is_allowed():
    scope.check_amend(["8041", "8043"], "8041", "8043")


def test_amend_cannot_pull_a_deal_into_scope():
    """Existing row belongs to 8888, caller owns 8041 — claiming it is a
    disclosure, not an edit."""
    with pytest.raises(scope.ScopeError):
        scope.check_amend(["8041"], "8888", "8041")


def test_amend_cannot_push_a_deal_out_of_scope():
    """Caller owns the row but tries to move it somewhere they cannot see."""
    with pytest.raises(scope.ScopeError):
        scope.check_amend(["8041"], "8041", "8888")


def test_amend_without_a_restated_portfolio_checks_only_the_existing_row():
    scope.check_amend(["8041"], "8041", None)
    with pytest.raises(scope.ScopeError):
        scope.check_amend(["8041"], "8888", None)


def test_amend_is_unrestricted_when_unfiltered():
    scope.check_amend(None, "8888", "9999")


# ── check_insert_legs: the INTER PTF FUNDING mirror ───────────────────

def leg(ptf, cpty):
    return {"portfolio_id": ptf, "counterparty": cpty,
            "cashflow_type": "INTER PTF FUNDING"}


def test_a_single_leg_in_scope_is_allowed():
    scope.check_insert_legs(["8041"], [leg(8041, "8888")])


def test_the_mirror_leg_of_an_owned_transfer_is_allowed():
    """Francis owns 8041 only. Moving cash 8041 -> 8888 writes a leg in 8888,
    and must be able to, or the transfer does not balance."""
    scope.check_insert_legs(["8041"], [leg(8041, "8888"), leg(8888, "8041")])


def test_the_mirror_is_allowed_in_either_order():
    scope.check_insert_legs(["8041"], [leg(8888, "8041"), leg(8041, "8888")])


def test_a_lone_leg_in_someone_elses_book_is_refused():
    """Nothing of the caller's opposite it — that is not a transfer, it is
    writing into a book they do not own."""
    with pytest.raises(scope.ScopeError):
        scope.check_insert_legs(["8041"], [leg(8888, "8041")])


def test_a_third_portfolio_riding_along_is_refused():
    """Two legs pair off; the third is not the mirror of anything owned."""
    with pytest.raises(scope.ScopeError, match="not the mirror"):
        scope.check_insert_legs(
            ["8041"], [leg(8041, "8888"), leg(8888, "8041"), leg(9999, "8041")])


def test_a_mismatched_pair_is_refused():
    """The far leg names 8041 as its counterparty but the near leg points at
    9999 — they are not two halves of the same movement."""
    with pytest.raises(scope.ScopeError):
        scope.check_insert_legs(["8041"], [leg(8041, "9999"), leg(8888, "8041")])


def test_the_pairing_is_read_from_the_payload_not_from_meta():
    """_meta.mirror_leg is client-supplied. A caller who stamps it on a lone
    foreign leg gains nothing, because it is never consulted."""
    forged = leg(8888, "8041")
    forged["_meta"] = {"mirror": True, "mirror_leg": 2}
    with pytest.raises(scope.ScopeError):
        scope.check_insert_legs(["8041"], [forged])


def test_numeric_and_string_portfolio_ids_pair_the_same():
    scope.check_insert_legs(["8041"], [leg("8041", 8888), leg(8888, "8041")])


def test_an_unfiltered_caller_may_book_anything():
    scope.check_insert_legs(None, [leg(8888, "9999")])


def test_an_empty_scope_cannot_ride_a_mirror():
    with pytest.raises(scope.ScopeError):
        scope.check_insert_legs([], [leg(8041, "8888"), leg(8888, "8041")])
