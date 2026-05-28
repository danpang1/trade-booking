"""Sync the perpetual-futures reference list from MySQL → JSON file.

Source : sg-ro-mysql.internal.tokkalabs.com,
         `reference_data.instrument_spot_derivatives`
Filter : deletedAt IS NULL AND status='ACTIVE'
         AND instrumentType='FUTURES - PERPETUAL'
Target : trade-booking/public/refdata/perps_instruments.json

The React form imports the JSON at runtime and feeds it into the
InstrumentPicker rendered inside the FUTURE section. v1 of the form
gates the venue dropdown to HYPERLIQUID; other venues (Binance, OKX,
Bybit, dYdX, Drift, etc.) ship in the JSON so they can be enabled
without a refdata change.

Schema (per row):
    id            int        — reference_data primary key
    venue         string     — e.g. "HYPERLIQUID"
    type          string     — "PERP" (FUTURES - PERPETUAL collapsed)
    symbol        string     — display ticker, e.g. "BTC-PERP"
    base          string     — e.g. "BTC"
    quote         string     — e.g. "USD"
    settlement    string?    — settlement asset (often = quote)
    contract_size number     — default 1.0
    max_leverage  number?    — exchange-declared max, when present
    ccxt_id       string?    — for downstream pricing reconciliation
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pymysql


REPO = Path(__file__).resolve().parents[1]
ENV = REPO / ".env"
OUT = REPO / "public" / "refdata" / "perps_instruments.json"


def _load_mysql_creds() -> dict[str, str]:
    """Read MYSQL RO creds. Env vars (T2X_RO_MYSQL_*) take precedence so
    deployed envs override the local-dev .env block lookup."""
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

    lines = ENV.read_text(encoding="utf-8", errors="replace").splitlines()
    creds: dict[str, str] = {}
    in_block = False
    for ln in lines:
        s = ln.strip()
        # Match either the legacy "# t2x-ro-mysql" anchor or the
        # current "#MYSQL RO" / "# MYSQL RO" section header.
        if "t2x-ro-mysql" in s.lower() or s.upper().lstrip("#").strip().startswith("MYSQL RO"):
            in_block = True
            continue
        if not in_block:
            continue
        if not s or s.startswith("#"):
            if s.startswith("#"):
                break
            continue
        if ":" in s:
            k, _, v = s.partition(":")
            creds[k.strip().lower()] = v.strip()
    if not all(k in creds for k in ("username", "password", "host")):
        raise RuntimeError("MYSQL RO credentials missing in .env (or env vars).")
    return creds


def _connect():
    c = _load_mysql_creds()
    return pymysql.connect(
        host=c["host"],
        user=c["username"],
        password=c["password"],
        database="reference_data",
        connect_timeout=15,
        read_timeout=60,
    )


def _derive_symbol(row: dict) -> str:
    """Human-readable display ticker: `{BASE}-PERP`. The full ccxt id is
    preserved separately on each output row for technical reconciliation
    so we don't lose precision — the picker just needs a clean label."""
    base = (row.get("baseAsset") or "").strip().upper()
    if base:
        return f"{base}-PERP"
    for key in ("instrumentSymbolExternal", "instrumentSymbolInternal", "ccxtId"):
        v = row.get(key)
        if v and str(v).strip():
            return str(v).strip()
    return f"INSTRUMENT-{row.get('id')}"


def main() -> int:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            # Pull only what the booking form needs. The contract type is
            # collapsed to "PERP" since v1 ships perps only — DATED can be
            # un-gated later via a separate sync.
            cur.execute(
                """
                SELECT id, venueName, instrumentSymbolExternal, instrumentSymbolInternal,
                       ccxtId, baseAsset, quoteAsset, settlementAsset,
                       contractSize, contractLeverage
                  FROM instrument_spot_derivatives
                 WHERE deletedAt IS NULL
                   AND status = 'ACTIVE'
                   AND instrumentType = 'FUTURES - PERPETUAL'
                   AND venueName IS NOT NULL
                   AND baseAsset IS NOT NULL
                """
            )
            cols = [d[0] for d in cur.description]
            raw = [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        conn.close()

    out: list[dict] = []
    for r in raw:
        contract_size = r.get("contractSize")
        leverage = r.get("contractLeverage")
        out.append({
            "id": r.get("id"),
            "venue": (r.get("venueName") or "").strip(),
            "type": "PERP",
            "symbol": _derive_symbol(r),
            "base": (r.get("baseAsset") or "").strip().upper(),
            "quote": (r.get("quoteAsset") or "").strip().upper() or None,
            "settlement": (r.get("settlementAsset") or "").strip().upper() or None,
            "contract_size": float(contract_size) if contract_size is not None else 1.0,
            "max_leverage": float(leverage) if leverage is not None else None,
            "ccxt_id": (r.get("ccxtId") or None),
        })

    # Stable ordering: venue → symbol → id so JSON diffs stay readable.
    out.sort(key=lambda x: ((x["venue"] or "").upper(), (x["symbol"] or "").upper(), x["id"] or 0))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "count": len(out), "out": str(OUT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
