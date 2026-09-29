"""Re-derive PRINCIPAL_DISBURSE / PRINCIPAL_REPAY on loan_cashflow_map from
the loan's direction, and report (or apply) the rows that change.

Until 2026-09-29 the mapping type came from the cashflow's label alone:
LOAN -> DISBURSE, LOAN REPAYMENT -> REPAY. That is the borrower's view.
On a LEND the money we pay OUT is the disbursement whatever the row is
labelled, so a lend booked as "LOAN REPAYMENT OUTGOING" was filed as a
repayment and its balance came out negative -- and the LEND sign flip in
the UI then showed it as money owed TO us with the wrong sign. The
derivation now reads the direction of the cash against the direction
of the loan (loan_cashflow_map_db.derive_mapping_type); this script
brings existing rows in line with it.

    python fix_principal_mapping_types.py           # dry run: list changes
    python fix_principal_mapping_types.py --apply   # write them
    python fix_principal_mapping_types.py --sql     # print the UPDATEs only

Idempotent. Only principal-typed cashflows (LOAN / LOAN REPAYMENT) on
live loans are considered; INTEREST and untyped mappings are untouched.
"""
from __future__ import annotations
import sys

import cashflow_db
import loan_cashflow_map_db as lcm


QUERY = """
SELECT m.loan_deal_ref, m.cashflow_deal_ref, m.mapping_type,
       l.direction AS loan_direction,
       cf.cashflow_type, cf.direction AS cf_direction, cf.amount
  FROM loan_cashflow_map m
  JOIN trades_loan l
    ON l.deal_ref = m.loan_deal_ref AND l.effective_end IS NULL
  JOIN trades_cashflow cf
    ON cf.deal_ref = m.cashflow_deal_ref AND cf.effective_end IS NULL
 WHERE cf.cashflow_type IN ('LOAN', 'LOAN REPAYMENT')
 ORDER BY m.loan_deal_ref, m.cashflow_deal_ref
"""


def plan(cur) -> list[dict]:
    cur.execute(QUERY)
    out = []
    for loan_ref, cf_ref, stored, loan_dir, cf_type, cf_dir, amount in cur.fetchall():
        want = lcm.derive_mapping_type(cf_type, cf_dir, loan_direction=loan_dir)
        if want != stored:
            out.append({
                "loan_deal_ref": loan_ref, "cashflow_deal_ref": cf_ref,
                "loan_direction": loan_dir, "cashflow_type": cf_type,
                "cf_direction": cf_dir, "amount": amount,
                "stored": stored, "want": want,
            })
    return out


def as_sql(changes: list[dict]) -> str:
    lines = []
    for c in changes:
        lines.append(
            f"UPDATE loan_cashflow_map SET mapping_type = '{c['want']}' "
            f"WHERE loan_deal_ref = '{c['loan_deal_ref']}' "
            f"AND cashflow_deal_ref = '{c['cashflow_deal_ref']}' "
            f"AND mapping_type = '{c['stored']}';"
        )
    return "\n".join(lines)


def main(argv) -> int:
    apply = "--apply" in argv
    conn = cashflow_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                changes = plan(cur)
                if "--sql" in argv:
                    print(as_sql(changes) or "-- nothing to change")
                    return 0
                if not changes:
                    print("all principal mappings already follow the loan direction")
                    return 0
                for c in changes:
                    print(
                        f"{c['loan_deal_ref']} ({c['loan_direction']}) <- "
                        f"{c['cashflow_deal_ref']} {c['cashflow_type']} {c['cf_direction']} "
                        f"{c['amount']}: {c['stored']} -> {c['want']}"
                    )
                if not apply:
                    print(f"\n{len(changes)} row(s) would change; re-run with --apply")
                    return 0
                for c in changes:
                    cur.execute(
                        "UPDATE loan_cashflow_map SET mapping_type = %s "
                        " WHERE loan_deal_ref = %s AND cashflow_deal_ref = %s",
                        (c["want"], c["loan_deal_ref"], c["cashflow_deal_ref"]),
                    )
                print(f"\napplied {len(changes)} row(s)")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
