# Cashflow Booking Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the existing Trade Booking cashflow form to UAT Postgres — book new rows, amend/cancel existing ones, and list recent live rows for a Deal Enquiry view.

**Architecture:** Node server (`trade-booking/server.js`, port 5181) gains four endpoints that each spawn a small single-purpose Python script. The scripts share a `cashflow_db.py` helper for creds/validation/(de)serialization, then run their SQL via `psycopg2`. Bitemporal SCD2 amendments use an atomic `UPDATE ... WHERE effective_end IS NULL RETURNING` to avoid TOCTOU. Frontend swaps the Deal Enquiry placeholder for a real component and adds amend-mode state to the booking form.

**Tech Stack:** Node (HTTP, child_process spawn), Python 3 + `psycopg2`, Postgres (UAT, `trades_cashflow` already deployed), React 19 + Vite.

**Spec reference:** `docs/superpowers/specs/2026-05-15-cashflow-booking-backend-design.md`.

**Test strategy:**
- **Pure-logic helpers** (`validate_payload`, `payload_to_columns`, `row_to_payload`) — pytest unit tests under `tests/trade_booking/`, no DB.
- **DB-touching scripts** (`cashflow_insert.py` etc.) — manual smoke commands against UAT documented at end of each task. Mocking psycopg2 to "test" raw SQL would give false confidence in SCD2 race semantics; we test those with real Postgres.
- **Frontend** — manual browser checklist in the final task.

---

## File Structure

**New files:**
- `trade-booking/scripts/cashflow_db.py` — shared helper (creds, validation, (de)serialization).
- `trade-booking/scripts/cashflow_insert.py` — INSERT (with mirror-leg support).
- `trade-booking/scripts/cashflow_amend.py` — atomic close + reinsert (cancel path too).
- `trade-booking/scripts/cashflow_recent.py` — list recent live rows.
- `trade-booking/scripts/cashflow_get.py` — fetch one live row by `deal_ref`.
- `tests/trade_booking/__init__.py` — empty.
- `tests/trade_booking/test_cashflow_db.py` — pytest tests for the helper.

**Modified files:**
- `trade-booking/server.js` — add `spawnPython` helper + 4 routes.
- `trade-booking/src/TradeBookingForm.jsx` — `SubmitFeedback`, `ConflictModal`, `amendingDealRef` state, `payloadToFormState` helper, `handleSubmit` rewrite, `DealEnquiry` component replacing the placeholder, amend-mode submit-button label.
- `trade-booking/docs/cashflow-schema-mapping.md` — append API contract section.

---

## Task 1: Add the shared Python helper skeleton — `load_creds` and `connect`

**Files:**
- Create: `trade-booking/scripts/cashflow_db.py`
- Create: `tests/trade_booking/__init__.py`
- Create: `tests/trade_booking/test_cashflow_db.py`

- [ ] **Step 1: Create empty test package init**

Create file `tests/trade_booking/__init__.py` with no content.

- [ ] **Step 2: Write the failing test for `load_creds`**

Create `tests/trade_booking/test_cashflow_db.py`:

```python
"""Tests for trade-booking/scripts/cashflow_db.py — pure-logic functions only.
DB-touching scripts (cashflow_insert, cashflow_amend, etc.) are smoke-tested
manually against UAT; see their docstrings.
"""
from pathlib import Path
import sys

# Make the trade-booking scripts importable
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "trade-booking" / "scripts"))

import cashflow_db  # noqa: E402


def test_load_creds_parses_mo_db_uat_block(tmp_path: Path, monkeypatch):
    fake_env = tmp_path / ".env"
    fake_env.write_text(
        "# Some other section\n"
        "key: value\n"
        "\n"
        "# MO DB UAT\n"
        "host: db.example.com\n"
        "port: 5432\n"
        "database: mo_uat\n"
        "username: app\n"
        "password: secret\n"
        "\n"
        "# Another section after\n"
        "other: thing\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cashflow_db, "ENV", fake_env)
    c = cashflow_db.load_creds()
    assert c == {
        "host": "db.example.com",
        "port": "5432",
        "database": "mo_uat",
        "username": "app",
        "password": "secret",
    }
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /Users/weiyiao/Projects/nxgen-mo-tools && pytest tests/trade_booking/test_cashflow_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cashflow_db'`.

- [ ] **Step 4: Create `cashflow_db.py` with `load_creds` and `connect`**

Create `trade-booking/scripts/cashflow_db.py`:

