"""Create `api_tokens` table. Idempotent."""
from __future__ import annotations
import cashflow_db

DDL = """
CREATE TABLE IF NOT EXISTS api_tokens (
  id            SERIAL          PRIMARY KEY,
  user_id       INTEGER         NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash    VARCHAR(64)     NOT NULL UNIQUE,
  token_prefix  VARCHAR(16)     NOT NULL,
  name          VARCHAR(64)     NOT NULL,
  created_at    TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
  last_used_at  TIMESTAMPTZ,
  expires_at    TIMESTAMPTZ     NOT NULL,
  revoked_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS api_tokens_user_idx
  ON api_tokens (user_id) WHERE revoked_at IS NULL;

CREATE INDEX IF NOT EXISTS api_tokens_lookup_idx
  ON api_tokens (token_hash) WHERE revoked_at IS NULL;
"""


def main() -> None:
    conn = cashflow_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(DDL)
        print("ok: api_tokens table ready")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
