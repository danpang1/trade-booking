"""mapping_type follows the direction of the cash against the loan.

A PRINCIPAL_DISBURSE is principal moving from lender to borrower, a
PRINCIPAL_REPAY the reverse -- regardless of what the cashflow row was
labelled. On a BORROW our incoming cash is the disbursement; on a LEND
our outgoing cash is. Deriving from the label alone filed a lend booked
as "LOAN REPAYMENT OUTGOING" as a repayment (MLA00000459, 2026-09-29),
and its balance came out with the wrong sign.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import loan_cashflow_map_db as lcm  # noqa: E402


@pytest.mark.parametrize("cf_type,cf_dir,loan_dir,want", [
    # BORROW: money in is the disbursement, money out the repayment.
    ("LOAN", "INCOMING", "BORROW", "PRINCIPAL_DISBURSE"),
    ("LOAN REPAYMENT", "OUTGOING", "BORROW", "PRINCIPAL_REPAY"),
    # LEND: the mirror image. The label does not get a vote.
    ("LOAN", "OUTGOING", "LEND", "PRINCIPAL_DISBURSE"),
    ("LOAN REPAYMENT", "OUTGOING", "LEND", "PRINCIPAL_DISBURSE"),
    ("LOAN", "INCOMING", "LEND", "PRINCIPAL_REPAY"),
    ("LOAN REPAYMENT", "INCOMING", "LEND", "PRINCIPAL_REPAY"),
    # A mislabelled BORROW is corrected the same way.
    ("LOAN REPAYMENT", "INCOMING", "BORROW", "PRINCIPAL_DISBURSE"),
])
def test_principal_follows_cash_direction_against_loan(cf_type, cf_dir, loan_dir, want):
    assert lcm.derive_mapping_type(cf_type, cf_dir, loan_direction=loan_dir) == want


@pytest.mark.parametrize("cf_type,cf_dir,want", [
    ("LOAN", "INCOMING", "PRINCIPAL_DISBURSE"),
    ("LOAN REPAYMENT", "OUTGOING", "PRINCIPAL_REPAY"),
    ("LOAN", None, "PRINCIPAL_DISBURSE"),
])
def test_without_loan_direction_falls_back_to_the_label(cf_type, cf_dir, want):
    assert lcm.derive_mapping_type(cf_type, cf_dir) == want
    assert lcm.derive_mapping_type(cf_type, cf_dir, loan_direction=None) == want


def test_interest_and_unknown_types_unchanged():
    for d in ("BORROW", "LEND", None):
        assert lcm.derive_mapping_type("INTEREST EXPENSE", "OUTGOING", loan_direction=d) == "INTEREST"
        assert lcm.derive_mapping_type("INTEREST INCOME", "INCOMING", loan_direction=d) == "INTEREST"
        assert lcm.derive_mapping_type("OPEX", "OUTGOING", loan_direction=d) is None
        assert lcm.derive_mapping_type(None, None, loan_direction=d) is None


def test_case_insensitive():
    assert lcm.derive_mapping_type("loan", "outgoing", loan_direction="lend") == "PRINCIPAL_DISBURSE"
