# Blotter CSV Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a server-side CSV export of all live cashflow + spot trades in the user-specified 18-column blotter layout, downloadable from the Deal Enquiry view.

**Architecture:** One pure-logic transforms module (`scripts/export_csv.py`) + one DB-touching script (`scripts/export_blotter.py`) that returns `{ok, csv, row_count}` JSON; one Node route `GET /api/exports/blotter.csv` that pipes the CSV string into a `text/csv` attachment response; one new "Download Full Blotter" button in Deal Enquiry that hits the route with current date-range filters. No enrichment pipeline — at ~3000 live rows the query + transform runs in <1s.

**Tech Stack:** Python 3 (psycopg2), Node 20 http server, React 19. Postgres `middle_office.trades_cashflow` + `trades_spot` are SCD2; live rows = `effective_end IS NULL`; "Input Date" = `MIN(effective_start) GROUP BY deal_ref`.

**Column spec (locked):**

| # | Header | Cashflow source | Spot source (per exploded leg) |
|---|--------|-----------------|--------------------------------|
| 1 | Input Date | `MIN(effective_start)` per `deal_ref` | same |
| 2 | Month Year | `MMMM YYYY` from `trade_date` UTC | same |
| 3 | Deal Reference | `deal_ref` | `deal_ref` (repeated across legs) |
| 4 | Portfolio | `portfolio_id` | `portfolio_id` |
| 5 | Portfolio Name | `portfolio_name` | `portfolio_name` |
| 6 | Counterparty | `counterparty` (resolved to name when `cashflow_type = INTER PTF FUNDING`) | `counterparty` |
| 7 | Txn Type | `txn_type` (= `CASHFLOW`) | `SPOT` |
| 8 | Trade Type | `cashflow_type` | `LONG` or `SHORT` (from `direction`) |
| 9 | Asset | `asset` | leg asset (`base_asset` / `quote_asset` / `fee_asset`) |
| 10 | Amount | `amount` signed: INCOMING +, OUTGOING − | leg amount signed per LONG/SHORT rules |
| 11 | Fee Asset | `fee_asset` | empty on base/quote legs; `fee_asset` on fee leg |
| 12 | Fee Amount | `fee_amount` (absolute) | empty on base/quote legs; `fee_amount` on fee leg |
| 13 | Trade Date | `trade_date` | `trade_date` |
| 14 | Value Date | `value_date` | `value_date` |
| 15 | Account | `account` | `account` |
| 16 | Account Type | `account_type` | `account_type` |
| 17 | TXID/REFERENCE | `txid_reference` | `txid_reference` |
| 18 | Comment | `comment` | `comment` |

Spot explosion (per locked spec):
- LONG `BTC/USDT 0.5 @ 70000 fee 17.5 USDT` → 3 rows: `(BTC, +0.5)`, `(USDT, -35000)`, `(USDT, -17.5)` fee row.
- SHORT same trade → `(BTC, -0.5)`, `(USDT, +35000)`, `(USDT, -17.5)` fee row.
- Fee row emitted only when `fee_amount > 0`.

---

### Task 0: Pure-logic CSV transforms module + tests

**Goal:** New `scripts/export_csv.py` exposing pure functions for column header list, cashflow → blotter row, spot → 1-3 blotter rows, INTER PTF FUNDING counterparty name lookup, month-year formatting, CSV serialization. All unit-tested without DB.

**Files:**
- Create: `trade-booking/scripts/export_csv.py`
- Create: `trade-booking/tests/test_export_csv.py`

**Acceptance Criteria:**
- [ ] `BLOTTER_COLUMNS` matches the 18-column spec exactly
- [ ] `cashflow_to_row(payload, *, portfolios)` returns one dict keyed by header
- [ ] Cashflow `direction='INCOMING'` → +amount; `'OUTGOING'` → -amount
- [ ] When `cashflow_type='INTER PTF FUNDING'`, counterparty (a portfolio number string) is resolved to portfolio name via `portfolios` lookup; non-matches fall back to raw value
- [ ] `spot_to_rows(payload)` returns list of 2-3 dicts; LONG/SHORT signs correct
- [ ] Fee row omitted when `fee_amount` is None / 0 / ""
- [ ] `fmt_month_year("2026-05-19T08:42:00+00:00") == "May 2026"`; handles None → ""
- [ ] `serialize_csv(rows)` produces CRLF lines with proper quoting; empty rows → header-only

**Verify:** `cd trade-booking && bash scripts/test_python.sh` → tests in `test_export_csv.py` pass.

**Steps:**

- [ ] **Step 1: Write failing tests**

Create `trade-booking/tests/test_export_csv.py`:

```python
"""Tests for trade-booking/scripts/export_csv.py — pure-logic functions only."""
from __future__ import annotations
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import export_csv  # noqa: E402


# Fixture: minimal portfolios.json shape (the few keys we use)
PORTFOLIOS = [
    {"number": 8000, "name": "TOKKA LABS - MM PMM - RFQ"},
    {"number": 8041, "name": "TOKKA LABS - ALPHA"},
]


def _cashflow(**overrides):
    base = {
        "deal_ref": "MCF-1",
        "first_effective_start": "2026-05-10T09:00:00+00:00",
        "txn_type": "CASHFLOW",
        "cashflow_type": "TRANSFER",
        "direction": "INCOMING",
        "portfolio_id": "8041",
        "portfolio_name": "TOKKA LABS - ALPHA",
        "counterparty": "Coinbase",
        "asset": "USDT",
        "amount": "1000",
        "fee_asset": "USDT",
        "fee_amount": "1",
        "trade_date": "2026-05-19T08:42:00+00:00",
        "value_date": "2026-05-19T08:42:00+00:00",
        "account": "Coinbase · prime · main",
        "account_type": "BROKERAGE",
        "txid_reference": None,
        "comment": None,
    }
    base.update(overrides)
    return base


def _spot(**overrides):
    base = {
        "deal_ref": "MFX-7",
        "first_effective_start": "2026-05-19T08:42:00+00:00",
        "txn_type": "SPOT",
        "direction": "LONG",
        "portfolio_id": "8041",
        "portfolio_name": "TOKKA LABS - ALPHA",
        "counterparty": "Binance",
        "account": "Binance · spot · tk006",
        "account_type": "EXCHANGE",
        "base_asset": "BTC",
        "base_amount": "0.5",
        "quote_asset": "USDT",
        "quote_amount": "35000",
        "price": "70000",
        "fee_asset": "USDT",
        "fee_amount": "17.5",
        "trade_date": "2026-05-19T08:42:00+00:00",
        "value_date": "2026-05-19T08:42:00+00:00",
        "txid_reference": None,
        "comment": None,
    }
    base.update(overrides)
    return base


# ── §1: Column spec ──────────────────────────────────────────────

def test_blotter_columns_match_spec_exactly():
    assert export_csv.BLOTTER_COLUMNS == (
        "Input Date", "Month Year", "Deal Reference", "Portfolio",
        "Portfolio Name", "Counterparty", "Txn Type", "Trade Type",
        "Asset", "Amount", "Fee Asset", "Fee Amount",
        "Trade Date", "Value Date", "Account", "Account Type",
        "TXID/REFERENCE", "Comment",
    )


# ── §2: Month-year format ────────────────────────────────────────

def test_fmt_month_year_iso_with_tz():
    assert export_csv.fmt_month_year("2026-05-19T08:42:00+00:00") == "May 2026"


def test_fmt_month_year_none_returns_empty():
    assert export_csv.fmt_month_year(None) == ""


def test_fmt_month_year_garbage_returns_empty():
    assert export_csv.fmt_month_year("not a date") == ""


# ── §3: Cashflow → row ───────────────────────────────────────────

def test_cashflow_incoming_amount_positive():
    row = export_csv.cashflow_to_row(_cashflow(direction="INCOMING", amount="1000"),
                                     portfolios=PORTFOLIOS)
    assert row["Amount"] == "1000"


def test_cashflow_outgoing_amount_negative():
    row = export_csv.cashflow_to_row(_cashflow(direction="OUTGOING", amount="1000"),
                                     portfolios=PORTFOLIOS)
    assert row["Amount"] == "-1000"


def test_cashflow_outgoing_already_negative_left_alone():
    # Defensive: if DB ever stores a signed amount, don't double-flip.
    row = export_csv.cashflow_to_row(_cashflow(direction="OUTGOING", amount="-1000"),
                                     portfolios=PORTFOLIOS)
    assert row["Amount"] == "-1000"


def test_cashflow_input_date_uses_first_effective_start():
    row = export_csv.cashflow_to_row(
        _cashflow(first_effective_start="2026-05-10T09:00:00+00:00",
                  effective_start="2026-05-20T11:00:00+00:00"),
        portfolios=PORTFOLIOS,
    )
    assert row["Input Date"] == "2026-05-10T09:00:00+00:00"


def test_cashflow_txn_type_and_trade_type():
    row = export_csv.cashflow_to_row(_cashflow(cashflow_type="REBATE"),
                                     portfolios=PORTFOLIOS)
    assert row["Txn Type"] == "CASHFLOW"
    assert row["Trade Type"] == "REBATE"


def test_cashflow_inter_ptf_funding_counterparty_resolved_to_name():
    row = export_csv.cashflow_to_row(
        _cashflow(cashflow_type="INTER PTF FUNDING", counterparty="8000"),
        portfolios=PORTFOLIOS,
    )
    assert row["Counterparty"] == "TOKKA LABS - MM PMM - RFQ"


def test_cashflow_inter_ptf_funding_unknown_portfolio_falls_back():
    row = export_csv.cashflow_to_row(
        _cashflow(cashflow_type="INTER PTF FUNDING", counterparty="9999"),
        portfolios=PORTFOLIOS,
    )
    assert row["Counterparty"] == "9999"


def test_cashflow_non_inter_ptf_counterparty_untouched():
    row = export_csv.cashflow_to_row(
        _cashflow(cashflow_type="TRANSFER", counterparty="Coinbase"),
        portfolios=PORTFOLIOS,
    )
    assert row["Counterparty"] == "Coinbase"


def test_cashflow_all_expected_keys_present():
    row = export_csv.cashflow_to_row(_cashflow(), portfolios=PORTFOLIOS)
    assert set(row.keys()) == set(export_csv.BLOTTER_COLUMNS)


# ── §4: Spot → rows ──────────────────────────────────────────────

def test_spot_long_explodes_to_three_rows():
    rows = export_csv.spot_to_rows(_spot(direction="LONG"))
    assert len(rows) == 3
    assert (rows[0]["Asset"], rows[0]["Amount"]) == ("BTC", "0.5")
    assert (rows[1]["Asset"], rows[1]["Amount"]) == ("USDT", "-35000")
    assert (rows[2]["Asset"], rows[2]["Amount"]) == ("USDT", "-17.5")


def test_spot_short_explodes_with_flipped_signs_but_fee_stays_negative():
    rows = export_csv.spot_to_rows(_spot(direction="SHORT"))
    assert len(rows) == 3
    assert (rows[0]["Asset"], rows[0]["Amount"]) == ("BTC", "-0.5")
    assert (rows[1]["Asset"], rows[1]["Amount"]) == ("USDT", "35000")
    assert (rows[2]["Asset"], rows[2]["Amount"]) == ("USDT", "-17.5")


def test_spot_no_fee_drops_fee_row():
    rows = export_csv.spot_to_rows(_spot(fee_amount=None, fee_asset=None))
    assert len(rows) == 2


def test_spot_zero_fee_drops_fee_row():
    rows = export_csv.spot_to_rows(_spot(fee_amount="0"))
    assert len(rows) == 2


def test_spot_trade_type_is_direction():
    rows = export_csv.spot_to_rows(_spot(direction="LONG"))
    assert all(r["Trade Type"] == "LONG" for r in rows)


def test_spot_all_rows_share_deal_ref_and_input_date():
    rows = export_csv.spot_to_rows(_spot())
    assert {r["Deal Reference"] for r in rows} == {"MFX-7"}
    assert {r["Input Date"] for r in rows} == {"2026-05-19T08:42:00+00:00"}


def test_spot_base_quote_legs_have_empty_fee_columns():
    rows = export_csv.spot_to_rows(_spot())
    assert rows[0]["Fee Asset"] == "" and rows[0]["Fee Amount"] == ""
    assert rows[1]["Fee Asset"] == "" and rows[1]["Fee Amount"] == ""


def test_spot_fee_row_carries_fee_asset_and_amount():
    rows = export_csv.spot_to_rows(_spot())
    assert rows[2]["Fee Asset"] == "USDT"
    assert rows[2]["Fee Amount"] == "17.5"


# ── §5: CSV serialization ────────────────────────────────────────

def test_serialize_csv_emits_header_only_for_empty_rows():
    out = export_csv.serialize_csv([])
    lines = out.splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("Input Date,Month Year,Deal Reference,")


def test_serialize_csv_quotes_comma_in_value():
    row = {h: "" for h in export_csv.BLOTTER_COLUMNS}
    row["Comment"] = "hello, world"
    out = export_csv.serialize_csv([row])
    assert '"hello, world"' in out


def test_serialize_csv_quotes_newline_in_value():
    row = {h: "" for h in export_csv.BLOTTER_COLUMNS}
    row["Comment"] = "line 1\nline 2"
    out = export_csv.serialize_csv([row])
    assert '"line 1\nline 2"' in out


def test_serialize_csv_one_full_row_round_trips():
    import csv as _csv
    import io
    row = export_csv.cashflow_to_row(_cashflow(), portfolios=PORTFOLIOS)
    out = export_csv.serialize_csv([row])
    rows = list(_csv.DictReader(io.StringIO(out)))
    assert len(rows) == 1
    assert rows[0]["Deal Reference"] == "MCF-1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd trade-booking && bash scripts/test_python.sh tests/test_export_csv.py`