```python
"""Shared helper for cashflow_insert/amend/recent/get scripts.

Pure logic (validation, (de)serialization) lives here for unit testing.
DB-touching scripts call into here for creds + connection.
"""
from __future__ import annotations
from pathlib import Path
import psycopg2

REPO = Path(__file__).resolve().parents[2]
ENV = REPO / ".env"


def load_creds() -> dict[str, str]:
    """Parse the #MO DB UAT block from <repo>/.env.

    Same convention as apply_schema_cashflow.py — block starts at the
    `# MO DB UAT` marker and ends at the next `#` comment that isn't the
    marker or at EOF.
    """
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
            creds[k.strip().lower()] = v.strip()
    return creds


def connect():
    """Open a psycopg2 connection. Caller manages txns (autocommit=False)."""
    c = load_creds()
    return psycopg2.connect(
        host=c["host"],
        port=int(c.get("port", "5432")),
        dbname=c["database"],
        user=c["username"],
        password=c["password"],
        connect_timeout=15,
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/weiyiao/Projects/nxgen-mo-tools && pytest tests/trade_booking/test_cashflow_db.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add trade-booking/scripts/cashflow_db.py tests/trade_booking/__init__.py tests/trade_booking/test_cashflow_db.py
git commit -m "feat(trade-booking): cashflow_db helper — load_creds + connect"
```

---

## Task 2: `validate_payload` for INSERT mode

**Files:**
- Modify: `trade-booking/scripts/cashflow_db.py` (add `ValidationError`, `validate_payload`)
- Modify: `tests/trade_booking/test_cashflow_db.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/trade_booking/test_cashflow_db.py`:

```python
import pytest


def _valid_insert_payload() -> dict:
    return {
        "deal_ref": "MCF-PLACEHOLDER",          # ignored on insert
        "external_trade_id": None,
        "cashflow_type": "FUNDING IN",
        "direction": "RECEIVE",
        "entity": "TK006",
        "portfolio_id": 8006,
        "portfolio_name": "CDA",
        "counterparty": "Galaxy",
        "account": "WALLET_CDA_EVM_04",
        "account_type": "WALLET",
        "asset": "USDC",
        "amount": "1000000",
        "fee_asset": None,
        "fee_amount": "0",
        "trade_date": "2026-05-15T12:00:00Z",
        "value_date": "2026-05-15T12:00:00Z",
        "network": "BSC",
        "txid_reference": None,
        "user_id": "adam",
        "status": "CONFIRMED",
        "comment": None,
    }


def test_validate_insert_accepts_valid_payload():
    p = _valid_insert_payload()
    cashflow_db.validate_payload(p, mode="insert")  # no raise


def test_validate_insert_rejects_missing_required():
    p = _valid_insert_payload()
    p["asset"] = None
    with pytest.raises(cashflow_db.ValidationError, match="asset"):
        cashflow_db.validate_payload(p, mode="insert")


def test_validate_insert_rejects_bad_direction():
    p = _valid_insert_payload()
    p["direction"] = "SEND"
    with pytest.raises(cashflow_db.ValidationError, match="direction"):
        cashflow_db.validate_payload(p, mode="insert")


def test_validate_insert_rejects_bad_status():
    p = _valid_insert_payload()
    p["status"] = "DRAFT"
    with pytest.raises(cashflow_db.ValidationError, match="status"):
        cashflow_db.validate_payload(p, mode="insert")


def test_validate_insert_rejects_non_numeric_amount():
    p = _valid_insert_payload()
    p["amount"] = "not-a-number"
    with pytest.raises(cashflow_db.ValidationError, match="amount"):
        cashflow_db.validate_payload(p, mode="insert")


def test_validate_insert_accepts_mirror_leg_array():
    a = _valid_insert_payload()
    b = _valid_insert_payload()
    b["direction"] = "PAY"
    cashflow_db.validate_payload([a, b], mode="insert")  # no raise


def test_validate_insert_rejects_mirror_leg_wrong_length():
    a = _valid_insert_payload()
    with pytest.raises(cashflow_db.ValidationError, match="mirror"):
        cashflow_db.validate_payload([a], mode="insert")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/weiyiao/Projects/nxgen-mo-tools && pytest tests/trade_booking/test_cashflow_db.py -v`
Expected: 7 new tests FAIL with `AttributeError: module 'cashflow_db' has no attribute 'ValidationError'` / `validate_payload`.

- [ ] **Step 3: Implement `ValidationError` and `validate_payload`**

Append to `trade-booking/scripts/cashflow_db.py`:

```python
from decimal import Decimal, InvalidOperation

REQUIRED_FIELDS_INSERT = (
    "cashflow_type", "direction", "entity", "portfolio_id",
    "portfolio_name", "asset", "amount", "trade_date", "value_date",
    "user_id", "status",
)
REQUIRED_FIELDS_AMEND = REQUIRED_FIELDS_INSERT + ("deal_ref",)

VALID_DIRECTIONS = {"RECEIVE", "PAY"}
VALID_STATUSES = {"PENDING", "CONFIRMED", "PROCESSED", "SETTLED", "CANCELLED"}


class ValidationError(ValueError):
    """Payload failed pre-DB validation. Raised before opening a txn."""


def _validate_one(p: dict, mode: str) -> None:
    required = REQUIRED_FIELDS_AMEND if mode == "amend" else REQUIRED_FIELDS_INSERT
    for f in required:
        v = p.get(f)
        if v is None or (isinstance(v, str) and not v.strip()):
            raise ValidationError(f"required field missing or empty: {f}")
    if p["direction"] not in VALID_DIRECTIONS:
        raise ValidationError(
            f"direction must be one of {sorted(VALID_DIRECTIONS)}, got {p['direction']!r}"
        )
    if p["status"] not in VALID_STATUSES:
        raise ValidationError(
            f"status must be one of {sorted(VALID_STATUSES)}, got {p['status']!r}"
        )
    try:
        Decimal(str(p["amount"]))
    except (InvalidOperation, TypeError, ValueError) as e:
        raise ValidationError(f"amount must be numeric, got {p['amount']!r}") from e
    if p.get("fee_amount") not in (None, "", 0):
        try:
            Decimal(str(p["fee_amount"]))
        except (InvalidOperation, TypeError, ValueError) as e:
            raise ValidationError(
                f"fee_amount must be numeric if set, got {p['fee_amount']!r}"
            ) from e
    try:
        int(p["portfolio_id"])
    except (TypeError, ValueError) as e:
        raise ValidationError(
            f"portfolio_id must be integer, got {p['portfolio_id']!r}"
        ) from e


def validate_payload(payload, *, mode: str) -> None:
    """Raise ValidationError if payload is bad. mode in {'insert', 'amend'}.

    On insert the payload may be a 2-element list (mirror-leg). On amend
    only a single dict is supported (mirror legs are independent deal_refs).
    """
    if mode not in ("insert", "amend"):
        raise ValidationError(f"unknown mode: {mode}")
    if isinstance(payload, list):
        if mode != "insert":
            raise ValidationError("mirror-leg list only supported on insert mode")
        if len(payload) != 2:
            raise ValidationError(
                f"mirror-leg payload must have exactly 2 elements, got {len(payload)}"
            )
        for leg in payload:
            _validate_one(leg, mode)
        return
    if not isinstance(payload, dict):
        raise ValidationError(f"payload must be dict or 2-element list, got {type(payload).__name__}")
    _validate_one(payload, mode)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/weiyiao/Projects/nxgen-mo-tools && pytest tests/trade_booking/test_cashflow_db.py -v`
Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add trade-booking/scripts/cashflow_db.py tests/trade_booking/test_cashflow_db.py
git commit -m "feat(trade-booking): cashflow_db — validate_payload (insert + mirror-leg)"
```

---

## Task 3: `validate_payload` for AMEND mode

**Files:**
- Modify: `tests/trade_booking/test_cashflow_db.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/trade_booking/test_cashflow_db.py`:

```python
def _valid_amend_payload() -> dict:
    p = _valid_insert_payload()
    p["deal_ref"] = "MCF-42"   # amend identifies the row to close
    return p


def test_validate_amend_accepts_valid_payload():
    cashflow_db.validate_payload(_valid_amend_payload(), mode="amend")  # no raise


def test_validate_amend_rejects_missing_deal_ref():
    p = _valid_amend_payload()
    p["deal_ref"] = None
    with pytest.raises(cashflow_db.ValidationError, match="deal_ref"):
        cashflow_db.validate_payload(p, mode="amend")


def test_validate_amend_rejects_list_payload():
    a = _valid_amend_payload()
    with pytest.raises(cashflow_db.ValidationError, match="mirror"):
        cashflow_db.validate_payload([a, a], mode="amend")
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd /Users/weiyiao/Projects/nxgen-mo-tools && pytest tests/trade_booking/test_cashflow_db.py -v`
Expected: all 3 new tests PASS (the existing `_validate_one` logic already covers AMEND because we added `deal_ref` to `REQUIRED_FIELDS_AMEND` in Task 2).

If any FAIL, fix `validate_payload` so the mirror-leg branch raises a ValidationError mentioning "mirror" when `mode == "amend"`.

- [ ] **Step 3: Commit**

```bash
git add tests/trade_booking/test_cashflow_db.py
git commit -m "test(trade-booking): cover amend-mode validation paths"
```

---

## Task 4: `payload_to_columns` — frontend JSON → DB tuple

**Files:**
- Modify: `trade-booking/scripts/cashflow_db.py`
- Modify: `tests/trade_booking/test_cashflow_db.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/trade_booking/test_cashflow_db.py`:

```python
def test_payload_to_columns_orders_match_ddl():
    p = _valid_insert_payload()
    cols, vals = cashflow_db.payload_to_columns(p, deal_ref="MCF-42")
    # Column order MUST match apply_schema_cashflow.py DDL declaration
    # order. effective_start/effective_end are SQL expressions, NOT params.
    assert cols == (
        "deal_ref", "external_trade_id", "txn_type", "cashflow_type",
        "direction", "entity", "portfolio_id", "portfolio_name",
        "counterparty", "account", "account_type", "asset", "amount",
        "fee_asset", "fee_amount", "trade_date", "value_date", "network",
        "txid_reference", "user_id", "status", "comment",
    )
    # Values must align positionally with cols.
    assert vals[cols.index("deal_ref")] == "MCF-42"
    assert vals[cols.index("txn_type")] == "CASHFLOW"
    assert vals[cols.index("cashflow_type")] == "FUNDING IN"
    assert vals[cols.index("direction")] == "RECEIVE"
    assert vals[cols.index("portfolio_id")] == 8006
    assert vals[cols.index("amount")] == "1000000"
    assert vals[cols.index("fee_amount")] == "0"


def test_payload_to_columns_coerces_empty_strings_to_none():
    p = _valid_insert_payload()
    p["external_trade_id"] = ""
    p["txid_reference"] = ""
    cols, vals = cashflow_db.payload_to_columns(p, deal_ref="MCF-42")
    assert vals[cols.index("external_trade_id")] is None
    assert vals[cols.index("txid_reference")] is None


def test_payload_to_columns_defaults_fee_amount_zero():
    p = _valid_insert_payload()
    p["fee_amount"] = None
    cols, vals = cashflow_db.payload_to_columns(p, deal_ref="MCF-42")
    assert vals[cols.index("fee_amount")] == "0"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/weiyiao/Projects/nxgen-mo-tools && pytest tests/trade_booking/test_cashflow_db.py::test_payload_to_columns_orders_match_ddl tests/trade_booking/test_cashflow_db.py::test_payload_to_columns_coerces_empty_strings_to_none tests/trade_booking/test_cashflow_db.py::test_payload_to_columns_defaults_fee_amount_zero -v`
Expected: FAIL with `AttributeError: module 'cashflow_db' has no attribute 'payload_to_columns'`.

- [ ] **Step 3: Implement `payload_to_columns`**

Append to `trade-booking/scripts/cashflow_db.py`:

```python
# Column order matches apply_schema_cashflow.py DDL declaration.
# effective_start / effective_end are populated by SQL expressions in the
# INSERT statement (NOW() and NULL respectively), not by these tuples.
DATA_COLUMNS = (
    "deal_ref",
    "external_trade_id",
    "txn_type",
    "cashflow_type",
    "direction",
    "entity",
    "portfolio_id",
    "portfolio_name",
    "counterparty",
    "account",
    "account_type",
    "asset",
    "amount",
    "fee_asset",
    "fee_amount",
    "trade_date",
    "value_date",
    "network",
    "txid_reference",
    "user_id",
    "status",
    "comment",
)


def _coerce_str_or_none(v):
    if v is None:
        return None
    if isinstance(v, str) and not v.strip():
        return None
    return v


def payload_to_columns(payload: dict, *, deal_ref: str) -> tuple[tuple[str, ...], tuple]:
    """Convert form JSON to (column_names, values) tuples for INSERT.

    `deal_ref` is passed in (allocated from trade_seq_cashflow on insert,
    preserved from the payload on amend) — it isn't trusted from the
    frontend on insert.
    """
    vals = []
    for col in DATA_COLUMNS:
        if col == "deal_ref":
            vals.append(deal_ref)
        elif col == "txn_type":
            vals.append("CASHFLOW")
        elif col == "portfolio_id":
            vals.append(int(payload["portfolio_id"]))
        elif col == "fee_amount":
            v = payload.get("fee_amount")
            vals.append("0" if v in (None, "") else v)
        else:
            vals.append(_coerce_str_or_none(payload.get(col)))
    return DATA_COLUMNS, tuple(vals)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/weiyiao/Projects/nxgen-mo-tools && pytest tests/trade_booking/test_cashflow_db.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add trade-booking/scripts/cashflow_db.py tests/trade_booking/test_cashflow_db.py
git commit -m "feat(trade-booking): cashflow_db — payload_to_columns"
```

---

## Task 5: `row_to_payload` — DB row → frontend JSON

**Files:**
- Modify: `trade-booking/scripts/cashflow_db.py`
- Modify: `tests/trade_booking/test_cashflow_db.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/trade_booking/test_cashflow_db.py`:

```python
from datetime import datetime, timezone
from decimal import Decimal


def test_row_to_payload_serializes_types_for_json():
    # Simulate the row tuple as psycopg2 returns it from SELECT *
    # (column order = DDL order = DATA_COLUMNS + effective_start/effective_end inserted at idx 19 & 20)
    cols = cashflow_db.DATA_COLUMNS[:19] + ("effective_start", "effective_end") + cashflow_db.DATA_COLUMNS[19:]
    row = (
        "MCF-42",                # deal_ref
        None,                    # external_trade_id
        "CASHFLOW",              # txn_type
        "FUNDING IN",            # cashflow_type
        "RECEIVE",               # direction
        "TK006",                 # entity
        8006,                    # portfolio_id
        "CDA",                   # portfolio_name
        "Galaxy",                # counterparty
        "WALLET_CDA_EVM_04",     # account
        "WALLET",                # account_type
        "USDC",                  # asset
        Decimal("1000000"),      # amount
        None,                    # fee_asset
        Decimal("0"),            # fee_amount
        datetime(2026, 5, 15, 12, tzinfo=timezone.utc),  # trade_date
        datetime(2026, 5, 15, 12, tzinfo=timezone.utc),  # value_date
        "BSC",                   # network
        None,                    # txid_reference
        datetime(2026, 5, 15, 14, 23, 1, tzinfo=timezone.utc),  # effective_start
        None,                    # effective_end
        "adam",                  # user_id
        "CONFIRMED",             # status
        None,                    # comment
    )
    out = cashflow_db.row_to_payload(cols, row)
    assert out["deal_ref"] == "MCF-42"
    assert out["portfolio_id"] == 8006
    assert out["amount"] == "1000000"               # Decimal → string for JSON
    assert out["fee_amount"] == "0"
    assert out["trade_date"] == "2026-05-15T12:00:00+00:00"
    assert out["effective_start"] == "2026-05-15T14:23:01+00:00"
    assert out["effective_end"] is None
    assert out["counterparty"] == "Galaxy"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/weiyiao/Projects/nxgen-mo-tools && pytest tests/trade_booking/test_cashflow_db.py::test_row_to_payload_serializes_types_for_json -v`
Expected: FAIL with `AttributeError: module 'cashflow_db' has no attribute 'row_to_payload'`.

- [ ] **Step 3: Implement `row_to_payload`**

Append to `trade-booking/scripts/cashflow_db.py`:

```python
from datetime import datetime
from decimal import Decimal


def _json_safe(v):
    if isinstance(v, Decimal):
        return format(v.normalize(), "f") if v == v.to_integral_value() else str(v)
    if isinstance(v, datetime):
        return v.isoformat()
    return v


def row_to_payload(columns, row) -> dict:
    """Convert a psycopg2 row tuple to a JSON-safe dict keyed by column name.

    Decimal → string (preserves precision for amounts), datetime → ISO 8601.
    Caller passes the column list (e.g., from cursor.description or known SELECT order).
    """
    return {col: _json_safe(val) for col, val in zip(columns, row)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/weiyiao/Projects/nxgen-mo-tools && pytest tests/trade_booking/test_cashflow_db.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add trade-booking/scripts/cashflow_db.py tests/trade_booking/test_cashflow_db.py
git commit -m "feat(trade-booking): cashflow_db — row_to_payload (Decimal/datetime → JSON-safe)"
```

---

## Task 6: `cashflow_insert.py` — INSERT with mirror-leg support

**Files:**
- Create: `trade-booking/scripts/cashflow_insert.py`

- [ ] **Step 1: Implement the script**

Create `trade-booking/scripts/cashflow_insert.py`:

```python
"""Insert one or two (mirror-leg) cashflow rows.

