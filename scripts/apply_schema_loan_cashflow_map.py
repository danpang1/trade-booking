"""Apply the loan_cashflow_map schema (loans ↔ cashflows linking table) to UAT.

Idempotent: CREATE ... IF NOT EXISTS so re-running is safe.
Reads credentials from the `#MO DB UAT` block in /.env.

Model
-----
Plain many-to-many mapping. One cashflow can link to several loans; one
loan can link to several cashflows. PRIMARY KEY (loan_deal_ref,
cashflow_deal_ref) enforces at-most-one mapping per pair.

NOT bitemporal — mappings are overwritten in place. The cashflow row's
own SCD2 history records *that* the mapping changed; the link table
itself is a snapshot of "what's currently mapped".

No foreign keys — both trades_loan and trades_cashflow are bitemporal
with composite PKs `(deal_ref, effective_start)`, so a FK to bare
deal_ref isn't well-defined. Backend enforces referential integrity at
write time.
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
-- loan_cashflow_map — links cashflow rows to loan rows.
-- See docs/superpowers/specs/2026-05-16-loan-cashflow-mapping-design.md
-- ════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS loan_cashflow_map (
  loan_deal_ref       TEXT           NOT NULL,
                                    -- MLA-prefix, refers to trades_loan.deal_ref
  cashflow_deal_ref   TEXT           NOT NULL,
                                    -- MCF-prefix, refers to trades_cashflow.deal_ref
  mapping_type        TEXT,
                                    -- PRINCIPAL_DISBURSE / PRINCIPAL_REPAY /
                                    -- INTEREST / COLLATERAL_POST /
                                    -- COLLATERAL_RELEASE / FEE.
                                    -- NULL allowed for manual mappings of
                                    -- non-loan cashflow types.
                            CHECK (mapping_type IS NULL OR mapping_type IN
                              ('PRINCIPAL_DISBURSE','PRINCIPAL_REPAY','INTEREST',
                               'COLLATERAL_POST','COLLATERAL_RELEASE','FEE')),
  mapped_amount       NUMERIC(36,18),
                                    -- NULL = full cashflow amount.
                                    -- Reserved for future split-allocation UI.
  mapped_by           TEXT           NOT NULL,
  mapped_at           TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
  comment             TEXT,

  PRIMARY KEY (loan_deal_ref, cashflow_deal_ref)
);

-- ─── Indexes ──────────────────────────────────────────────────────
-- Loan side: "give me every cashflow mapped to MLA00000001".
CREATE INDEX IF NOT EXISTS idx_lcm_loan
  ON loan_cashflow_map (loan_deal_ref);
-- Cashflow side: "give me every loan this cashflow links to" (used by
-- the LEFT JOIN in cashflow_get / _recent / _history).
CREATE INDEX IF NOT EXISTS idx_lcm_cashflow
  ON loan_cashflow_map (cashflow_deal_ref);

-- ─── Cascade triggers ─────────────────────────────────────────────
-- Because trades_loan and trades_cashflow are bitemporal (PK is
-- (deal_ref, effective_start)), we can't declare a normal FK against
-- bare deal_ref. These AFTER DELETE triggers fill the gap: when ALL
-- SCD2 versions of a deal_ref have been hard-deleted, the corresponding
-- mapping rows are cleaned up too. SCD2 amends INSERT new rows (not
-- DELETE prior versions) so the triggers never fire during normal
-- amend/cancel workflows — only on raw SQL deletes.

CREATE OR REPLACE FUNCTION lcm_cleanup_on_loan_delete() RETURNS TRIGGER AS $$
BEGIN
  -- Only nuke mappings once the loan is FULLY gone (no remaining
  -- SCD2 versions). Otherwise deleting just one version would
  -- orphan the survivor's link erroneously.
  IF NOT EXISTS (SELECT 1 FROM trades_loan WHERE deal_ref = OLD.deal_ref) THEN
    DELETE FROM loan_cashflow_map WHERE loan_deal_ref = OLD.deal_ref;
  END IF;
  RETURN OLD;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION lcm_cleanup_on_cashflow_delete() RETURNS TRIGGER AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM trades_cashflow WHERE deal_ref = OLD.deal_ref) THEN
    DELETE FROM loan_cashflow_map WHERE cashflow_deal_ref = OLD.deal_ref;
  END IF;
  RETURN OLD;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_lcm_cleanup_loan ON trades_loan;
CREATE TRIGGER trg_lcm_cleanup_loan
  AFTER DELETE ON trades_loan
  FOR EACH ROW EXECUTE FUNCTION lcm_cleanup_on_loan_delete();

DROP TRIGGER IF EXISTS trg_lcm_cleanup_cashflow ON trades_cashflow;
CREATE TRIGGER trg_lcm_cleanup_cashflow
  AFTER DELETE ON trades_cashflow
  FOR EACH ROW EXECUTE FUNCTION lcm_cleanup_on_cashflow_delete();
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
        WHERE table_name = 'loan_cashflow_map'
        ORDER BY ordinal_position
    """)
    cols = cur.fetchall()
    print(f"loan_cashflow_map columns: {len(cols)}")
    for col in cols:
        print(f"  {col[0]:24s} {col[1]:25s} {'NULL' if col[2] == 'YES' else 'NOT NULL':10s} {col[3] or ''}")

    cur.execute("""
        SELECT indexname FROM pg_indexes
        WHERE tablename='loan_cashflow_map'
        ORDER BY indexname
    """)
    idx = [r[0] for r in cur.fetchall()]
    print(f"\nindexes: {idx}")

    cur.execute(
        "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid='loan_cashflow_map'::regclass ORDER BY contype, conname"
    )
    print("\nconstraints:")
    for row in cur.fetchall():
        print(f"  {row[0]:50s} {row[1]}")

    conn.close()


if __name__ == "__main__":
    main()
