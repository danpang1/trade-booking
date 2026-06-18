"""Apply the trade_attachments schema to UAT Postgres.

Idempotent: uses CREATE ... IF NOT EXISTS so re-running is safe.
Reads credentials from the `# MO DB UAT` block in .env.
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
-- trade_attachments — drive attachments linked to deal_ref.
-- ════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS trade_attachments (
  id               BIGSERIAL    PRIMARY KEY,
  deal_ref         TEXT         NOT NULL,
  drive_folder_id  TEXT         NOT NULL,
  drive_folder_url TEXT         NOT NULL,
  file_name        TEXT         NOT NULL,
  drive_file_id    TEXT         NOT NULL UNIQUE,
  drive_view_url   TEXT         NOT NULL,
  mime_type        TEXT         NOT NULL,
  size_bytes       BIGINT       NOT NULL,
  status           TEXT         NOT NULL DEFAULT 'uploaded'
                                  CHECK (status IN ('uploaded','removed')),
  uploaded_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  uploaded_by      TEXT
);

CREATE INDEX IF NOT EXISTS trade_attachments_deal_ref_idx
  ON trade_attachments (deal_ref);
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
    print("trade_attachments: applied (idempotent).")

    # Verify
    cur.execute("""
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_name = 'trade_attachments'
        ORDER BY ordinal_position
    """)
    cols = cur.fetchall()
    print(f"\ntrade_attachments columns: {len(cols)}")
    for col in cols:
        print(f"  {col[0]:20s} {col[1]:20s} {'NULL' if col[2] == 'YES' else 'NOT NULL':10s} {col[3] or ''}")

    cur.execute("""
        SELECT indexname FROM pg_indexes
        WHERE tablename='trade_attachments'
        ORDER BY indexname
    """)
    idx = [r[0] for r in cur.fetchall()]
    print(f"\nindexes: {idx}")

    cur.execute("""
        SELECT pg_get_constraintdef(oid)
        FROM pg_constraint
        WHERE conrelid='trade_attachments'::regclass
        ORDER BY contype
    """)
    print("\nconstraints:")
    for row in cur.fetchall():
        print(f"  {row[0]}")

    conn.close()


if __name__ == "__main__":
    main()
