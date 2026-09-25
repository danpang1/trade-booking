"""Read-only client + id resolvers for the Postgres `refdata` DB.

`refdata` holds the dense integer ids that nx-hft-position consumes:
`exchanges` (codename→id), `assets` (codename→id), `instruments`. It is a
SEPARATE database from both the MO DB and the tech DB.

Used by manual_write.py to turn booking business strings into the dense
refdata ids the manual_trade / manual_cashflow tables require.

Creds: REFDATA_DB_* env vars first, else the `# REFDATA DB` block in .env
(same convention as tech_db / cashflow_db).

NOTE — the venue → exchange-codename step is intentionally NOT implemented here
(see `exchange_codename`): a booking carries a venue *name*, and a venue maps to
several codenames (e.g. binance-spot vs binance-linear) with no clean rule. That
mapping is an open decision; this module resolves a codename that is already
known into its id.
"""
from __future__ import annotations
import os
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENV = REPO / ".env"

_MARKER = "REFDATA DB"
_PREFIX = "refdata_db_"


def load_creds() -> dict[str, str]:
    """REFDATA_DB_* env vars take precedence; `# REFDATA DB` .env block is the fallback."""
    env_creds = {
        k: os.environ[f"REFDATA_DB_{k.upper()}"]
        for k in ("host", "port", "database", "username", "password")
        if f"REFDATA_DB_{k.upper()}" in os.environ
    }
    if all(k in env_creds for k in ("host", "database", "username", "password")):
        env_creds.setdefault("port", "5432")
        return env_creds

    if not ENV.exists():
        raise FileNotFoundError(
            f".env not found at {ENV} and REFDATA_DB_* env vars are incomplete"
        )

    creds: dict[str, str] = {}
    in_block = False
    for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if _MARKER in s.upper():
            in_block = True
            continue
        if not in_block:
            continue
        if not s or s.startswith("#"):
            if s.startswith("#") and _MARKER not in s.upper():
                break
            continue
        if ":" in s:
            k, _, v = s.partition(":")
            key = k.strip().lower()
            if key.startswith(_PREFIX):
                key = key[len(_PREFIX):]
            creds[key] = v.strip()

    if not creds:
        raise RuntimeError(f"No '# REFDATA DB' block (or empty block) found in {ENV}")
    return creds


def connect():
    """Open a psycopg2 connection to refdata and PIN THE SESSION READ-ONLY.

    The provisioned refdata creds are read-WRITE, but this service must never
    write to refdata — so the session is forced read-only client-side: any
    INSERT/UPDATE/DELETE then fails with "cannot execute … in a read-only
    transaction". Reads only (autocommit on).
    """
    import psycopg2

    # Accept a full DSN via REFDATA_DB_URL (the k8s `refdata-db-config` secret's
    # single `url`) or the split REFDATA_DB_* / `# REFDATA DB` creds. In a libpq
    # URI the password must be percent-encoded (a literal `@` is `%40`).
    url = os.environ.get("REFDATA_DB_URL")
    if url:
        conn = psycopg2.connect(url, connect_timeout=15)
    else:
        c = load_creds()
        conn = psycopg2.connect(
            host=c["host"],
            port=int(c.get("port", "5432")),
            dbname=c["database"],
            user=c["username"],
            password=c["password"],
            connect_timeout=15,
        )
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SET default_transaction_read_only = on")
    return conn


# ── Resolvers ─────────────────────────────────────────────────────────────
# These take an open cursor so a booking can resolve several ids on one conn.

def resolve_exchange_id(cur, codename: str) -> int | None:
    """exchanges.codename → id (e.g. 'binance-spot' → 12). None if unknown."""
    cur.execute("SELECT id FROM exchanges WHERE codename = %s", (codename,))
    row = cur.fetchone()
    return int(row[0]) if row else None


def resolve_asset_id(cur, code: str) -> int | None:
    """assets.codename → id, case-insensitive (e.g. 'BTC' → 4). None if unknown.

    Booking payloads carry upper-case codes ('BTC','USDT'); refdata codenames
    are lower-case ('btc','usdt').
    """
    if code is None:
        return None
    cur.execute("SELECT id FROM assets WHERE codename = %s", (code.strip().lower(),))
    row = cur.fetchone()
    return int(row[0]) if row else None


# ── UNDECIDED (do not use yet) ──────────────────────────────────────────────
def exchange_codename(venue: str, product: str) -> str:
    """Map a booking venue name + product to a refdata exchange codename.

    UNDECIDED — not implemented. There is no clean rule: a venue maps to
    several codenames (binance-spot / binance-linear / binance-convert; a spot
    manual trade is *-spot but cashflows are ambiguous) and some codenames are
    not `venue + '-' + product` at all (alpaca-us-equity, ibkr, native-spot).
    This needs a curated venue+product → codename table. Left for review.
    """
    raise NotImplementedError(
        "venue+product -> exchange codename mapping is an open decision; "
        f"cannot resolve venue={venue!r} product={product!r}"
    )
