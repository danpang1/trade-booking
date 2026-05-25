"""Fetch all live loans (with mappings + schedule_comments) for the CSV
export modal in LoanEnquiry.

Returns the full set — no LIMIT — so the frontend can build a complete
loan-schedule CSV. Mirrors `loan_recent.py` but accepts optional
date and portfolio filters and skips the row cap.

Reads `{"from": "...", "to": "...", "portfolio_ids": [...]}` from stdin
(all optional). Writes {"ok": true, "rows": [...]} to stdout.

Exit codes match the export_blotter convention:
    0 success, 2 invalid JSON, 3 bad params, 5 DB error.

Manual smoke:
    echo '{}' | python3 trade-booking/scripts/loan_export.py
    echo '{"portfolio_ids":["8041"]}' | python3 trade-booking/scripts/loan_export.py
"""
from __future__ import annotations
import json
import sys

import loan_db
import loan_cashflow_map_db
import loan_schedule_comments_db


def _parse_params(raw: str) -> dict:
    params = json.loads(raw or "{}")
    if not isinstance(params, dict):
        raise ValueError("stdin must be a JSON object")
    out = {
        "from": params.get("from") or None,
        "to": params.get("to") or None,
        "portfolio_ids": params.get("portfolio_ids") or [],
    }
    if not isinstance(out["portfolio_ids"], list):
        raise ValueError("portfolio_ids must be a list of strings")
    out["portfolio_ids"] = [str(p) for p in out["portfolio_ids"] if str(p).strip()]
    return out


def _where_and_args(params: dict) -> tuple[str, list]:
    clauses = ["t.effective_end IS NULL"]
    args: list = []
    if params["from"]:
        clauses.append("t.trade_date >= %s")
        args.append(params["from"])
    if params["to"]:
        clauses.append("t.trade_date <= %s")
        args.append(params["to"])
    if params["portfolio_ids"]:
        placeholders = ",".join(["%s"] * len(params["portfolio_ids"]))
        clauses.append(f"t.portfolio_id IN ({placeholders})")
        args.extend(params["portfolio_ids"])
    return " AND ".join(clauses), args


def main() -> int:
    raw = sys.stdin.read().strip()
    try:
        params = _parse_params(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": "invalid JSON on stdin", "detail": str(e)}))
        return 2
    except ValueError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 3

    where, args = _where_and_args(params)
    sql = (
        "SELECT t.*, "
        "       (SELECT MIN(effective_start) FROM trades_loan "
        "         WHERE deal_ref = t.deal_ref) AS first_effective_start, "
        f"      {loan_cashflow_map_db.LOAN_MAPPINGS_JSON_AGG}, "
        f"      {loan_schedule_comments_db.LOAN_SCHEDULE_COMMENTS_JSON_AGG} "
        "  FROM trades_loan t "
        "  LEFT JOIN loan_cashflow_map m ON m.loan_deal_ref = t.deal_ref "
        "  LEFT JOIN trades_cashflow cf "
        "         ON cf.deal_ref = m.cashflow_deal_ref "
        "        AND cf.effective_end IS NULL AND cf.status <> 'CANCELLED' "
        f" WHERE {where} "
        " GROUP BY t.deal_ref, t.effective_start "
        " ORDER BY t.trade_date DESC, t.deal_ref DESC"
    )

    conn = loan_db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            cols = [d.name for d in cur.description]
            rows = [loan_db.row_to_payload(cols, r) for r in cur.fetchall()]
        print(json.dumps({"ok": True, "rows": rows}))
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
