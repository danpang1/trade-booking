"""Apply the trades_loan schema + trade_seq_loan sequence to UAT Postgres.

Idempotent: uses CREATE ... IF NOT EXISTS so re-running is safe.
Reads credentials from the `#MO DB UAT` block in /.env.

Model
-----
One row per loan CONTRACT (the agreement: who, with whom, principal,
rate, term, collateral terms). Amendments insert a new row via SCD2 —
identical pattern to trades_cashflow.

What does NOT live here:
- The actual disbursement of principal       → trades_cashflow row (cashflow_type='LOAN')
- Interest accruals / payments               → trades_cashflow row (cashflow_type='INTEREST EXPENSE' / 'INTEREST INCOME')
- Principal repayments                       → trades_cashflow row (cashflow_type='LOAN REPAYMENT')
- Collateral postings / unpostings           → trades_cashflow row (cashflow_type='COLLATERAL POSTING')
- The hedge spot trade (if is_hedged)        → trades_spot row (booked separately).
                                                The HEDGE ECONOMICS (asset/qty/price/proceeds) are also
                                                captured on this loan row as hedge_* columns so the loan
                                                tells the full story. The operator manually pastes the
                                                hedge SPOT deal_ref into `comment` for cross-reference —
                                                no FK enforced.

All of those cashflow events carry a loan_deal_ref column (added by a
separate migration to trades_cashflow) pointing back to this row's deal_ref.
"""
import os
from pathlib import Path
import psycopg2

REPO = Path(__file__).resolve().parents[1]
ENV = REPO / ".env"


def _load_creds() -> dict[str, str]:
    """Env vars (MO_DB_*) take precedence; .env file parsed as fallback."""
    env_creds = {
        k: os.environ[f"MO_DB_{k.upper()}"]
        for k in ("host", "port", "database", "username", "password")
        if f"MO_DB_{k.upper()}" in os.environ
    }
    if all(k in env_creds for k in ("host", "database", "username", "password")):
        env_creds.setdefault("port", "5432")
        return env_creds

    creds: dict[str, str] = {}
    in_block = False
    for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if "MO DB UAT" in s.upper():
            in_block = True
            continue
        if not in_block:
            continue
        if not s or s.startswith("#"):
            if s.startswith("#") and "MO DB UAT" not in s.upper():
                break
            continue
        if ":" in s:
            k, _, v = s.partition(":")
            key = k.strip().lower()
            if key.startswith("mo_db_"):
                key = key[len("mo_db_"):]
            creds[key] = v.strip()
    return creds


