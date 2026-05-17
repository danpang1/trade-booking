"""Sync the portfolio reference list from MySQL → JSON file.

Source : sg-ro-mysql.internal.tokkalabs.com, `reference_data.portfolio`
Target : trade-booking/public/refdata/portfolios.json
Filter : deletedAt IS NULL AND (status IS NULL OR status='ACTIVE')

The React form (TradeBookingForm.jsx) fetches the JSON on mount and
on refresh-button click, replacing the historic hardcoded PORTFOLIOS
constant.
"""
from __future__ import annotations

import json
from pathlib import Path

import pymysql

REPO = Path(__file__).resolve().parents[2]
ENV = REPO / ".env"
OUT = REPO / "trade-booking" / "public" / "refdata" / "portfolios.json"


def _load_mysql_creds() -> dict[str, str]:
    """Read the sg-ro-mysql block from .env."""
    if not ENV.exists():
        raise FileNotFoundError(f".env not found at {ENV}")

    lines = ENV.read_text(encoding="utf-8", errors="replace").splitlines()
    creds: dict[str, str] = {}
    for i, ln in enumerate(lines):
        if "sg-ro-mysql" in ln.lower():
            for j in range(max(0, i - 5), min(len(lines), i + 3)):
                s = lines[j].strip()
                if not s or s.startswith("#"):
                    continue
                if ":" in s:
                    k, _, v = s.partition(":")
                    creds[k.strip().lower()] = v.strip()
            break
    if not all(k in creds for k in ("username", "password", "host")):
        raise RuntimeError("sg-ro-mysql credentials missing in .env")
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
            "SELECT id, number, name, organisation, type, mainGroup, manager "
            "FROM portfolio "
            "WHERE deletedAt IS NULL AND (status IS NULL OR status='ACTIVE') "
            "ORDER BY number"
        )
        rows = [
            {
                "id": r[0],
                "number": r[1],
                "name": r[2],
                "entity": r[3],
                "type": r[4],
                "mainGroup": r[5],
                "manager": r[6],
            }
            for r in cur.fetchall()
        ]
    finally:
        conn.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} portfolios → {OUT}")


if __name__ == "__main__":
    main()
