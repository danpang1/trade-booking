"""Create `bookings_draft` table. Idempotent."""
from __future__ import annotations
import cashflow_db

DDL = """
CREATE TABLE IF NOT EXISTS bookings_draft (
  id                  SERIAL          PRIMARY KEY,
  category            TEXT            NOT NULL
                        CHECK (category IN ('SPOT','CASHFLOW','TRANSFER')),
  payload             JSONB           NOT NULL,
  source              TEXT            NOT NULL
                        CHECK (source IN ('CLAUDE_CODE')),
  status              TEXT            NOT NULL
                        CHECK (status IN
                          ('PENDING_REVIEW','APPROVED','REJECTED')),
  batch_id            UUID,
  client_request_id   UUID            NOT NULL UNIQUE,
  created_by          VARCHAR(64)     NOT NULL,
  created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
  approved_at         TIMESTAMPTZ,
  approved_by         VARCHAR(64),
  approved_deal_ref   TEXT,
  rejected_at         TIMESTAMPTZ,
  rejected_by         VARCHAR(64),
  rejection_reason    TEXT
);

CREATE INDEX IF NOT EXISTS idx_drafts_user_status
  ON bookings_draft (created_by, status);

CREATE INDEX IF NOT EXISTS idx_drafts_batch
  ON bookings_draft (batch_id)
  WHERE batch_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_drafts_pending
  ON bookings_draft (created_by, created_at DESC)
  WHERE status = 'PENDING_REVIEW';

-- TRANSFER drafts (2026-09-30) on a table created before them: the CHECK
-- above only applies to a fresh table, so re-create the constraint when the
-- existing one does not list TRANSFER. Prod hit exactly this on 2026-10-07
-- ("violates check constraint bookings_draft_category_check").
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_constraint
             WHERE conname = 'bookings_draft_category_check'
               AND pg_get_constraintdef(oid) NOT LIKE '%TRANSFER%') THEN
    ALTER TABLE bookings_draft DROP CONSTRAINT bookings_draft_category_check;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'bookings_draft_category_check') THEN
    ALTER TABLE bookings_draft ADD CONSTRAINT bookings_draft_category_check
      CHECK (category IN ('SPOT','CASHFLOW','TRANSFER'));
  END IF;
END $$;
"""


def main() -> None:
    conn = cashflow_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(DDL)
        print("ok: bookings_draft table ready")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