DDL = """
-- ════════════════════════════════════════════════════════════════
-- trade_seq_loan — monotonic counter for MLA deal-refs.
-- ════════════════════════════════════════════════════════════════
CREATE SEQUENCE IF NOT EXISTS trade_seq_loan
  START WITH 1 INCREMENT BY 1 NO MAXVALUE CACHE 1;

-- ════════════════════════════════════════════════════════════════
-- trades_loan — bitemporal loan contracts.
-- Column order matches the form JSON payload key sequence
-- (see trade-booking/docs/loan-schema-mapping.md) so backend
-- INSERTs and SELECT * round-trip in the same shape as the form.
-- ════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS trades_loan (
  deal_ref                TEXT           NOT NULL
                            DEFAULT ('MLA' || lpad(nextval('trade_seq_loan')::text, 8, '0')),
  order_id                TEXT,
                          -- Counterparty's order/loan reference
                          -- (e.g. Binance VIP loan ID). Form field is
                          -- still `form.external_trade_id` — only the
                          -- UI label and DB column use the LOAN-specific
                          -- "Order ID" naming.
  txn_type                TEXT           NOT NULL DEFAULT 'LOAN',
  direction               TEXT           NOT NULL
                            CHECK (direction IN ('BORROW','LEND')),
  loan_type               TEXT           NOT NULL
                            CHECK (loan_type IN
                              ('VIP LOAN','INTERNAL','EXTERNAL','DEFI LENDING')),
                          -- Mirror this list in the React `LOAN_TYPES`
                          -- constant (src/TradeBookingForm.jsx). New
                          -- types require updating both this CHECK and
                          -- the form constant.
  entity                  TEXT           NOT NULL,
  portfolio_id            TEXT           NOT NULL,
  portfolio_name          TEXT           NOT NULL,
  counterparty_id         TEXT,
  counterparty            TEXT,
  principal_asset         TEXT           NOT NULL,
  principal_amount        NUMERIC(36,18) NOT NULL
                            CHECK (principal_amount > 0),
  interest_asset          TEXT           NOT NULL,
  interest_rate_pa_pct    NUMERIC(12,6)  NOT NULL DEFAULT 0,
  interest_type           TEXT           NOT NULL
                            CHECK (interest_type IN ('FIXED','FLOATING')),
  day_count_basis         SMALLINT       NOT NULL DEFAULT 365
                            CHECK (day_count_basis IN (360, 365)),
                          -- Days-per-year for interest accrual:
                          --   365 = Actual/365 (crypto convention)
                          --   360 = Actual/360 (USD money markets)
                          -- Stored as a knob; the form captures it but
                          -- no auto-accrual job consumes it yet — that's
                          -- a separate feature.
  floating_benchmark      TEXT,
                          -- Only meaningful when interest_type='FLOATING'
                          -- (e.g. SOFR, AAVE_USDC_BORROW_APY).
  collateral_asset        TEXT,
  collateral_amount       NUMERIC(36,18),
  is_hedged               BOOLEAN        NOT NULL DEFAULT FALSE,
  hedged_asset            TEXT,
  hedged_qty              NUMERIC(36,18),
  hedged_price            NUMERIC(36,18),
  hedge_proceeds_asset    TEXT,
  hedge_proceeds_amount   NUMERIC(36,18),
                          -- Hedge economics captured at booking. The
                          -- actual SPOT trade is booked separately on
                          -- trades_spot; operator pastes its deal_ref
                          -- into `comment` for cross-reference.
  trade_date              TIMESTAMPTZ    NOT NULL,
                          -- "Start Date" in the form — when the loan was
                          -- booked AND principal was disbursed. Same-day
                          -- for our manual-booking workflow, so we don't
                          -- carry a separate value_date column.
  maturity_date           TIMESTAMPTZ,
                          -- "Maturity Date" in the form (form.value_date).
                          -- NULL = open-term (REVOLVING / MARGIN credit lines
                          -- with no fixed maturity). Term-in-days is derived
                          -- as (maturity_date - trade_date); not stored.
  effective_start         TIMESTAMPTZ    NOT NULL,
  effective_end           TIMESTAMPTZ,
  user_id                 TEXT           NOT NULL,
  status                  TEXT           NOT NULL
                            CHECK (status IN ('LIVE','MATURED','CANCELLED')),
  comment                 TEXT,
  wht_pct                 NUMERIC(8,4),
                          -- Optional withholding tax rate (% of accrued
                          -- interest). NULL = not applicable. Shown in
                          -- the schedule's WHT column as accrued × wht_pct/100
                          -- per row. No CHECK constraint — caller validates.

  -- Sanity constraints
  CONSTRAINT trades_loan_maturity_after_start
    CHECK (maturity_date IS NULL OR maturity_date >= trade_date),
  CONSTRAINT trades_loan_floating_benchmark_consistency
    CHECK (
      (interest_type = 'FLOATING')
      OR (floating_benchmark IS NULL)
    ),
  CONSTRAINT trades_loan_collateral_pair
    CHECK (
      (collateral_asset IS NULL AND collateral_amount IS NULL)
      OR (collateral_asset IS NOT NULL AND collateral_amount IS NOT NULL
          AND collateral_amount > 0)
    ),
  CONSTRAINT trades_loan_hedge_consistency
    CHECK (
      is_hedged = FALSE
      OR (hedged_asset IS NOT NULL
          AND hedged_qty IS NOT NULL AND hedged_qty > 0
          AND hedged_price IS NOT NULL AND hedged_price > 0)
    ),

  id                      BIGINT         GENERATED BY DEFAULT AS IDENTITY,
  PRIMARY KEY (id),
  CONSTRAINT uq_trades_loan_version UNIQUE (deal_ref, effective_start)
);

-- ─── Indexes ──────────────────────────────────────────────────────
-- Partial indexes on `effective_end IS NULL` keep Deal Enquiry fast
-- regardless of how big the amendment history grows. Same pattern as
-- trades_cashflow.

CREATE INDEX IF NOT EXISTS idx_tloan_live
  ON trades_loan (deal_ref) WHERE effective_end IS NULL;
CREATE INDEX IF NOT EXISTS idx_tloan_deal_ref
  ON trades_loan (deal_ref);
CREATE INDEX IF NOT EXISTS idx_tloan_portfolio_live
  ON trades_loan (portfolio_id, trade_date DESC) WHERE effective_end IS NULL;
CREATE INDEX IF NOT EXISTS idx_tloan_counterparty_live
  ON trades_loan (counterparty, trade_date DESC) WHERE effective_end IS NULL;
CREATE INDEX IF NOT EXISTS idx_tloan_maturity_live
  ON trades_loan (maturity_date)
  WHERE effective_end IS NULL AND status = 'LIVE';
CREATE INDEX IF NOT EXISTS idx_tloan_order_id
  ON trades_loan (order_id) WHERE order_id IS NOT NULL;

-- ─── Migrations on existing trades_loan ───────────────────────────
-- ALTER TABLE ADD COLUMN IF NOT EXISTS is idempotent — re-running is
-- safe. Columns added here always land at the end of the table; keep
-- DATA_COLUMNS in loan_db.py aligned to this trailing order.
ALTER TABLE trades_loan
  ADD COLUMN IF NOT EXISTS wht_pct NUMERIC(8,4);
"""


def main():
    c = _load_creds()
    conn = psycopg2.connect(
        host=c["host"],
        port=int(c.get("port", "5432")),
        dbname=c["database"],
        user=c["username"],
        password=c["password"],
        connect_timeout=15,
    )
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(DDL)
    print("applied DDL OK\n")

    cur.execute("""
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_name = 'trades_loan'
        ORDER BY ordinal_position
    """)
    cols = cur.fetchall()
    print(f"trades_loan columns: {len(cols)}")
    for col in cols:
        print(f"  {col[0]:24s} {col[1]:20s} {'NULL' if col[2] == 'YES' else 'NOT NULL':10s} {col[3] or ''}")

    cur.execute(
        "SELECT sequencename, start_value, last_value, increment_by "
        "FROM pg_sequences WHERE sequencename='trade_seq_loan'"
    )
    seq = cur.fetchone()
    print(f"\nsequence: {seq}")

    cur.execute("""
        SELECT indexname FROM pg_indexes
        WHERE tablename='trades_loan'
        ORDER BY indexname
    """)
    idx = [r[0] for r in cur.fetchall()]
    print(f"\nindexes: {idx}")

    cur.execute(
        "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid='trades_loan'::regclass ORDER BY contype, conname"
    )
    print("\nconstraints:")
    for row in cur.fetchall():
        print(f"  {row[0]:50s} {row[1]}")

    conn.close()


if __name__ == "__main__":
    main()
