"""Create `users` and `sessions` tables. Idempotent."""
from __future__ import annotations
import cashflow_db

DDL = """
CREATE TABLE IF NOT EXISTS users (
  id              SERIAL          PRIMARY KEY,
  username        VARCHAR(64)     NOT NULL UNIQUE,
  email           VARCHAR(255)    NOT NULL UNIQUE,
  role            VARCHAR(16)     NOT NULL CHECK (role IN ('admin','user')),
  password_hash   VARCHAR(60)     NOT NULL,
  created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
  created_by      VARCHAR(64),
  updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
  updated_by      VARCHAR(64)
);

CREATE INDEX IF NOT EXISTS users_username_lower_idx ON users (LOWER(username));

CREATE TABLE IF NOT EXISTS sessions (
  session_id      UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         INTEGER         NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
  expires_at      TIMESTAMPTZ     NOT NULL,
  last_seen_at    TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS sessions_user_id_idx    ON sessions (user_id);
CREATE INDEX IF NOT EXISTS sessions_expires_at_idx ON sessions (expires_at);
"""


def main() -> None:
    conn = cashflow_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(DDL)
        print("ok: users + sessions tables ready")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
