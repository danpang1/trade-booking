"""Who may see which portfolio's trades and loans.

`reference_data.portfolio.usernames` is a comma-separated email list per
portfolio, maintained in TMS. It is the firm's own answer to "whose book is
this", so it is the right thing to gate on -- there is no second list to keep
in step, and granting someone a portfolio in TMS grants them TMS dashboard
access with no deploy.

server.js spawns this module on the refdata tick and holds the result in
memory. Nothing here is written to disk: `public/refdata/` is served to
browsers without authentication, and the firm's email-to-book map is not a
static asset.

Sibling implementations that agree on these semantics: ace-run/access.py
(which carries the regression tests), Paxos mintburn/access.py,
slack-trade-bot/access.py.

Everything here FAILS CLOSED. See `build_map`.

Manual smoke:
    python3 trade-booking/scripts/portfolio_access.py
    python3 trade-booking/scripts/portfolio_access.py --audit
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENV = REPO / ".env"

# Marker line anchoring the read-only refdata MySQL block in .env. The keys
# sit ABOVE it.
#
# Matched EXACTLY, not as a substring: the .env's own header comment mentions
# the marker by name several lines up, and a substring search lands on that
# comment and parses nothing. slack-trade-bot/access.py documents the same
# trap, and this module hit it on its first real run.
ENV_MARKERS = ("# sg-ro-mysql", "# t2x-ro-mysql")


def load_mysql_creds() -> dict[str, str]:
    """Read-only refdata MySQL creds.

    Env vars (T2X_RO_MYSQL_*) take precedence; the .env block is the fallback,
    parsed the way sync_portfolios.py parses it.
    """
    env_creds = {
        k: os.environ[f"T2X_RO_MYSQL_{k.upper()}"]
        for k in ("host", "username", "password")
        if f"T2X_RO_MYSQL_{k.upper()}" in os.environ
    }
    if all(k in env_creds for k in ("host", "username", "password")):
        return env_creds

    if not ENV.exists():
        raise FileNotFoundError(
            f".env not found at {ENV} and T2X_RO_MYSQL_* env vars are incomplete"
        )

    lines = ENV.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    marks = [
        i for i, ln in enumerate(lines)
        if ln.strip().lower() in ENV_MARKERS
    ]
    if not marks:
        raise RuntimeError(
            f"no {' or '.join(ENV_MARKERS)} marker line in {ENV}"
        )
    creds: dict[str, str] = {}
    for j in range(max(0, marks[0] - 5), marks[0]):
        s = lines[j].strip()
        if not s or s.startswith("#") or ":" not in s:
            continue
        k, _, v = s.partition(":")
        creds[k.strip().lower()] = v.strip()
    missing = [k for k in ("host", "username", "password") if k not in creds]
    if missing:
        raise RuntimeError(
            "t2x-ro-mysql credentials missing in .env: " + ", ".join(missing)
        )
    return creds


def split_emails(usernames: str | None) -> set[str]:
    """`"A@x.com, b@X.com "` -> {"a@x.com", "b@x.com"}."""
    return {
        e.strip().lower()
        for e in (usernames or "").split(",")
        if e.strip()
    }


def build_map(rows) -> tuple[dict[str, list[int]], dict[str, str]]:
    """`(by_email, names)` from `(number, name, usernames)` rows.

    Refuses to return a map in which no portfolio has any member. A successful
    query against broken or empty refdata would otherwise read as "nobody has
    access to anything", which locks the firm out of its own book.
    """
    by_email: dict[str, set[int]] = {}
    names: dict[str, str] = {}
    any_member = False
    for number, name, usernames in rows:
        if number is None:
            continue
        number = int(number)
        names[str(number)] = name
        for email in split_emails(usernames):
            any_member = True
            by_email.setdefault(email, set()).add(number)
    if not any_member:
        raise RuntimeError("no portfolio has any usernames -- refusing to load")
    return ({e: sorted(v) for e, v in by_email.items()}, names)


def fetch_rows(cur):
    """`(number, name, usernames)` for every portfolio that still grants access.

    A soft-deleted portfolio still carries its old `usernames`, so reading it
    would keep granting a book MO has retired -- hence `deletedAt IS NULL`.
    `status` excludes DELETED alone: a DORMANT portfolio is a live grant, it
    just is not trading today.
    """
    cur.execute(
        "SELECT number, name, usernames FROM portfolio "
        " WHERE deletedAt IS NULL "
        "   AND (status IS NULL OR status <> 'DELETED')"
    )
    return cur.fetchall()


def load() -> dict:
    """Query refdata and return the payload server.js caches."""
    import pymysql

    creds = load_mysql_creds()
    conn = pymysql.connect(
        host=creds["host"],
        user=creds["username"],
        password=creds["password"],
        database="reference_data",
        connect_timeout=20,
    )
    try:
        cur = conn.cursor()
        rows = fetch_rows(cur)
    finally:
        conn.close()

    by_email, names = build_map(rows)
    return {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "by_email": by_email,
        "names": names,
    }


def audit() -> int:
    """Read-only report: every TMS user and the portfolios T2X would grant.

    Run before deploying portfolio scoping. It answers whether the change is
    invisible or whether it takes people's access away.
    """
    import cashflow_db

    payload = load()
    by_email = payload["by_email"]
    names = payload["names"]

    conn = cashflow_db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT username, email, role FROM users ORDER BY role, username"
            )
            users = cur.fetchall()
    finally:
        conn.close()

    print(f"{len(users)} TMS users, {len(by_email)} emails known to T2X\n")
    header = "%-24s %-34s %-6s %s" % ("USERNAME", "EMAIL", "ROLE", "PORTFOLIOS")
    print(header)
    print("-" * len(header))
    orphans = []
    for username, email, role in users:
        granted = by_email.get((email or "").strip().lower(), [])
        if role == "admin":
            shown = "(admin - all)"
        elif granted:
            shown = ", ".join(str(n) for n in granted)
        else:
            shown = "*** NONE - will see an empty dashboard ***"
            orphans.append(username)
        print("%-24s %-34s %-6s %s" % (username, email, role, shown))

    if orphans:
        print(
            f"\n{len(orphans)} non-admin user(s) with no portfolio: "
            + ", ".join(orphans)
        )
        print("Fix in TMS (portfolio.usernames) before deploying, or they go dark.")
    else:
        print("\nEvery non-admin user has at least one portfolio.")

    unknown = sorted(set(names) - {str(n) for v in by_email.values() for n in v})
    if unknown:
        print(f"\n{len(unknown)} portfolio(s) with no members at all: "
              + ", ".join(unknown[:20])
              + (" ..." if len(unknown) > 20 else ""))
    return 0


def main() -> int:
    if "--audit" in sys.argv[1:]:
        return audit()
    try:
        print(json.dumps(load()))
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "error": "refdata unavailable",
                          "detail": str(e)}))
        return 5


if __name__ == "__main__":
    sys.exit(main())