Expected: ImportError or AttributeError — `export_csv` module doesn't exist yet.

- [ ] **Step 3: Implement export_csv.py**

Create `trade-booking/scripts/export_csv.py`:

```python
"""Pure-logic helpers for the blotter CSV export.

Transforms a live cashflow / spot row payload (as produced by
cashflow_db.row_to_payload / spot_db.row_to_payload) into the 18-column
blotter shape requested by the MO team. Strict separation from DB / IO
so each transform has direct unit-test coverage.

Used by scripts/export_blotter.py (the DB-touching wrapper).
"""
from __future__ import annotations
import csv
import io
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable, Sequence


BLOTTER_COLUMNS: tuple[str, ...] = (
    "Input Date",
    "Month Year",
    "Deal Reference",
    "Portfolio",
    "Portfolio Name",
    "Counterparty",
    "Txn Type",
    "Trade Type",
    "Asset",
    "Amount",
    "Fee Asset",
    "Fee Amount",
    "Trade Date",
    "Value Date",
    "Account",
    "Account Type",
    "TXID/REFERENCE",
    "Comment",
)


_MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def fmt_month_year(iso: str | None) -> str:
    """Return e.g. 'May 2026' from an ISO timestamp; '' on None / bad input."""
    if not iso:
        return ""
    try:
        # Postgres TIMESTAMPTZ renders as '2026-05-19 08:42:00+00' or
        # ISO 8601 — strptime needs separators normalized. Use fromisoformat
        # which accepts both 'T' and ' ' separators in Py 3.11+.
        normalized = str(iso).replace(" ", "T")
        d = datetime.fromisoformat(normalized)
    except (ValueError, TypeError):
        return ""
    return f"{_MONTH_NAMES[d.month - 1]} {d.year}"


def _sign_amount(amount, direction: str, *, positive: str, negative: str) -> str:
    """Return amount as a string with sign applied per direction.

    `positive` and `negative` are the direction labels that mean
    add and subtract respectively (e.g. INCOMING/OUTGOING for cashflow,
    LONG/SHORT for spot base leg). If the raw value is already negative
    we leave it alone — never double-flip.
    """
    if amount in (None, ""):
        return ""
    try:
        d = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        return str(amount)
    if d == 0:
        return "0"
    abs_d = abs(d)
    if direction == positive:
        return _decimal_str(abs_d)
    if direction == negative:
        return _decimal_str(-abs_d)
    return _decimal_str(d)


def _decimal_str(d: Decimal) -> str:
    """Render a Decimal without exponent notation and without trailing zeros."""
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s if s else "0"


def _str_or_empty(v) -> str:
    if v is None:
        return ""
    return str(v)


def _resolve_inter_ptf_counterparty(raw, portfolios: Sequence[dict]) -> str:
    """Look up portfolio name when counterparty is a portfolio number.

    Returns the name on hit, the raw value on miss. portfolios entries
    are expected to be {'number': int, 'name': str}.
    """
    if raw is None:
        return ""
    try:
        target = int(str(raw).strip())
    except (ValueError, AttributeError):
        return str(raw)
    for p in portfolios:
        if int(p.get("number", -1)) == target:
            return str(p.get("name", raw))
    return str(raw)


def cashflow_to_row(payload: dict, *, portfolios: Sequence[dict]) -> dict:
    """Map one live cashflow payload to a single blotter row."""
    cf_type = payload.get("cashflow_type") or ""
    counterparty_raw = payload.get("counterparty")
    if cf_type == "INTER PTF FUNDING":
        counterparty = _resolve_inter_ptf_counterparty(counterparty_raw, portfolios)
    else:
        counterparty = _str_or_empty(counterparty_raw)

    return {
        "Input Date":       _str_or_empty(payload.get("first_effective_start")),
        "Month Year":       fmt_month_year(payload.get("trade_date")),
        "Deal Reference":   _str_or_empty(payload.get("deal_ref")),
        "Portfolio":        _str_or_empty(payload.get("portfolio_id")),
        "Portfolio Name":   _str_or_empty(payload.get("portfolio_name")),
        "Counterparty":     counterparty,
        "Txn Type":         _str_or_empty(payload.get("txn_type")),
        "Trade Type":       cf_type,
        "Asset":            _str_or_empty(payload.get("asset")),
        "Amount":           _sign_amount(payload.get("amount"),
                                         payload.get("direction") or "",
                                         positive="INCOMING", negative="OUTGOING"),
        "Fee Asset":        _str_or_empty(payload.get("fee_asset")),
        "Fee Amount":       _str_or_empty(payload.get("fee_amount")),
        "Trade Date":       _str_or_empty(payload.get("trade_date")),
        "Value Date":       _str_or_empty(payload.get("value_date")),
        "Account":          _str_or_empty(payload.get("account")),
        "Account Type":     _str_or_empty(payload.get("account_type")),
        "TXID/REFERENCE":   _str_or_empty(payload.get("txid_reference")),
        "Comment":          _str_or_empty(payload.get("comment")),
    }


def _spot_common(payload: dict) -> dict:
    """Columns that are identical across every spot leg of one trade."""
    return {
        "Input Date":       _str_or_empty(payload.get("first_effective_start")),
        "Month Year":       fmt_month_year(payload.get("trade_date")),
        "Deal Reference":   _str_or_empty(payload.get("deal_ref")),
        "Portfolio":        _str_or_empty(payload.get("portfolio_id")),
        "Portfolio Name":   _str_or_empty(payload.get("portfolio_name")),
        "Counterparty":     _str_or_empty(payload.get("counterparty")),
        "Txn Type":         "SPOT",
        "Trade Type":       _str_or_empty(payload.get("direction")),
        "Trade Date":       _str_or_empty(payload.get("trade_date")),
        "Value Date":       _str_or_empty(payload.get("value_date")),
        "Account":          _str_or_empty(payload.get("account")),
        "Account Type":     _str_or_empty(payload.get("account_type")),
        "TXID/REFERENCE":   _str_or_empty(payload.get("txid_reference")),
        "Comment":          _str_or_empty(payload.get("comment")),
    }


def spot_to_rows(payload: dict) -> list[dict]:
    """Explode a spot trade into 2 (no fee) or 3 (with fee) blotter rows."""
    direction = payload.get("direction") or ""
    common = _spot_common(payload)

    base = {
        **common,
        "Asset":      _str_or_empty(payload.get("base_asset")),
        "Amount":     _sign_amount(payload.get("base_amount"), direction,
                                   positive="LONG", negative="SHORT"),
        "Fee Asset":  "",
        "Fee Amount": "",
    }
    quote = {
        **common,
        "Asset":      _str_or_empty(payload.get("quote_asset")),
        "Amount":     _sign_amount(payload.get("quote_amount"), direction,
                                   positive="SHORT", negative="LONG"),
        "Fee Asset":  "",
        "Fee Amount": "",
    }
    rows = [base, quote]

    fee_amount = payload.get("fee_amount")
    if fee_amount not in (None, "", 0, "0"):
        try:
            if Decimal(str(fee_amount)) != 0:
                fee = {
                    **common,
                    "Asset":      _str_or_empty(payload.get("fee_asset")),
                    "Amount":     _sign_amount(payload.get("fee_amount"), "OUTGOING",
                                               positive="INCOMING", negative="OUTGOING"),
                    "Fee Asset":  _str_or_empty(payload.get("fee_asset")),
                    "Fee Amount": _str_or_empty(payload.get("fee_amount")),
                }
                rows.append(fee)
        except (InvalidOperation, TypeError, ValueError):
            pass

    return rows


def serialize_csv(rows: Iterable[dict]) -> str:
    """Serialize rows (dicts keyed by BLOTTER_COLUMNS) to a CSV string."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(BLOTTER_COLUMNS),
                            quoting=csv.QUOTE_MINIMAL, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    return buf.getvalue()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd trade-booking && bash scripts/test_python.sh tests/test_export_csv.py`