Reads JSON payload from stdin. Writes JSON result to stdout:
  Success: {"ok": true, "rows": [<row JSON>, ...]}
  Failure: {"ok": false, "error": "...", "detail": "..."}  (with non-zero exit)

Manual smoke (run against UAT):

    cd /Users/weiyiao/Projects/nxgen-mo-tools
    cat <<'EOF' | python3 trade-booking/scripts/cashflow_insert.py
    {
      "external_trade_id": "TEST-SMOKE-INS-001",
      "cashflow_type": "FUNDING IN",
      "direction": "RECEIVE",
      "entity": "TK006",
      "portfolio_id": 8006,
      "portfolio_name": "CDA",
      "counterparty": "Galaxy",
      "account": "WALLET_CDA_EVM_04",
      "account_type": "WALLET",
      "asset": "USDC",
      "amount": "1.00",
      "fee_asset": null,
      "fee_amount": "0",
      "trade_date": "2026-05-15T12:00:00+00:00",
      "value_date": "2026-05-15T12:00:00+00:00",
      "network": "BSC",
      "txid_reference": null,
      "user_id": "smoke",
      "status": "PENDING",
      "comment": "smoke test — safe to delete"
    }
    EOF

After verification:
    psql ... -c "DELETE FROM trades_cashflow WHERE external_trade_id LIKE 'TEST-SMOKE-INS-%';"
"""
from __future__ import annotations
import json
import sys

import cashflow_db


def _insert_one(cur, payload: dict) -> dict:
    cur.execute("SELECT nextval('trade_seq_cashflow')")
    n = cur.fetchone()[0]
    deal_ref = f"MCF-{n}"
    cols, vals = cashflow_db.payload_to_columns(payload, deal_ref=deal_ref)
    # Build INSERT: data columns + effective_start (NOW()) + effective_end (NULL)
    col_list = ", ".join(cols + ("effective_start", "effective_end"))
    placeholders = ", ".join(["%s"] * len(cols)) + ", NOW(), NULL"
    cur.execute(
        f"INSERT INTO trades_cashflow ({col_list}) VALUES ({placeholders}) RETURNING *",
        vals,
    )
    out_cols = [d.name for d in cur.description]
    return cashflow_db.row_to_payload(out_cols, cur.fetchone())


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": "invalid JSON on stdin", "detail": str(e)}))
        return 2
    try:
        cashflow_db.validate_payload(payload, mode="insert")
    except cashflow_db.ValidationError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 3
    legs = payload if isinstance(payload, list) else [payload]
    conn = cashflow_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                rows = [_insert_one(cur, leg) for leg in legs]
        print(json.dumps({"ok": True, "rows": rows}))
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run the smoke command against UAT**

Run the heredoc in the script's docstring (you must be on the VPN). Verify stdout looks like:

```json
{"ok": true, "rows": [{"deal_ref": "MCF-N", "external_trade_id": "TEST-SMOKE-INS-001", ...}]}
```

Then in psql, verify:

```sql
SELECT deal_ref, external_trade_id, asset, amount, effective_start, effective_end
  FROM trades_cashflow
 WHERE external_trade_id = 'TEST-SMOKE-INS-001';
```

Expected: 1 row, `effective_end` is NULL, `effective_start` is recent.

Clean up:

```sql
DELETE FROM trades_cashflow WHERE external_trade_id LIKE 'TEST-SMOKE-INS-%';
```

- [ ] **Step 3: Commit**

```bash
git add trade-booking/scripts/cashflow_insert.py
git commit -m "feat(trade-booking): cashflow_insert.py — INSERT with mirror-leg support"
```

---

## Task 7: `cashflow_amend.py` — atomic close + reinsert

**Files:**
- Create: `trade-booking/scripts/cashflow_amend.py`

- [ ] **Step 1: Implement the script**

Create `trade-booking/scripts/cashflow_amend.py`:

```python
"""Amend an existing cashflow row.

