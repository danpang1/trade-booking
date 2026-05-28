"""One-off: retag every live trades_loan row whose counterparty matches
Binance to loan_type='VIP LOAN'. Uses the SCD2 amend pattern from
loan_amend.py (end the current row, insert a new version), so history
is preserved and the audit trail in Loan Enquiry stays correct.

Dry-run by default — lists the matched rows and what they'd become.
Pass --commit to actually perform the retag.
"""
from __future__ import annotations
import sys

import loan_db

COUNTERPARTY_PATTERN = "BINANCE INVESTMENTS%"
TARGET_LOAN_TYPE = "VIP LOAN"
RETAG_USER = "bulk-retag-binance-vip"


def main() -> int:
    commit = "--commit" in sys.argv[1:]
    conn = loan_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM trades_loan "
                    " WHERE effective_end IS NULL "
                    "   AND counterparty ILIKE %s "
                    " ORDER BY deal_ref",
                    (COUNTERPARTY_PATTERN,),
                )
                cols = [d.name for d in cur.description]
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]

                eligible = [r for r in rows if r["loan_type"] != TARGET_LOAN_TYPE]
                already = [r for r in rows if r["loan_type"] == TARGET_LOAN_TYPE]

                print(f"Matched {len(rows)} live row(s) where counterparty ILIKE '{COUNTERPARTY_PATTERN}'")
                print(f"  → {len(already)} already tagged {TARGET_LOAN_TYPE} (skip)")
                print(f"  → {len(eligible)} to be retagged")
                print()
                for r in rows:
                    marker = "SKIP" if r["loan_type"] == TARGET_LOAN_TYPE else "RETAG"
                    print(
                        f"  [{marker}] {r['deal_ref']:>14} | {r['counterparty']:<35} | "
                        f"{r['principal_amount']} {r['principal_asset']} | "
                        f"current type: {r['loan_type']}"
                    )
                print()

                if not commit:
                    print("Dry-run only. Pass --commit to apply.")
                    return 0
                if not eligible:
                    print("Nothing to retag.")
                    return 0

                # SCD2 amend per row: end the live version, insert a new
                # version that's byte-identical except loan_type, user_id,
                # and effective_start/end.
                data_cols = loan_db.DATA_COLUMNS
                for r in eligible:
                    cur.execute(
                        "UPDATE trades_loan SET effective_end = NOW() "
                        " WHERE deal_ref = %s AND effective_end IS NULL "
                        " RETURNING deal_ref",
                        (r["deal_ref"],),
                    )
                    if cur.fetchone() is None:
                        print(f"  [WARN] {r['deal_ref']} no live row at amend time — skipping")
                        continue
                    new_vals = []
                    for c in data_cols:
                        if c == "loan_type":
                            new_vals.append(TARGET_LOAN_TYPE)
                        elif c == "user_id":
                            new_vals.append(RETAG_USER)
                        else:
                            new_vals.append(r[c])
                    col_list = ", ".join(data_cols + ("effective_start", "effective_end"))
                    placeholders = ", ".join(["%s"] * len(data_cols)) + ", NOW(), NULL"
                    cur.execute(
                        f"INSERT INTO trades_loan ({col_list}) "
                        f"VALUES ({placeholders})",
                        new_vals,
                    )
                    print(f"  [OK]   {r['deal_ref']} retagged {r['loan_type']} → {TARGET_LOAN_TYPE}")
        print()
        print(f"Done. Retagged {len(eligible)} row(s).")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
