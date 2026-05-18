"""Helpers for the loan_schedule_comments table.

upsert_comment(): write-or-overwrite one (loan, period_start) row.
fetch_for_loan(): pull all comments for one loan as a JSON-friendly list.

Both expose a SQL fragment LOAN_SCHEDULE_COMMENTS_JSON_AGG suitable for
LEFT JOIN inside loan_get / loan_recent / loan_history queries so the
loan row carries its comments inline (matches the loan_cashflow_map
mappings JSON pattern).
"""
from __future__ import annotations
from datetime import date, datetime


class ScheduleCommentError(ValueError):
    pass


# SELECT fragment that aggregates schedule comments per loan.
# Drop into the loan_* queries' SELECT clause exactly as-is.
# trigger_cashflow_deal_ref is the stable key (immune to cashflow
# amend-driven date shifts); period_start_date is informational.
LOAN_SCHEDULE_COMMENTS_JSON_AGG = """
  COALESCE(
    (SELECT json_agg(json_build_object(
        'trigger_cashflow_deal_ref', sc.trigger_cashflow_deal_ref,
        'period_start_date', to_char(sc.period_start_date, 'YYYY-MM-DD'),
        'comment',           sc.comment,
        'user_id',           sc.user_id,
        'updated_at',        sc.updated_at
      ) ORDER BY sc.period_start_date)
       FROM loan_schedule_comments sc
      WHERE sc.loan_deal_ref = t.deal_ref),
    '[]'::json
  ) AS schedule_comments
""".strip()


def _coerce_date(value) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        s = value.strip()
        # Accept ISO date or full ISO timestamp; take first 10 chars.
        return date.fromisoformat(s[:10])
    raise ScheduleCommentError(f"unrecognized date value: {value!r}")


def upsert_comment(
    cur,
    loan_deal_ref: str,
    trigger_cashflow_deal_ref: str,
    period_start_date,
    comment: str | None,
    user_id: str,
) -> dict:
    """Insert or overwrite one schedule comment. Keyed by
    (loan_deal_ref, trigger_cashflow_deal_ref); period_start_date is
    refreshed alongside since the row may have shifted on the schedule.
    """
    if not loan_deal_ref or not loan_deal_ref.strip():
        raise ScheduleCommentError("loan_deal_ref is required")
    if not trigger_cashflow_deal_ref or not trigger_cashflow_deal_ref.strip():
        raise ScheduleCommentError("trigger_cashflow_deal_ref is required")
    if not user_id or not user_id.strip():
        raise ScheduleCommentError("user_id is required")
    psd = _coerce_date(period_start_date)
    cmt = (comment or "").strip() or None
    cur.execute(
        """
        INSERT INTO loan_schedule_comments
          (loan_deal_ref, trigger_cashflow_deal_ref,
           period_start_date, comment, user_id, updated_at)
        VALUES (%s, %s, %s, %s, %s, NOW())
        ON CONFLICT (loan_deal_ref, trigger_cashflow_deal_ref) DO UPDATE
          SET period_start_date = EXCLUDED.period_start_date,
              comment           = EXCLUDED.comment,
              user_id           = EXCLUDED.user_id,
              updated_at        = NOW()
        RETURNING loan_deal_ref,
                  trigger_cashflow_deal_ref,
                  to_char(period_start_date, 'YYYY-MM-DD') AS period_start_date,
                  comment, user_id, updated_at
        """,
        (
            loan_deal_ref.strip(),
            trigger_cashflow_deal_ref.strip(),
            psd,
            cmt,
            user_id.strip(),
        ),
    )
    row = cur.fetchone()
    return {
        "loan_deal_ref": row[0],
        "trigger_cashflow_deal_ref": row[1],
        "period_start_date": row[2],
        "comment": row[3],
        "user_id": row[4],
        "updated_at": row[5].isoformat() if row[5] else None,
    }


def fetch_for_loan(cur, loan_deal_ref: str) -> list[dict]:
    cur.execute(
        """
        SELECT to_char(period_start_date, 'YYYY-MM-DD') AS period_start_date,
               comment, user_id, updated_at
          FROM loan_schedule_comments
         WHERE loan_deal_ref = %s
         ORDER BY period_start_date
        """,
        (loan_deal_ref,),
    )
    return [
        {
            "period_start_date": r[0],
            "comment": r[1],
            "user_id": r[2],
            "updated_at": r[3].isoformat() if r[3] else None,
        }
        for r in cur.fetchall()
    ]
