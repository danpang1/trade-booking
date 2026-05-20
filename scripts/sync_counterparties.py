"""Sync the counterparty reference list from MySQL → JSON file.

Source : sg-ro-mysql.internal.tokkalabs.com, `reference_data.counterparty`
Target : trade-booking/src/data/counterparties.json
Filter : deletedAt IS NULL AND (status IS NULL OR status='ACTIVE')

The React form (TradeBookingForm.jsx) imports the JSON and derives
both the COUNTERPARTIES picker list and the COUNTERPARTY_IDS lookup
from it. Run this whenever the desk reports the list looks stale.

Schedule: can be wired into launchd / cron for hourly refresh.
For now, run manually:

    python trade-booking/scripts/sync_counterparties.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pymysql

REPO = Path(__file__).resolve().parents[1]
ENV = REPO / ".env"
OUT = REPO / "public" / "refdata" / "counterparties.json"


def _load_mysql_creds() -> dict[str, str]:
    """Read sg-ro-mysql creds. Env vars (SG_RO_MYSQL_*) take precedence;
    .env file parsed as fallback for local dev."""
    env_creds = {
        k: os.environ[f"SG_RO_MYSQL_{k.upper()}"]
        for k in ("host", "username", "password")
        if f"SG_RO_MYSQL_{k.upper()}" in os.environ
    }
    if all(k in env_creds for k in ("host", "username", "password")):
        return env_creds

    if not ENV.exists():
        raise FileNotFoundError(
            f".env not found at {ENV} and SG_RO_MYSQL_* env vars are incomplete"
        )

    lines = ENV.read_text(encoding="utf-8", errors="replace").splitlines()
    creds: dict[str, str] = {}
    for i, ln in enumerate(lines):
        if "sg-ro-mysql" in ln.lower():
            # Walk backwards up to 5 lines + forwards up to 2 to grab the block
            for j in range(max(0, i - 5), min(len(lines), i + 3)):
                s = lines[j].strip()
                if not s or s.startswith("#"):
                    continue
                if ":" in s:
                    k, _, v = s.partition(":")
                    creds[k.strip().lower()] = v.strip()
            break
    if not all(k in creds for k in ("username", "password", "host")):
        raise RuntimeError(
            "sg-ro-mysql credentials missing in .env "
            "(need username, password, host)"
        )
    return creds


def main() -> None:
    creds = _load_mysql_creds()
    conn = pymysql.connect(
        host=creds["host"],
        user=creds["username"],
        password=creds["password"],
        database="reference_data",
        connect_timeout=15,
    )
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, type, subType FROM counterparty "
            "WHERE deletedAt IS NULL AND (status IS NULL OR status='ACTIVE') "
            "ORDER BY name"
        )
        rows = [
            {"id": r[0], "name": r[1], "type": r[2], "subType": r[3]}
            for r in cur.fetchall()
        ]
    finally:
        conn.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Quick summary so the operator can sanity-check
    by_subtype: dict[str, int] = {}
    for r in rows:
        by_subtype[r["subType"]] = by_subtype.get(r["subType"], 0) + 1
    print(f"wrote {len(rows)} counterparties -> {OUT}")
    print("by subType:")
    for k, v in sorted(by_subtype.items(), key=lambda kv: -kv[1]):
        print(f"  {v:4d}  {k}")
    lenders = sum(1 for r in rows if r["subType"] == "LENDER")
    print(f"\nLENDER-subType only (loan view): {lenders}")


if __name__ == "__main__":
    main()