Atomic SCD2: UPDATE the current live row's effective_end (single
WHERE effective_end IS NULL → row-locks so concurrent amends serialize),
then INSERT a new version with the amended fields. Cancel is just amend
with status='CANCELLED'.

Reads JSON payload (single dict, deal_ref required) from stdin. Writes
JSON result to stdout:
  Success: {"ok": true, "rows": [<row JSON>]}
  Conflict (no live row): {"ok": false, "error": "<msg>", "code": "conflict"}  (exit 4)
  Validation: {"ok": false, "error": "..."} (exit 3)

Manual smoke (run against UAT after running cashflow_insert.py smoke first
and recording its deal_ref):

    DEAL=MCF-123  # replace with the deal_ref printed by insert smoke
    cat <<EOF | python3 trade-booking/scripts/cashflow_amend.py
    {
      "deal_ref": "$DEAL",
      "external_trade_id": "TEST-SMOKE-AMD-001",
      "cashflow_type": "FUNDING IN",
      "direction": "RECEIVE",
      "entity": "TK006",
      "portfolio_id": 8006,
      "portfolio_name": "CDA",
      "counterparty": "Galaxy",
      "account": "WALLET_CDA_EVM_04",
      "account_type": "WALLET",
      "asset": "USDC",
      "amount": "2.00",
      "fee_asset": null, "fee_amount": "0",
      "trade_date": "2026-05-15T12:00:00+00:00",
      "value_date": "2026-05-15T12:00:00+00:00",
      "network": "BSC", "txid_reference": null,
      "user_id": "smoke", "status": "CONFIRMED",
      "comment": "amend smoke"
    }
    EOF

Verify in psql:
    SELECT deal_ref, amount, status, effective_start, effective_end
      FROM trades_cashflow WHERE deal_ref='MCF-123' ORDER BY effective_start;
Expected: 2 rows. First has effective_end stamped; second has effective_end NULL and amount=2.00.
"""
from __future__ import annotations
import json
import sys

import cashflow_db


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": "invalid JSON on stdin", "detail": str(e)}))
        return 2
    try:
        cashflow_db.validate_payload(payload, mode="amend")
    except cashflow_db.ValidationError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 3
    if isinstance(payload, list):
        print(json.dumps({"ok": False, "error": "amend takes a single record, not a list"}))
        return 3
    deal_ref = payload["deal_ref"]
    cols, vals = cashflow_db.payload_to_columns(payload, deal_ref=deal_ref)

    conn = cashflow_db.connect()
    try:
        with conn:
            with conn.cursor() as cur:
                # Atomically close the live row.
                cur.execute(
                    "UPDATE trades_cashflow SET effective_end = NOW() "
                    "WHERE deal_ref = %s AND effective_end IS NULL "
                    "RETURNING deal_ref",
                    (deal_ref,),
                )
                if cur.fetchone() is None:
                    print(json.dumps({
                        "ok": False,
                        "error": f"{deal_ref} has no live row (already amended or never existed)",
                        "code": "conflict",
                    }))
                    return 4
                # Insert the new version. deal_ref preserved; new effective window.
                col_list = ", ".join(cols + ("effective_start", "effective_end"))
                placeholders = ", ".join(["%s"] * len(cols)) + ", NOW(), NULL"
                cur.execute(
                    f"INSERT INTO trades_cashflow ({col_list}) "
                    f"VALUES ({placeholders}) RETURNING *",
                    vals,
                )
                out_cols = [d.name for d in cur.description]
                row = cashflow_db.row_to_payload(out_cols, cur.fetchone())
        print(json.dumps({"ok": True, "rows": [row]}))
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run the amend smoke against UAT**

First, insert a smoke row using Task 6's heredoc. Record the printed `deal_ref` (e.g., `MCF-N`).

Then run the amend smoke (substitute `MCF-N` into the heredoc) per the docstring. Verify in psql the two-row history. Then run the amend a *second* time on the same `deal_ref` — verify a third row appears, the second row's `effective_end` gets stamped, and the third row is live.

Test the conflict path: change the JSON's `deal_ref` to `MCF-DOES-NOT-EXIST` and run again. Expected stdout: `{"ok": false, "error": "MCF-DOES-NOT-EXIST has no live row ...", "code": "conflict"}` and exit code 4.

Clean up: `DELETE FROM trades_cashflow WHERE external_trade_id LIKE 'TEST-SMOKE-%';`

- [ ] **Step 3: Commit**

```bash
git add trade-booking/scripts/cashflow_amend.py
git commit -m "feat(trade-booking): cashflow_amend.py — atomic SCD2 close + reinsert"
```

---

## Task 8: `cashflow_recent.py` — list recent live rows

**Files:**
- Create: `trade-booking/scripts/cashflow_recent.py`

- [ ] **Step 1: Implement the script**

Create `trade-booking/scripts/cashflow_recent.py`:

```python
"""List the N most recent live cashflow rows for the Deal Enquiry view.

Reads `{"limit": N}` from stdin (default 20, max 200).
Writes {"ok": true, "rows": [...]} to stdout.

Manual smoke:
    echo '{"limit": 5}' | python3 trade-booking/scripts/cashflow_recent.py
"""
from __future__ import annotations
import json
import sys

import cashflow_db


def main() -> int:
    raw = sys.stdin.read().strip() or "{}"
    try:
        params = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": "invalid JSON on stdin", "detail": str(e)}))
        return 2
    try:
        limit = int(params.get("limit", 20))
    except (TypeError, ValueError):
        print(json.dumps({"ok": False, "error": "limit must be integer"}))
        return 3
    limit = max(1, min(200, limit))

    conn = cashflow_db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM trades_cashflow "
                "WHERE effective_end IS NULL "
                "ORDER BY trade_date DESC, deal_ref DESC "
                "LIMIT %s",
                (limit,),
            )
            cols = [d.name for d in cur.description]
            rows = [cashflow_db.row_to_payload(cols, r) for r in cur.fetchall()]
        print(json.dumps({"ok": True, "rows": rows}))
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run smoke against UAT**

```bash
echo '{"limit": 5}' | python3 trade-booking/scripts/cashflow_recent.py | python3 -m json.tool
```

Expected: JSON with `"ok": true` and `"rows"` (possibly empty if the table has no live rows yet). All rows should have `effective_end: null`.

- [ ] **Step 3: Commit**

```bash
git add trade-booking/scripts/cashflow_recent.py
git commit -m "feat(trade-booking): cashflow_recent.py — list N most recent live rows"
```

---

## Task 9: `cashflow_get.py` — fetch one live row by deal_ref

**Files:**
- Create: `trade-booking/scripts/cashflow_get.py`

- [ ] **Step 1: Implement the script**

Create `trade-booking/scripts/cashflow_get.py`:

```python
"""Fetch the single live (effective_end IS NULL) row for one deal_ref.

