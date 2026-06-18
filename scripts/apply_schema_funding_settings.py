"""Apply the funding_settings schema to UAT.

A tiny shared key-value store for the Dashboard's Funding & Deployment
band. One row per setting key ('capital', 'itd_pnl'); operators overwrite
their own row by editing the value. Plain table (NOT bitemporal).
"""
import os
from pathlib import Path
import psycopg2

REPO = Path(__file__).resolve().parents[1]
ENV = REPO / ".env"


def _load_creds() -> dict[str, str]:
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
CREATE TABLE IF NOT EXISTS funding_settings (
  key         TEXT          NOT NULL,
  value       NUMERIC       NOT NULL,
  updated_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
  updated_by  TEXT          NOT NULL,
  PRIMARY KEY (key)
);
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
        WHERE table_name = 'funding_settings'
        ORDER BY ordinal_position
    """)
    cols = cur.fetchall()
    print(f"funding_settings columns: {len(cols)}")
    for col in cols:
        nullable = 'NULL' if col[2] == 'YES' else 'NOT NULL'
        print(f"  {col[0]:20s} {col[1]:25s} {nullable:10s} {col[3] or ''}")
    conn.close()


if __name__ == "__main__":
    main()