Expected: all green.

- [ ] **Step 5: Run flake8**

Run: `cd trade-booking && bash scripts/lint_python.sh`
Expected: passes (max-line-length=88, the project's standing rules from `feedback_trade_booking_flake8`).

- [ ] **Step 6: Commit**

```bash
cd "C:\Users\peter\OneDrive\Desktop\Claude\trade-booking"
git add scripts/export_csv.py tests/test_export_csv.py
git commit -m "feat: pure-logic transforms for blotter CSV export"
```

---

### Task 1: DB-querying export script (export_blotter.py)

**Goal:** New `scripts/export_blotter.py` reads `{from, to, type, portfolio_ids}` from stdin, queries `trades_cashflow` + `trades_spot` live rows (with `first_effective_start` subquery), passes each through `export_csv` transforms, returns `{ok, csv, row_count}` JSON envelope.

**Files:**
- Create: `trade-booking/scripts/export_blotter.py`

**Acceptance Criteria:**
- [ ] Stdin params: `from` / `to` (ISO date or datetime strings, optional), `type` (`all`|`cashflow`|`spot`, default `all`), `portfolio_ids` (list[str], optional)
- [ ] `from`/`to` filter on `trade_date` (inclusive on both ends)
- [ ] `portfolio_ids` filters on `portfolio_id` (TEXT column)
- [ ] Loads `public/refdata/portfolios.json` once, passes to `cashflow_to_row` for INTER PTF FUNDING name resolution
- [ ] Joins cashflow + spot output, sorted by `trade_date DESC, deal_ref DESC`
- [ ] Emits `{ok: true, csv: "...", row_count: N}` on success
- [ ] Exit codes match project convention: 0 ok, 2 invalid JSON, 3 bad params, 5 DB error

**Verify:** `echo '{}' | python trade-booking/scripts/export_blotter.py | python -c "import json,sys; d=json.load(sys.stdin); print(d['row_count'], 'rows'); print(d['csv'][:500])"` returns valid CSV.

**Steps:**

- [ ] **Step 1: Implement the script**

Create `trade-booking/scripts/export_blotter.py`:

```python
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
        raise ValueError(f"type must be one of {sorted(VALID_TYPES)}, got {out['type']!r}")
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
```

- [ ] **Step 2: Smoke test against UAT**

Run: `echo '{}' | python trade-booking/scripts/export_blotter.py | python -c "import json,sys; d=json.load(sys.stdin); print(d.get('row_count'), 'rows'); print((d.get('csv') or '')[:600])"`

Expected: prints a row count + a CSV header line starting with `Input Date,Month Year,Deal Reference,…` followed by some rows.

If `row_count` is suspiciously low, sanity-check with a type filter:
`echo '{"type":"spot"}' | python trade-booking/scripts/export_blotter.py | python -c "import json,sys; print(json.load(sys.stdin)['row_count'])"`

- [ ] **Step 3: Smoke test param validation**

Run: `echo '{"type":"bogus"}' | python trade-booking/scripts/export_blotter.py`
Expected: `{"ok": false, "error": "type must be one of ['all', 'cashflow', 'spot'], got 'bogus'"}` and exit code 3.

Run: `echo 'not json' | python trade-booking/scripts/export_blotter.py`
Expected: `{"ok": false, "error": "invalid JSON on stdin", ...}` exit code 2.

- [ ] **Step 4: Run flake8**

Run: `cd trade-booking && bash scripts/lint_python.sh`
Expected: passes.

- [ ] **Step 5: Commit**

```bash
cd "C:\Users\peter\OneDrive\Desktop\Claude\trade-booking"
git add scripts/export_blotter.py
git commit -m "feat: export_blotter.py — query live trades + emit blotter CSV"
```

---

### Task 2: Node server route `GET /api/exports/blotter.csv`

**Goal:** Wire `GET /api/exports/blotter.csv` in `server.js` — auth-gated like other routes, shells to `export_blotter.py` via `spawnPython`, writes CSV body with `Content-Disposition: attachment` header.

**Files:**
- Modify: `trade-booking/server.js` — three edits:
  1. Add `EXPORT_BLOTTER_SCRIPT` const next to other export consts (around line 34)
  2. Add route handler (place AFTER spot routes around line 900, BEFORE the SPA catch-all at line 901)
  3. Add a `/help` log line in startup output near line 951

**Acceptance Criteria:**
- [ ] Auth-gated (returns 401 if no session — the existing middleware at line ~397 handles this for any `/api/*` route)
- [ ] Accepts query params: `from`, `to`, `type`, `portfolio` (repeatable for multi-select)
- [ ] Returns `Content-Type: text/csv; charset=utf-8`
- [ ] Returns `Content-Disposition: attachment; filename="blotter_<from>_<to>.csv"`
- [ ] Filename defaults: missing `from` → `all`, missing `to` → today (YYYY-MM-DD UTC)
- [ ] On script error returns JSON `{ok:false,error}` body with 5xx status

**Steps:**

- [ ] **Step 1: Add script constant**

In `server.js`, after the existing `SPOT_*_SCRIPT` consts (around line 34), add:

```javascript
const EXPORT_BLOTTER_SCRIPT = resolve(__dirname, "scripts", "export_blotter.py");
```

- [ ] **Step 2: Add route handler**

In `server.js`, find the line just before the SPA fallback comment (`// Unknown routes (SPA navigation) get index.html`, around line 901) and insert the new handler immediately above it:

```javascript
  // GET /api/exports/blotter.csv?from=&to=&type=&portfolio=...
  // Streams a CSV download of live cashflow + spot trades in the
  // 18-column MO blotter layout. Spot trades are exploded into 2-3
  // per-asset legs; INTER PTF FUNDING counterparties are resolved to
  // portfolio names. See scripts/export_blotter.py for the contract.
  // HEAD is accepted so the UI can probe for errors before triggering
  // the actual download (so users see in-page errors, not a broken file).
  if ((req.method === "GET" || req.method === "HEAD") && req.url.startsWith("/api/exports/blotter.csv")) {
    const url = new URL(req.url, "http://localhost");
    const from = url.searchParams.get("from") || null;
    const to   = url.searchParams.get("to")   || null;
    const type = (url.searchParams.get("type") || "all").toLowerCase();
    const portfolioIds = url.searchParams.getAll("portfolio").filter(Boolean);
    const stdin = JSON.stringify({
      from, to, type,
      portfolio_ids: portfolioIds,
    });
    const t0 = Date.now();
    const { code, json, stderr } = await spawnPython(EXPORT_BLOTTER_SCRIPT, stdin);
    if (stderr) console.error(`[exports:err] ${stderr.trim()}`);
    if (code !== 0 || !json || json.ok !== true) {
      res.statusCode = httpStatusFor(code, json);
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(json || { ok: false, error: "export failed" }));
      return;
    }
    const today = new Date().toISOString().slice(0, 10);
    const fromTag = (from || "all").slice(0, 10);
    const toTag = (to || today).slice(0, 10);
    const filename = `blotter_${fromTag}_${toTag}.csv`;
    console.log(`[exports] blotter ${json.row_count} rows (${Date.now() - t0}ms)`);
    res.statusCode = 200;
    res.setHeader("Content-Type", "text/csv; charset=utf-8");
    res.setHeader("Content-Disposition", `attachment; filename="${filename}"`);
    // UTF-8 BOM so Excel opens the file in the correct codepage. Matches
    // the client-side downloadCsv helper convention in TradeBookingForm.jsx.
    res.end("﻿" + json.csv);
    return;
  }
```

- [ ] **Step 3: Add /help log line**

In `server.js` around line 951 (where the other endpoint help lines are printed at startup), add:

```javascript
  console.log(`[server]   GET  /api/exports/blotter.csv  — full blotter CSV (cashflow + spot)`);
```

Place it after the existing spot recent line at line 951.

- [ ] **Step 4: Smoke test the server**

```powershell
cd C:\Users\peter\OneDrive\Desktop\Claude\trade-booking
node server.js
```

In another terminal:
```powershell
# Without auth — should 401
curl.exe -i "http://localhost:5181/api/exports/blotter.csv?type=spot"

# With auth — replace <SID> with a valid session cookie value taken from your browser
curl.exe -i -b "sid=<SID>" "http://localhost:5181/api/exports/blotter.csv?type=spot" -o spot.csv
```

Expected: first call → 401 JSON; second → 200 with `Content-Type: text/csv` and `Content-Disposition: attachment; filename="blotter_all_<today>.csv"`. Open `spot.csv` and confirm the header row matches `Input Date,Month Year,Deal Reference,...`.

- [ ] **Step 5: Smoke test the date+portfolio filter**

```powershell
curl.exe -b "sid=<SID>" "http://localhost:5181/api/exports/blotter.csv?from=2026-05-01&to=2026-05-25&portfolio=8041&portfolio=8000" -o range.csv
```

Expected: 200 download, CSV scoped to those portfolios within the date range. Filename `blotter_2026-05-01_2026-05-25.csv`.

- [ ] **Step 6: Commit**

```bash
cd "C:\Users\peter\OneDrive\Desktop\Claude\trade-booking"
git add server.js
git commit -m "feat: GET /api/exports/blotter.csv route"
```

---

### Task 3: UI — Deal Enquiry "Download Full Blotter" button

**Goal:** Add a "Download Full Blotter" button to the Deal Enquiry view, next to the existing "Export CSV" button. Pulls current `trade_date_from` / `trade_date_to` filters, calls `/api/exports/blotter.csv`, triggers download. Existing client-side `exportCsv` (limited to 20 loaded rows) stays untouched.

**Files:**
- Modify: `trade-booking/src/TradeBookingForm.jsx`
  - Add `downloadBlotter` callback near `exportCsv` (around line 4323)
  - Add a button next to the existing CSV export button in the Deal Enquiry header

**Acceptance Criteria:**
- [ ] New button labeled "Download Full Blotter"
- [ ] Reads `filters.trade_date_from` / `filters.trade_date_to` (already maintained by the view's filter UI)
- [ ] Builds query string with `from` / `to` if set, omits them otherwise
- [ ] Triggers download by setting `window.location.href` (CSV endpoint returns attachment headers, so the browser will save instead of navigate)
- [ ] Disabled while a previous click is in flight (basic guard via local state)
- [ ] On non-200 response, sets the existing `error` state so the in-page banner shows
- [ ] Existing "Export CSV" button + handler unchanged

**Steps:**

- [ ] **Step 1: Locate the existing exportCsv call site**

Open `trade-booking/src/TradeBookingForm.jsx` and find this block around line 4323:

```javascript
  const exportCsv = useCallback(() => {
    const csv = rowsToCsv(filteredRows, DEAL_CSV_COLUMNS);
    downloadCsv(`deal-enquiry-${todayStampLocal()}.csv`, csv);
  }, [filteredRows]);
```

This is inside the DealEnquiry component. Find the button that currently invokes `exportCsv` (search for `onClick={exportCsv}` near the DealEnquiry header — it's near the toolbar around the search/filter area).

- [ ] **Step 2: Add the new callback right below exportCsv**

Insert immediately after the `exportCsv` definition:

```javascript
  const [downloadingBlotter, setDownloadingBlotter] = useState(false);
  const downloadBlotter = useCallback(async () => {
    if (downloadingBlotter) return;
    setDownloadingBlotter(true);
    setError(null);
    try {
      const qs = new URLSearchParams();
      const from = (filters.trade_date_from || "").slice(0, 10);
      const to   = (filters.trade_date_to   || "").slice(0, 10);
      if (from) qs.set("from", from);
      if (to) qs.set("to", to);
      qs.set("type", "all");
      // HEAD request first so we surface errors in-page instead of showing
      // the user a download dialog full of error JSON.
      const probe = await api(`/api/exports/blotter.csv?${qs.toString()}`,
                              { method: "HEAD" });
      if (!probe.ok) {
        let detail = `HTTP ${probe.status}`;
        try {
          const body = await probe.text();
          if (body) detail += ` — ${body.slice(0, 200)}`;
        } catch { /* ignore */ }
        throw new Error(detail);
      }
      // Trigger the actual download via a transient <a download> click.
      const a = document.createElement("a");
      a.href = `/api/exports/blotter.csv?${qs.toString()}`;
      a.rel = "noopener";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    } catch (e) {
      setError(`Blotter download failed: ${String(e.message || e)}`);
    } finally {
      setDownloadingBlotter(false);
    }
  }, [filters.trade_date_from, filters.trade_date_to, downloadingBlotter]);
```

- [ ] **Step 3: Add the button next to the existing Export CSV button**

The existing Export CSV button is at `src/TradeBookingForm.jsx:4432-4445` (`onClick={exportCsv}` rendered as `↓ CSV`). Insert this sibling button immediately AFTER it (after line 4445, before the closing `</div>` at line 4446):

```jsx
            <button
              type="button"
              onClick={downloadBlotter}
              disabled={downloadingBlotter}
              title="Download all live trades from the database in the MO blotter format (cashflow + spot legs)"
              className="text-[10px] tracking-[0.22em] uppercase transition-colors"
              style={{
                background: "transparent",
                color: downloadingBlotter ? "#cdc8bb" : "#1f1f1f",
                border: "none",
                padding: "4px 0",
                cursor: downloadingBlotter ? "wait" : "pointer",
              }}
            >{downloadingBlotter ? "↓ PREPARING…" : "↓ FULL BLOTTER"}</button>
```

The styling exactly mirrors the existing `↓ CSV` button — same className, same transparent background, same padding — so the two buttons line up visually as siblings in the toolbar.

- [ ] **Step 4: Verify HEAD probe works**

Task 2 already set the route to accept GET and HEAD. Confirm by running the dev server and:

```powershell
curl.exe -X HEAD -b "sid=<SID>" "http://localhost:5181/api/exports/blotter.csv?type=all" -i
```

Expected: 200 with `Content-Type: text/csv` and the `Content-Disposition` header, no body.

- [ ] **Step 5: Manual UI test**

Start vite + node:
```powershell
cd C:\Users\peter\OneDrive\Desktop\Claude\trade-booking
npm run dev
# in another terminal:
node server.js
```

Open the app in the browser, log in, navigate to Deal Enquiry:
1. Click "Download Full Blotter" with no date range set → CSV downloads named `blotter_all_<today>.csv` containing all live trades
2. Set a date range, click again → CSV scoped to range, filename reflects from/to
3. Open the downloaded CSV in Excel — confirm header row is `Input Date,Month Year,Deal Reference,Portfolio,Portfolio Name,Counterparty,Txn Type,Trade Type,Asset,Amount,Fee Asset,Fee Amount,Trade Date,Value Date,Account,Account Type,TXID/REFERENCE,Comment`
4. Confirm spot trades show 2-3 rows per deal_ref with signed amounts
5. Force an error: kill the python interpreter so script spawn fails → in-page error banner shows the failure instead of a broken download

- [ ] **Step 6: Commit**

```bash
cd "C:\Users\peter\OneDrive\Desktop\Claude\trade-booking"
git add src/TradeBookingForm.jsx server.js
git commit -m "feat: Deal Enquiry Download Full Blotter button"
```

---

### Task 4: Lint, version bump, commit

**Goal:** Run final lint+test pass, bump version per project convention, single chore commit.

**Files:**
- Modify: `trade-booking/version.yml` (via `scripts/update_version.py`)

**Acceptance Criteria:**
- [ ] `bash scripts/lint_python.sh` passes
- [ ] `bash scripts/test_python.sh` passes (includes new tests)
- [ ] `python scripts/update_version.py` bumps `version.yml`
- [ ] Chore commit lands on top of the three feature commits

**Steps:**

- [ ] **Step 1: Lint everything**

```bash
cd "C:\Users\peter\OneDrive\Desktop\Claude\trade-booking"
bash scripts/lint_python.sh
```
Expected: clean exit. Per `feedback_trade_booking_flake8`: no one-liner defs, no aligned `=`, single space after commas.

- [ ] **Step 2: Run the test suite**

```bash
cd "C:\Users\peter\OneDrive\Desktop\Claude\trade-booking"
bash scripts/test_python.sh
```
Expected: all green, including the new `test_export_csv.py`.

- [ ] **Step 3: Bump version**

```bash
cd "C:\Users\peter\OneDrive\Desktop\Claude\trade-booking"
python scripts/update_version.py
```
Expected: `version.yml` updated. Per `project_trade_booking_version_bump`, this is required for any push to main since ECR tag immutability gates the build.

- [ ] **Step 4: Commit version bump**

```bash
cd "C:\Users\peter\OneDrive\Desktop\Claude\trade-booking"
git add version.yml
git commit -m "chore: bump version for blotter CSV export"
```

- [ ] **Step 5: Final check**

```bash
git log --oneline -5
```
Expected: 4 commits in order:
1. `feat: pure-logic transforms for blotter CSV export`
2. `feat: export_blotter.py — query live trades + emit blotter CSV`
3. `feat: GET /api/exports/blotter.csv route` (or combined with the UI commit)
4. `feat: Deal Enquiry Download Full Blotter button`
5. `chore: bump version for blotter CSV export`