Reads `{"deal_ref": "MCF-42"}` from stdin.
Writes {"ok": true, "rows": [<row>]} on hit, {"ok": false, "error": "...", "code": "not_found"} on miss (exit 4).
"""
from __future__ import annotations
import json
import sys

import cashflow_db


def main() -> int:
    raw = sys.stdin.read()
    try:
        params = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": "invalid JSON on stdin", "detail": str(e)}))
        return 2
    deal_ref = (params.get("deal_ref") or "").strip()
    if not deal_ref:
        print(json.dumps({"ok": False, "error": "deal_ref is required"}))
        return 3

    conn = cashflow_db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM trades_cashflow "
                "WHERE deal_ref = %s AND effective_end IS NULL",
                (deal_ref,),
            )
            row = cur.fetchone()
            if row is None:
                print(json.dumps({
                    "ok": False,
                    "error": f"no live row for {deal_ref}",
                    "code": "not_found",
                }))
                return 4
            cols = [d.name for d in cur.description]
            out = cashflow_db.row_to_payload(cols, row)
        print(json.dumps({"ok": True, "rows": [out]}))
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "error": "DB error", "detail": str(e)}))
        return 5
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run smoke against UAT**

Insert a row via Task 6 smoke, record its deal_ref, then:

```bash
echo '{"deal_ref": "MCF-N"}' | python3 trade-booking/scripts/cashflow_get.py | python3 -m json.tool
```

Then test the miss path:

```bash
echo '{"deal_ref": "MCF-DOES-NOT-EXIST"}' | python3 trade-booking/scripts/cashflow_get.py
```

Expected: `{"ok": false, "error": "...", "code": "not_found"}` and exit code 4.

Clean up: `DELETE FROM trades_cashflow WHERE external_trade_id LIKE 'TEST-SMOKE-%';`

- [ ] **Step 3: Commit**

```bash
git add trade-booking/scripts/cashflow_get.py
git commit -m "feat(trade-booking): cashflow_get.py — fetch one live row by deal_ref"
```

---

## Task 10: Wire the four endpoints into `server.js`

**Files:**
- Modify: `trade-booking/server.js`

- [ ] **Step 1: Add the `spawnPython` helper and routes**

Open `trade-booking/server.js`. After the existing `runSnapshotOnce` function (~line 53), add the spawn helper. Modify the HTTP handler (currently `const server = createServer(async (req, res) => { ... })` at line 83) to add the new routes BEFORE the final 404 fallback.

Find this section in `server.js`:

```js
const SNAPSHOT_SCRIPT = resolve(__dirname, "scripts", "snapshot_tokens.py");
```

Add below it:

```js
const CASHFLOW_INSERT_SCRIPT = resolve(__dirname, "scripts", "cashflow_insert.py");
const CASHFLOW_AMEND_SCRIPT  = resolve(__dirname, "scripts", "cashflow_amend.py");
const CASHFLOW_RECENT_SCRIPT = resolve(__dirname, "scripts", "cashflow_recent.py");
const CASHFLOW_GET_SCRIPT    = resolve(__dirname, "scripts", "cashflow_get.py");
```

Then, just before the line `// ── HTTP server: serves /tokens.json ...` (~line 82), add:

```js
// Spawn a Python script, pipe stdinJson to its stdin, resolve to its
// parsed JSON stdout + exit code. Never throws — errors come back as
// { ok:false, error, detail } so the HTTP handler can map them cleanly.
function spawnPython(scriptPath, stdinJson) {
  return new Promise((resolveP) => {
    const proc = spawn(PYTHON, [scriptPath], { cwd: __dirname });
    let stdout = "";
    let stderr = "";
    proc.stdout.on("data", (d) => { stdout += d; });
    proc.stderr.on("data", (d) => { stderr += d; });
    proc.on("error", (e) => {
      resolveP({ code: -1, json: { ok: false, error: "spawn failed", detail: String(e) }, stderr });
    });
    proc.on("close", (code) => {
      let parsed;
      try { parsed = JSON.parse(stdout); }
      catch (e) {
        parsed = { ok: false, error: "non-JSON output from script", detail: stdout.slice(0, 500) };
      }
      resolveP({ code, json: parsed, stderr });
    });
    proc.stdin.end(stdinJson);
  });
}

// Read the full request body as a string.
function readBody(req) {
  return new Promise((resolveB, rejectB) => {
    let buf = "";
    req.on("data", (d) => { buf += d; });
    req.on("end", () => resolveB(buf));
    req.on("error", rejectB);
  });
}

// Map a Python exit code → HTTP status code.
function httpStatusFor(exitCode, json) {
  if (exitCode === 0) return 200;
  if (json && json.code === "conflict") return 409;
  if (json && json.code === "not_found") return 404;
  if (exitCode === 3) return 400;  // validation
  if (exitCode === 4) return 404;  // not_found (fallback if code missing)
  return 500;
}
```

Then in the HTTP handler — find the existing `if (req.url === "/tokens.json")` block (~line 108). The 404 fallback (`res.statusCode = 404; res.end("Not found");`) is at the very end. Insert these new route handlers BEFORE the 404 fallback:

```js
  // POST /api/cashflow/insert
  if (req.url === "/api/cashflow/insert" && req.method === "POST") {
    const body = await readBody(req);
    const t0 = Date.now();
    const { code, json, stderr } = await spawnPython(CASHFLOW_INSERT_SCRIPT, body);
    const dealRefs = (json && json.rows || []).map((r) => r.deal_ref).join(",");
    console.log(`[cashflow] insert ${dealRefs || "FAIL"} (${Date.now() - t0}ms, exit ${code})`);
    if (stderr) console.error(`[cashflow:err] ${stderr.trim()}`);
    res.statusCode = httpStatusFor(code, json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(json));
    return;
  }

  // POST /api/cashflow/amend
  if (req.url === "/api/cashflow/amend" && req.method === "POST") {
    const body = await readBody(req);
    const t0 = Date.now();
    const { code, json, stderr } = await spawnPython(CASHFLOW_AMEND_SCRIPT, body);
    const dealRef = (json && json.rows && json.rows[0] && json.rows[0].deal_ref) || "FAIL";
    console.log(`[cashflow] amend ${dealRef} (${Date.now() - t0}ms, exit ${code})`);
    if (stderr) console.error(`[cashflow:err] ${stderr.trim()}`);
    res.statusCode = httpStatusFor(code, json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(json));
    return;
  }

  // GET /api/cashflow/recent?limit=N
  if (req.method === "GET" && req.url.startsWith("/api/cashflow/recent")) {
    const url = new URL(req.url, "http://localhost");
    const limit = parseInt(url.searchParams.get("limit") || "20", 10);
    const stdin = JSON.stringify({ limit: Number.isNaN(limit) ? 20 : limit });
    const { code, json } = await spawnPython(CASHFLOW_RECENT_SCRIPT, stdin);
    res.statusCode = httpStatusFor(code, json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(json));
    return;
  }

  // GET /api/cashflow/:deal_ref  (must come AFTER /api/cashflow/recent so the more-specific route matches first)
  if (req.method === "GET" && /^\/api\/cashflow\/[^/]+$/.test(req.url)) {
    const dealRef = decodeURIComponent(req.url.split("/").pop());
    const stdin = JSON.stringify({ deal_ref: dealRef });
    const { code, json } = await spawnPython(CASHFLOW_GET_SCRIPT, stdin);
    res.statusCode = httpStatusFor(code, json);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(json));
    return;
  }
```

Also extend the `Access-Control-Allow-Origin` block so POST requests work cross-origin from the Vite dev server. Replace:

```js
  // CORS for the Vite dev server on a different port
  res.setHeader("Access-Control-Allow-Origin", "*");
```

With:

```js
  // CORS for the Vite dev server on a different port
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  if (req.method === "OPTIONS") {
    res.statusCode = 204;
    res.end();
    return;
  }
```

Finally, update the listen-banner at the bottom to mention the new routes. Find:

```js
  console.log(`[server]   POST /api/refresh    — force a re-snapshot`);
```

And add below:

```js
  console.log(`[server]   POST /api/cashflow/insert    — book new cashflow row(s)`);
  console.log(`[server]   POST /api/cashflow/amend     — amend an existing cashflow`);
  console.log(`[server]   GET  /api/cashflow/recent    — list N recent live rows`);
  console.log(`[server]   GET  /api/cashflow/:deal_ref — fetch one live row`);
```

- [ ] **Step 2: Restart server and exercise each route with curl**

Run in a terminal:

```bash
cd /Users/weiyiao/Projects/nxgen-mo-tools/trade-booking && node server.js
```

In a second terminal:

```bash
# Recent (should be 200 with empty or existing rows)
curl -s http://localhost:5181/api/cashflow/recent?limit=3 | python3 -m json.tool

# Insert a smoke row (replace fields as in Task 6 smoke)
curl -s -X POST http://localhost:5181/api/cashflow/insert \
  -H 'Content-Type: application/json' \
  -d '{"external_trade_id":"TEST-CURL-001","cashflow_type":"FUNDING IN","direction":"RECEIVE","entity":"TK006","portfolio_id":8006,"portfolio_name":"CDA","counterparty":"Galaxy","account":"WALLET_CDA_EVM_04","account_type":"WALLET","asset":"USDC","amount":"1.00","fee_amount":"0","trade_date":"2026-05-15T12:00:00+00:00","value_date":"2026-05-15T12:00:00+00:00","network":"BSC","user_id":"smoke","status":"PENDING"}' \
  | python3 -m json.tool

# Get by deal_ref (substitute the MCF-N from above)
curl -s http://localhost:5181/api/cashflow/MCF-N | python3 -m json.tool

# Amend (substitute MCF-N)
curl -s -X POST http://localhost:5181/api/cashflow/amend \
  -H 'Content-Type: application/json' \
  -d '{"deal_ref":"MCF-N","external_trade_id":"TEST-CURL-001","cashflow_type":"FUNDING IN","direction":"RECEIVE","entity":"TK006","portfolio_id":8006,"portfolio_name":"CDA","counterparty":"Galaxy","account":"WALLET_CDA_EVM_04","account_type":"WALLET","asset":"USDC","amount":"2.00","fee_amount":"0","trade_date":"2026-05-15T12:00:00+00:00","value_date":"2026-05-15T12:00:00+00:00","network":"BSC","user_id":"smoke","status":"CONFIRMED","comment":"amended via curl"}' \
  | python3 -m json.tool

# Confirm conflict — amend the same row twice rapidly. Second amend should return 200 (the first amend created a new live row that the second amend then closes); but trying to amend a non-existent ref should 404/409:
curl -s -X POST http://localhost:5181/api/cashflow/amend \
  -H 'Content-Type: application/json' \
  -d '{"deal_ref":"MCF-DOES-NOT-EXIST", ... }' -w "\nHTTP %{http_code}\n"
```

Expected: each command returns the right HTTP status (200 / 404 / 409 / 400 as designed). Server log shows `[cashflow] insert MCF-N` etc.

Clean up: `DELETE FROM trades_cashflow WHERE external_trade_id LIKE 'TEST-CURL-%';`

- [ ] **Step 3: Commit**

```bash
git add trade-booking/server.js
git commit -m "feat(trade-booking): server.js — 4 cashflow routes + spawnPython helper"
```

---

## Task 11: Add `SubmitFeedback` + `ConflictModal` UI primitives

**Files:**
- Modify: `trade-booking/src/TradeBookingForm.jsx`

- [ ] **Step 1: Add state slices and components**

Open `trade-booking/src/TradeBookingForm.jsx`. Find the existing `handleSubmit` function at line 2233. Just BEFORE that function, add the state slices:

```jsx
  // Booking submission feedback. Cleared when the form is edited again
  // or after ~4s on success.
  const [feedback, setFeedback] = useState(null);
  // null | { dealRef: string, message: string }
  const [conflictModal, setConflictModal] = useState(null);
  // null | "MCF-42"  — when set, form is in amend mode (PUT vs POST)
  const [amendingDealRef, setAmendingDealRef] = useState(null);
```

(`useState` is already in the React import at line 1 — `import React, { useState, useMemo, useEffect, useRef, useContext, createContext } from "react";`. No change needed there.)

Then, find where the submit button is rendered (line 3612 area — search for `onClick={handleSubmit}`). Add the `<SubmitFeedback />` block immediately ABOVE the submit-button container. Define the helper components inside the same file, just below the existing helpers (search for `const PlaceholderView` at the top — define both right after it):

```jsx
function SubmitFeedback({ feedback, onDismiss }) {
  if (!feedback) return null;
  const palette = {
    error:   { bg: "#fff0eb", text: "#7a1f00", border: "#e08a6a" },
    success: { bg: "#eef5e9", text: "#1f4a1f", border: "#7ea66a" },
  }[feedback.kind] || { bg: "#fff7e0", text: "#5a4400", border: "#d6b656" };
  return (
    <div
      className="px-3 py-2 mb-2 text-[12px]"
      style={{
        background: palette.bg,
        color: palette.text,
        border: `1px solid ${palette.border}`,
        fontFamily: "'IBM Plex Mono', ui-monospace, monospace",
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <span>{feedback.message}</span>
        <button
          type="button"
          onClick={onDismiss}
          className="opacity-60 hover:opacity-100"
        >×</button>
      </div>
      {feedback.detail && (
        <details className="mt-1 opacity-80">
          <summary className="cursor-pointer">detail</summary>
          <pre className="whitespace-pre-wrap text-[11px] mt-1">{feedback.detail}</pre>
        </details>
      )}
    </div>
  );
}

function ConflictModal({ open, dealRef, message, onReload, onClose }) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(0,0,0,0.45)" }}
    >
      <div
        className="px-6 py-5 max-w-md w-full"
        style={{
          background: "#f6f3ec",
          border: "1px solid #d9d4c7",
          fontFamily: "'IBM Plex Mono', ui-monospace, monospace",
        }}
      >
        <div className="text-[13px] font-medium mb-2">Booking already amended</div>
        <div className="text-[12px] mb-4">
          {message || `${dealRef} was amended by another session while you were editing it.`}
        </div>
        <div className="flex gap-2 justify-end">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1 text-[12px]"
            style={{ border: "1px solid #aaa" }}
          >Cancel</button>
          <button
            type="button"
            onClick={onReload}
            className="px-3 py-1 text-[12px]"
            style={{ background: "#1f1f1f", color: "#f2efe8" }}
          >Reload latest</button>
        </div>
      </div>
    </div>
  );
}
```

Now wire the rendering. Find `<button ... onClick={handleSubmit}` at line 3612 and insert directly above it (still inside the same wrapper div):

```jsx
              <SubmitFeedback feedback={feedback} onDismiss={() => setFeedback(null)} />
```

And at the very end of the form's outer JSX tree (just before the form's outermost closing tag — look for the last `</div>` of the main returned JSX), add:

```jsx
            <ConflictModal
              open={Boolean(conflictModal)}
              dealRef={conflictModal?.dealRef}
              message={conflictModal?.message}
              onClose={() => setConflictModal(null)}
              onReload={async () => {
                if (!conflictModal?.dealRef) return setConflictModal(null);
                await loadIntoForm(conflictModal.dealRef);
                setConflictModal(null);
              }}
            />
```

(`loadIntoForm` is added in Task 13. For now the Reload button will throw "loadIntoForm is not defined" — that's fine for this task; Task 13 closes the gap.)

- [ ] **Step 2: Verify it compiles and renders**

```bash
cd /Users/weiyiao/Projects/nxgen-mo-tools/trade-booking && npm run dev
```

Open http://localhost:5180 . Verify the form still loads. Then in the browser console:

```js
// Manually set feedback to see the banner render
// (Easiest: temporarily add `useEffect(() => setFeedback({kind:"error", message:"test"}), [])` to TradeBookingForm and reload.)
```

Or just verify the form renders without errors. Confirm React DevTools shows the new `feedback`, `conflictModal`, `amendingDealRef` state.

- [ ] **Step 3: Commit**

```bash
git add trade-booking/src/TradeBookingForm.jsx
git commit -m "feat(trade-booking): SubmitFeedback + ConflictModal + amend-mode state"
```

---

## Task 12: Rewrite `handleSubmit` to call the insert endpoint

**Files:**
- Modify: `trade-booking/src/TradeBookingForm.jsx`

- [ ] **Step 1: Replace `handleSubmit`**

In `TradeBookingForm.jsx`, replace the existing `handleSubmit` (line 2233) with:

```jsx
  const handleSubmit = async () => {
    if (!canSubmit) return;
    setFeedback(null);
    const endpoint = amendingDealRef
      ? "http://localhost:5181/api/cashflow/amend"
      : "http://localhost:5181/api/cashflow/insert";
    let res;
    try {
      res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(outputRecord),
      });
    } catch (e) {
      setFeedback({ kind: "error", message: "Server unreachable", detail: String(e) });
      return;
    }
    const result = await res.json().catch(() => ({ ok: false, error: "non-JSON server response" }));
    if (result.ok && result.rows && result.rows.length > 0) {
      setSubmittedRecord(result.rows.length === 1 ? result.rows[0] : result.rows);
      const verb = amendingDealRef ? "Updated" : "Booked";
      const ref = result.rows[0].deal_ref;
      setAmendingDealRef(null);
      setFeedback({ kind: "success", message: `${verb} ${ref}` });
      setTimeout(() => {
        setFeedback((f) => (f && f.kind === "success" ? null : f));
      }, 4000);
    } else if (res.status === 409) {
      setConflictModal({ dealRef: amendingDealRef, message: result.error });
    } else {
      setFeedback({ kind: "error", message: result.error || "Booking failed", detail: result.detail });
    }
  };
```

(Only the cashflow form currently submits via this path — SPOT/FUTURE/LOAN still produce JSON preview but don't book. The endpoint check assumes `form.category === "CASHFLOW"`. Add a guard at the top of `handleSubmit` so non-cashflow categories fall back to the old `setSubmittedRecord(outputRecord)` behavior:)

Insert this at the very top of the new `handleSubmit`, before `if (!canSubmit) return;`:

```jsx
    if (form.category !== "CASHFLOW") {
      // SPOT/FUTURE/LOAN: not wired to backend yet — keep the existing
      // JSON preview behavior so those forms still work.
      if (!canSubmit) return;
      setSubmittedRecord(outputRecord);
      return;
    }
```

- [ ] **Step 2: Manual browser test — fresh insert**

Restart the Vite dev server if needed (`npm run dev`). Make sure `node server.js` is also running.

- Open http://localhost:5180, switch to CASHFLOW category.
- Fill in valid fields (any portfolio, counterparty, asset = USDC, amount = 1, status = PENDING, comment = "test from UI").
- Click Submit.
- Expected: green "Booked MCF-N" banner appears above the submit button and clears after 4s. The right-hand JSON preview now shows the row returned by the backend (with the allocated `deal_ref`).

In psql verify the row landed:
```sql
SELECT deal_ref, asset, amount, comment, effective_start, effective_end
  FROM trades_cashflow ORDER BY effective_start DESC LIMIT 5;
```

Test a failure path: leave a required field empty, click Submit. Expected: red banner with the validation message.

Clean up the test row: `DELETE FROM trades_cashflow WHERE comment LIKE 'test from UI%';`

- [ ] **Step 3: Commit**

```bash
git add trade-booking/src/TradeBookingForm.jsx
git commit -m "feat(trade-booking): wire handleSubmit to POST /api/cashflow/insert"
```

---

## Task 13: `payloadToFormState` + `loadIntoForm` (amend wiring)

**Files:**
- Modify: `trade-booking/src/TradeBookingForm.jsx`

- [ ] **Step 1: Add the inverse mapping helper**

Open `TradeBookingForm.jsx`. The `outputRecord` memo at line 2006 forward-maps form state to DB shape. We need the inverse.

Find the existing `PORTFOLIOS` constant (line 101) — note the structure (each entry has at least a numeric id matching `portfolio_id`).

Just before the existing `handleSubmit` (now rewritten), add:

```jsx
  // Convert a backend cashflow row (mapping-doc shape) into the slice
  // of form state the cashflow tab consumes. Inverse of outputRecord
  // for category="CASHFLOW". Unknown fields are ignored.
  function payloadToFormState(row) {
    return {
      category: "CASHFLOW",
      trade_id: row.deal_ref,
      external_trade_id: row.external_trade_id || "",
      cf_type: row.cashflow_type,
      cf_direction: row.direction,
      portfolio: String(row.portfolio_id),
      counterparty: row.counterparty || "",
      account_name: row.account || "",
      account_venue_type: row.account_type || "",
      cf_asset: row.asset,
      cf_amount: row.amount,
      fee_asset: row.fee_asset || "",
      fee_amount: row.fee_amount || "0",
      trade_date: row.trade_date,
      value_date: row.value_date,
      network: row.network || "",
      tx_hash: row.txid_reference || "",
      created_by: row.user_id,
      status: row.status,
      notes: row.comment || "",
    };
  }

  async function loadIntoForm(dealRef) {
    setFeedback(null);
    let res;
    try {
      res = await fetch(`http://localhost:5181/api/cashflow/${encodeURIComponent(dealRef)}`);
    } catch (e) {
      setFeedback({ kind: "error", message: "Server unreachable", detail: String(e) });
      return;
    }
    const result = await res.json().catch(() => ({ ok: false, error: "non-JSON server response" }));
    if (!result.ok) {
      setFeedback({ kind: "error", message: result.error || "Failed to load deal" });
      return;
    }
    const row = result.rows[0];
    // setMany is the existing bulk-patch helper (TradeBookingForm.jsx:1815);
    // it merges the patch and refreshes last_modified_at.
    setMany(payloadToFormState(row));
    setAmendingDealRef(row.deal_ref);
    setView("TRADE_INPUT");
  }
```

These field names were verified against `outputRecord` (TradeBookingForm.jsx:2024-2046):
`form.cf_type`, `form.cf_direction`, `form.portfolio`, `form.counterparty`,
`form.account_name`, `form.account_venue_type`, `form.cf_asset`,
`form.cf_amount`, `form.fee_asset`, `form.fee_amount`, `form.trade_date`,
`form.value_date`, `form.network`, `form.tx_hash`, `form.created_by`,
`form.status`, `form.notes`, `form.external_trade_id`. If any of these
have been renamed in the source by the time this task runs, update the
mapping helper accordingly — the source of truth is the `outputRecord`
memo for `form.category === "CASHFLOW"`.

- [ ] **Step 2: Update the submit button label in amend mode**

Find the submit button at line 3612 (`onClick={handleSubmit}`). Inside the button JSX (between the opening and closing tags), it likely says something like `Submit` or `Book Trade`. Replace the button text with:

```jsx
              {amendingDealRef ? `Update ${amendingDealRef}` : (
                form.category === "CASHFLOW" ? "Book Cashflow" : "Generate Output"
              )}
```

(Preserve whatever surrounding markup, icons, or className the existing button has — only swap the inner text node.)

Also add a "× cancel amend" affordance just below the submit button:

```jsx
              {amendingDealRef && (
                <button
                  type="button"
                  onClick={() => {
                    setAmendingDealRef(null);
                    setFeedback(null);
                  }}
                  className="mt-2 text-[11px] opacity-70 hover:opacity-100 underline"
                >× cancel amend</button>
              )}
```

- [ ] **Step 3: Manual browser test**

Make sure `node server.js` and `npm run dev` are both running. Insert a fresh row via the UI per Task 12. Record its `MCF-N`.

In the browser console:
```js
// Trigger loadIntoForm manually
// (Easiest: temporarily add a debug button in the UI, OR set state via React DevTools, OR just wait until Task 14 builds DealEnquiry.)
```

For this task it's fine to test programmatically — open the React DevTools, find the form component, and call `loadIntoForm("MCF-N")` via the dev tools console. Expected: form fields populate, submit button changes to "Update MCF-N", the "× cancel amend" link appears.

Click "Update MCF-N". Verify:
- Network tab shows POST to `/api/cashflow/amend`.
- Green "Updated MCF-N" banner.
- psql: `SELECT deal_ref, effective_start, effective_end FROM trades_cashflow WHERE deal_ref='MCF-N' ORDER BY effective_start;` → 2 rows.

Clean up: `DELETE FROM trades_cashflow WHERE deal_ref='MCF-N';`

- [ ] **Step 4: Commit**

```bash
git add trade-booking/src/TradeBookingForm.jsx
git commit -m "feat(trade-booking): loadIntoForm + amend-mode submit button label"
```

---

## Task 14: Build the `DealEnquiry` component

**Files:**
- Modify: `trade-booking/src/TradeBookingForm.jsx`

- [ ] **Step 1: Define the component**

In `TradeBookingForm.jsx`, search for `view === "DEAL_ENQUIRY"` at line 2651 — currently a `<PlaceholderView title="Deal Enquiry" ... />`. We'll keep that line but render the real component when called. First, define the component near `SubmitFeedback`/`ConflictModal` (just below `PlaceholderView`):

```jsx
function DealEnquiry({ onSelect, BB }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [lastFetchedAt, setLastFetchedAt] = useState(null);

  const fetchRecent = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch("http://localhost:5181/api/cashflow/recent?limit=20");
      const j = await r.json();
      if (!j.ok) throw new Error(j.error || "fetch failed");
      setRows(j.rows || []);
      setLastFetchedAt(new Date());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchRecent(); }, [fetchRecent]);

  return (
    <div className="px-5 pt-4 pb-8">
      <div className="flex items-baseline justify-between mb-3">
        <div>
          <div
            className="text-[11px] tracking-[0.25em] uppercase opacity-60"
            style={{ fontFamily: "'IBM Plex Mono', ui-monospace, monospace" }}
          >Deal Enquiry</div>
          <div
            className="text-[22px] mt-1"
            style={{ fontFamily: "'Cormorant Garamond', 'EB Garamond', Georgia, serif" }}
          >Recent Cashflow Bookings</div>
        </div>
        <button
          type="button"
          onClick={fetchRecent}
          disabled={loading}
          className="px-3 py-1 text-[12px]"
          style={{
            background: BB?.surface || "#f6f3ec",
            border: `1px solid ${BB?.border || "#d9d4c7"}`,
            color: BB?.text || "#1f1f1f",
            opacity: loading ? 0.5 : 1,
          }}
        >{loading ? "Loading…" : "↻ Refresh"}{lastFetchedAt ? ` · ${lastFetchedAt.toLocaleTimeString()}` : ""}</button>
      </div>

      {error && (
        <div
          className="px-3 py-2 mb-3 text-[12px]"
          style={{ background: "#fff0eb", border: "1px solid #e08a6a", color: "#7a1f00" }}
        >Error: {error}</div>
      )}

      <div
        style={{
          background: BB?.surface || "#f6f3ec",
          border: `1px solid ${BB?.border || "#d9d4c7"}`,
        }}
      >
        <table className="w-full text-[12px]" style={{ fontFamily: "'IBM Plex Mono', ui-monospace, monospace" }}>
          <thead>
            <tr style={{ background: "rgba(0,0,0,0.04)", color: BB?.mute || "#666" }}>
              <th className="px-3 py-2 text-left">Deal Ref</th>
              <th className="px-3 py-2 text-left">Trade Date</th>
              <th className="px-3 py-2 text-left">Portfolio</th>
              <th className="px-3 py-2 text-left">Counterparty</th>
              <th className="px-3 py-2 text-left">Cashflow Type</th>
              <th className="px-3 py-2 text-left">Dir</th>
              <th className="px-3 py-2 text-left">Asset</th>
              <th className="px-3 py-2 text-right">Amount</th>
              <th className="px-3 py-2 text-left">Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && !loading && (
              <tr><td colSpan={9} className="px-3 py-6 text-center opacity-60">No live cashflow bookings yet.</td></tr>
            )}
            {rows.map((r) => (
              <tr
                key={r.deal_ref}
                onClick={() => onSelect(r.deal_ref)}
                className="cursor-pointer"
                style={{ borderTop: `1px solid ${BB?.border || "#d9d4c7"}` }}
                onMouseEnter={(e) => e.currentTarget.style.background = "rgba(0,0,0,0.03)"}
                onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
              >
                <td className="px-3 py-2">{r.deal_ref}</td>
                <td className="px-3 py-2">{(r.trade_date || "").slice(0, 10)}</td>
                <td className="px-3 py-2">{r.portfolio_id}</td>
                <td className="px-3 py-2">{r.counterparty || "—"}</td>
                <td className="px-3 py-2">{r.cashflow_type}</td>
                <td className="px-3 py-2">{r.direction}</td>
                <td className="px-3 py-2">{r.asset}</td>
                <td className="px-3 py-2 text-right">{r.amount}</td>
                <td className="px-3 py-2">{r.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="text-[11px] mt-3 opacity-60" style={{ fontFamily: "'IBM Plex Mono', ui-monospace, monospace" }}>
        Click a row to load it into the booking form for amendment.
      </div>
    </div>
  );
}
```

The React import at line 1 already includes `useEffect` but NOT `useCallback`. Update line 1 to add it:

```jsx
import React, { useState, useMemo, useEffect, useCallback, useRef, useContext, createContext } from "react";
```

Then change `React.useCallback` to `useCallback` in the `DealEnquiry` component above (or leave as `React.useCallback` — both work).

- [ ] **Step 2: Replace the placeholder with the real component**

Find at line 2651:

```jsx
          {view === "DEAL_ENQUIRY" && (
            <PlaceholderView
              title="Deal Enquiry"
              subtitle="Search, filter and inspect existing trade records from the MO ledger. Lookup by trade ID, portfolio, counterparty, date range, or asset. Coming soon."
            />
          )}
```

Replace with:

```jsx
          {view === "DEAL_ENQUIRY" && (
            <DealEnquiry
              BB={BB}
              onSelect={(dealRef) => loadIntoForm(dealRef)}
            />
          )}
```

`BB` is the existing palette object referenced throughout the file. If it isn't in scope at this point, pass `{}` and the component will fall back to its hard-coded defaults.

- [ ] **Step 3: Manual browser test — full amend flow end-to-end**

Restart dev server if needed. Make sure `node server.js` is running.

1. Book a fresh cashflow via the form (Task 12 flow). Record the `MCF-N`.
2. Click the "Deal Enquiry" tab in the left sidebar.
3. Expected: the table renders, with your `MCF-N` at the top (most recent first).
4. Click that row. Expected: switches back to TRADE_INPUT view, form is populated, submit button reads `Update MCF-N`, "× cancel amend" link visible.
5. Change the amount, click Update. Expected: green "Updated MCF-N" banner.
6. Click "Deal Enquiry" again → refresh button → expected: the row shows the new amount.
7. Test the ConflictModal: in a second browser tab, also load `MCF-N` into form. In tab 1 amend it. In tab 2, change a different field and submit. Expected: ConflictModal opens. Click "Reload latest" — form refills with tab 1's amended values; submit button reads `Update MCF-N`.
8. Test cancellation: load `MCF-N`, change status dropdown to CANCELLED, click Update. Expected: success banner. In Deal Enquiry table, MCF-N disappears (still live, but status=CANCELLED — verify by looking at the Status column or psql).

Clean up: `DELETE FROM trades_cashflow WHERE deal_ref LIKE 'MCF-%' AND comment LIKE 'test%';` (adjust filter to whatever you used).

- [ ] **Step 4: Commit**

```bash
git add trade-booking/src/TradeBookingForm.jsx
git commit -m "feat(trade-booking): Deal Enquiry view — list 20 recent live cashflows, click to amend"
```

---

## Task 15: Append API contract section to the schema mapping doc

**Files:**
- Modify: `trade-booking/docs/cashflow-schema-mapping.md`

- [ ] **Step 1: Append the API contract section**

Append to `trade-booking/docs/cashflow-schema-mapping.md`:

```markdown

## API contract

The frontend posts the JSON payload built by `outputRecord` (this
mapping) to one of four endpoints on the trade-booking Node server
(port 5181). All endpoints return `{ok: true, rows: [...]}` on success
or `{ok: false, error: "..."}` on failure.

| Method | Route | Body | Success body |
| ------ | ----- | ---- | ------------ |
| POST | `/api/cashflow/insert` | `outputRecord` (object, or 2-element array for mirror-leg) | `rows` has 1 or 2 elements, each is the inserted row with server-allocated `deal_ref` and `effective_start` |
| POST | `/api/cashflow/amend` | `outputRecord` with `deal_ref` populated (object only) | `rows[0]` is the newly inserted live row |
| GET | `/api/cashflow/recent?limit=N` | n/a | `rows` is the N most recent live rows ordered by `trade_date DESC` |
| GET | `/api/cashflow/:deal_ref` | n/a | `rows[0]` is the live row for that deal_ref |

Error HTTP statuses:

- 400 — payload validation failure
- 404 — `deal_ref` not found / no live row
- 409 — concurrent amend (`{ok: false, error: "...", code: "conflict"}`)
- 500 — server/DB error

Implementation lives in `trade-booking/scripts/cashflow_*.py` (one
script per endpoint, all sharing `cashflow_db.py`). See the
[design spec](../../docs/superpowers/specs/2026-05-15-cashflow-booking-backend-design.md)
for SCD2 transaction logic and concurrency reasoning.
```

- [ ] **Step 2: Commit**

```bash
git add trade-booking/docs/cashflow-schema-mapping.md
git commit -m "docs(trade-booking): append cashflow API contract to schema mapping"
```

---

## Task 16: End-to-end smoke checklist + final commit

**Files:**
- None (manual verification only)

- [ ] **Step 1: Run the full smoke checklist**

With both `node server.js` and `npm run dev` running, walk the full happy path and edge cases:

1. **Fresh insert (single)** — Cashflow form, valid fields, Submit → green banner with new MCF-N. Row appears in Deal Enquiry on refresh.
2. **Fresh insert (mirror-leg)** — `cf_type = INTER PTF FUNDING`, Mirror Trade checkbox ticked, fill counterparty as another portfolio, Submit → two MCF-N rows in psql, one row in Deal Enquiry per portfolio.
3. **Amend** — Click a row in Deal Enquiry → form loads → change amount → Update → green "Updated MCF-N" banner. psql shows 2 rows for that deal_ref (first has `effective_end` stamped).
4. **Cancel** — Same as Amend, but change Status to CANCELLED. Confirm new row has `status=CANCELLED`, `effective_end IS NULL`.
5. **Validation 400** — Try to submit with required field missing (e.g., clear Counterparty for a CASHFLOW that isn't INTER PTF FUNDING). Expected: red banner with field-specific message.
6. **Conflict 409** — Two browser tabs, both load MCF-N. Amend in tab 1, then attempt amend in tab 2. Tab 2: ConflictModal opens. Click "Reload latest" → form refills with tab 1's values.
7. **Server down** — Stop `node server.js`. Try to submit. Expected: red banner "Server unreachable".
8. **DB unreachable / VPN off** — Kill VPN. Submit. Expected: red banner "DB error" with stderr detail.

Walk through pytest:

```bash
cd /Users/weiyiao/Projects/nxgen-mo-tools && pytest tests/trade_booking/ -v
```

Expected: all unit tests pass (no UAT dependency for these — they're pure-logic tests).

- [ ] **Step 2: Clean up smoke data**

```sql
DELETE FROM trades_cashflow
  WHERE comment LIKE 'smoke%'
     OR comment LIKE 'test from UI%'
     OR external_trade_id LIKE 'TEST-%';
```

Verify with `SELECT count(*) FROM trades_cashflow;` that only intended rows remain (typically 0 for fresh UAT, more if your team has been booking real data).

- [ ] **Step 3: Final commit (if any docs/cleanup remain)**

If `data/*.json` runtime files have drifted in this session, leave them — they're regenerated. If any cleanup commits are needed:

```bash
git status
# review what's left
git add <files>
git commit -m "chore(trade-booking): post-smoke cleanup"
```

Otherwise, no commit needed.
