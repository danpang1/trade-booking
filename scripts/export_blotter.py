"""Build a blotter CSV from live cashflow + spot rows.

Reads `{"from": "...", "to": "...", "type": "all|cashflow|spot",
       "portfolio_ids": ["8041", ...]}` from stdin (all optional).
Writes {"ok": true, "csv": "...", "row_count": N} to stdout.

Manual smoke:
    echo '{}' | python3 trade-booking/scripts/export_blotter.py
    echo '{"type":"spot"}' | python3 trade-booking/scripts/export_blotter.py
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import cashflow_db
import spot_db
import export_csv


REPO = Path(__file__).resolve().parents[1]
PORTFOLIOS_JSON = REPO / "public" / "refdata" / "portfolios.json"

VALID_TYPES = {"all", "cashflow", "spot"}


def _load_portfolios() -> list[dict]:
    if not PORTFOLIOS_JSON.exists():
        return []
    try:
        return json.loads(PORTFOLIOS_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _parse_params(raw: str) -> dict:
    params = json.loads(raw or "{}")
    if not isinstance(params, dict):
        raise ValueError("stdin must be a JSON object")
    out = {
        "from": params.get("from") or None,
        "to": params.get("to") or None,
        "type": (params.get("type") or "all").lower(),
        "portfolio_ids": params.get("portfolio_ids") or [],
    }
    if out["type"] not in VALID_TYPES:
        raise ValueError(
            f"type must be one of {sorted(VALID_TYPES)}, got {out['type']!r}"
        )
    if not isinstance(out["portfolio_ids"], list):
        raise ValueError("portfolio_ids must be a list of strings")
    out["portfolio_ids"] = [str(p) for p in out["portfolio_ids"] if str(p).strip()]
    return out


def _where_clause(params: dict, alias: str = "t") -> tuple[str, list]:
    clauses = [f"{alias}.effective_end IS NULL"]
    args: list = []
    if params["from"]:
        clauses.append(f"{alias}.trade_date >= %s")
        args.append(params["from"])
    if params["to"]:
        clauses.append(f"{alias}.trade_date <= %s")
        args.append(params["to"])
    if params["portfolio_ids"]:
        placeholders = ",".join(["%s"] * len(params["portfolio_ids"]))
        clauses.append(f"{alias}.portfolio_id IN ({placeholders})")
        args.extend(params["portfolio_ids"])
    return " AND ".join(clauses), args


def _fetch_cashflows(params: dict) -> list[dict]:
    where, args = _where_clause(params)
    sql = (
        "SELECT t.*, "
        "       (SELECT MIN(effective_start) FROM trades_cashflow "
        "         WHERE deal_ref = t.deal_ref) AS first_effective_start "
        "  FROM trades_cashflow t "
        f" WHERE {where} "
        " ORDER BY t.trade_date DESC, t.deal_ref DESC"
    )
    conn = cashflow_db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            cols = [d.name for d in cur.description]
            return [cashflow_db.row_to_payload(cols, r) for r in cur.fetchall()]
    finally:
        conn.close()


def _fetch_spots(params: dict) -> list[dict]:
    where, args = _where_clause(params)
    sql = (
        "SELECT t.*, "
        "       (SELECT MIN(effective_start) FROM trades_spot "
        "         WHERE deal_ref = t.deal_ref) AS first_effective_start "
        "  FROM trades_spot t "
        f" WHERE {where} "
        " ORDER BY t.trade_date DESC, t.deal_ref DESC"
    )
    conn = spot_db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            cols = [d.name for d in cur.description]
            return [spot_db.row_to_payload(cols, r) for r in cur.fetchall()]
    finally:
        conn.close()


def _build_rows(params: dict, portfolios: list[dict]) -> list[dict]:
    rows: list[dict] = []
    if params["type"] in ("all", "cashflow"):
        for cf in _fetch_cashflows(params):
            rows.append(export_csv.cashflow_to_row(cf, portfolios=portfolios))
    if params["type"] in ("all", "spot"):
        for sp in _fetch_spots(params):
            rows.extend(export_csv.spot_to_rows(sp))
    # Stable secondary sort by trade_date desc — spot legs preserve their
    # order from spot_to_rows (base, quote, fee) which is meaningful.
    rows.sort(key=lambda r: r.get("Trade Date", ""), reverse=True)
    return rows


def main() -> int:
    raw = sys.stdin.read().strip()
    try:
        params = _parse_params(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": "invalid JSON on stdin", "detail": str(e)}))
        return 2
    except ValueError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 3

    portfolios = _load_portfolios()
    try:
        rows = _build_rows(params, portfolios)
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5

    csv_text = export_csv.serialize_csv(rows)
    print(json.dumps({"ok": True, "csv": csv_text, "row_count": len(rows)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
