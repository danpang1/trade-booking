# Loan ↔ Cashflow Mapping — Design

**Date:** 2026-05-16
**Status:** Approved, ready to implement
**Touches:** `trade-booking/scripts/`, `trade-booking/src/TradeBookingForm.jsx`, `trade-booking/server.js`

## Goal

Let operators link a cashflow row to one or more loan rows ("which loan does this interest payment belong to?"), and surface those links in the existing Deal Enquiry view without adding a new dashboard tab.

## Motivation

Today `trades_cashflow` and `trades_loan` are independent ledgers. Loan-related cashflows (interest, principal repayment, fees, collateral postings) have no machine-readable link back to the parent loan. This breaks reconciliation: "how much interest have I paid against MLA00000001?" requires manual matching by date/counterparty/amount.

## Non-goals

- **No separate mapping dashboard.** Mapping creation lives inside the existing cashflow form. Display is inline in Deal Enquiry.
- **No split-amount UI in v1.** `mapped_amount` exists on the table for future use but the form treats every mapping as "full cashflow amount" (NULL).
- **Not bitemporal.** Mappings are plain rows. The cashflow's own SCD2 history captures *that* an amendment changed the mapping; the mapping table itself is overwritten.

## Data model

New table `loan_cashflow_map`:

| Column | Type | Notes |
| --- | --- | --- |
| `loan_deal_ref` | TEXT NOT NULL | MLA-prefix, references `trades_loan.deal_ref` (soft, no FK) |
| `cashflow_deal_ref` | TEXT NOT NULL | MCF-prefix, references `trades_cashflow.deal_ref` (soft, no FK) |
| `mapping_type` | TEXT | Enum: `PRINCIPAL_DISBURSE / PRINCIPAL_REPAY / INTEREST / COLLATERAL_POST / COLLATERAL_RELEASE / FEE`. Derived in backend from `cashflow_type` + `direction` if not supplied. |
| `mapped_amount` | NUMERIC(36,18) NULL | NULL = full cashflow amount. Reserved for future split UI. |
| `mapped_by` | TEXT NOT NULL | `user_id` of operator who created the mapping. |
| `mapped_at` | TIMESTAMPTZ NOT NULL DEFAULT NOW() | |
| `comment` | TEXT NULL | |

**Primary key:** `(loan_deal_ref, cashflow_deal_ref)` → enforces many-to-many with at-most-one mapping per pair.

**Indexes:**
- `(loan_deal_ref)` — "all cashflows for this loan"
- `(cashflow_deal_ref)` — "what loans does this cashflow link to"

**No foreign keys.** Both source tables are bitemporal with composite PKs; a FK to a single deal_ref isn't possible without picking an effective_start. Application-level integrity is enforced by the backend (loan_deal_ref must match a live loan; cashflow_deal_ref must match a live cashflow at mapping time).

## Mapping-type derivation

When the frontend doesn't supply `mapping_type`, the backend derives it from cashflow context:

| cashflow_type | direction | mapping_type |
| --- | --- | --- |
| LOAN | INCOMING (borrower) | PRINCIPAL_DISBURSE |
| LOAN | OUTGOING (lender) | PRINCIPAL_DISBURSE |
| LOAN REPAYMENT | OUTGOING | PRINCIPAL_REPAY |
| LOAN REPAYMENT | INCOMING | PRINCIPAL_REPAY |
| INTEREST EXPENSE / INTEREST INCOME | either | INTEREST |
| (anything else with a manual map) | — | NULL (operator can still map but type is empty) |

## Write path

Frontend sends loan mappings in the cashflow payload's `_meta.loan_deal_refs: ["MLA00000001", "MLA00000005"]`. `cashflow_insert.py` and `cashflow_amend.py`:

1. Insert / amend the cashflow row (as today, in the existing transaction).
2. Call `loan_cashflow_map_db.set_mappings_for_cashflow(cur, cashflow_deal_ref, loan_deal_refs, user_id)`:
   - `DELETE FROM loan_cashflow_map WHERE cashflow_deal_ref = %s`
   - `INSERT` one row per loan_deal_ref in the list
   - Mapping_type derived per the table above; mapped_amount NULL; mapped_by = cashflow's user_id.
3. Commit. Mapping changes are atomic with the cashflow change.

Idempotent semantics: passing `loan_deal_refs: []` clears all mappings for that cashflow; passing the same list twice is a no-op (replace-with-self).

## Read path

Six existing read endpoints get a LEFT JOIN attaching a `mappings` array to each row:

**Cashflow side** (cashflow_get / recent / history):

```sql
SELECT t.*, COALESCE(json_agg(json_build_object(
  'counterpart_deal_ref', m.loan_deal_ref,
  'mapping_type', m.mapping_type,
  'mapped_amount', m.mapped_amount
)) FILTER (WHERE m.loan_deal_ref IS NOT NULL), '[]') AS mappings
FROM trades_cashflow t
LEFT JOIN loan_cashflow_map m ON m.cashflow_deal_ref = t.deal_ref
WHERE ...
GROUP BY t.deal_ref, t.effective_start
```

**Loan side** (loan_get / recent / history): symmetric, joining on `loan_deal_ref` and including counterpart cashflow's `direction` + `amount` + `asset` so the loan-ledger derived total can be computed client-side.

## Frontend

### Form state

Add `cf_loan_deal_refs: []` (array of strings) to the form state. Initial empty; cleared when `cf_type` changes to a non-loan-related type.

### Picker UI

Conditional Field "Linked Loan(s) (optional)" renders in Cashflow Details when `cf_type ∈ { LOAN, LOAN REPAYMENT, INTEREST EXPENSE, INTEREST INCOME }`. Multi-Select chip picker:

- Options sourced from `useLiveLoans()` hook → fetches `/api/loan/recent?limit=200` on mount.
- Client-side filter: `loans.where(l => String(l.portfolio_id) === form.portfolio)`.
- Option label: `MLA00000001 · BORROW 100,000 USDT @ 5.25% FIXED · Binance · matures 2026-06-15` (or `open-term`).
- Picked loans show as removable chips. Add via dropdown below the chips.
- If filtered list is empty: helper line "No live loans on portfolio X" — picker remains active.

### outputRecord

CASHFLOW branch adds the array to `_meta`:

```js
_meta: {
  ...existing,
  loan_deal_refs: form.cf_loan_deal_refs.filter(Boolean),
}
```

Mirror legs (INTER PTF FUNDING) inherit the same array — irrelevant in practice but cheap to keep consistent.

### payloadToFormState (amend reload)

```js
cf_loan_deal_refs: (row.mappings || []).map(m => m.counterpart_deal_ref),
```

### Deal Enquiry inline display

Cashflow row, Details column: append after the existing summary text:

- 1 mapping → `↗ MLA00000001`
- 2+ mappings → `↗ MLA00000001 + 1 more` (tooltip lists all)
- 0 mappings → nothing

Loan row, Details column: derive aggregates from joined cashflow mappings:

- `↗ N cashflows linked` with hover-tooltip showing principal disbursed / total interest paid / total repaid.
- If N=0: nothing.

### History modal

Add `mappings` to `AUDIT_DIFF_FIELDS_CASHFLOW`. Comparison is a sorted-array-of-strings equality on `mappings.map(m => m.counterpart_deal_ref).sort()`. Initial-version summary shows `· linked to N loan(s)` when non-empty.

## Files to touch

| File | Change |
| --- | --- |
| `trade-booking/scripts/apply_schema_loan_cashflow_map.py` | **New** — DDL migration |
| `trade-booking/scripts/loan_cashflow_map_db.py` | **New** — helpers + `set_mappings_for_cashflow` |
| `trade-booking/scripts/cashflow_insert.py` | Read `_meta.loan_deal_refs` and call `set_mappings_for_cashflow` in same txn |
| `trade-booking/scripts/cashflow_amend.py` | Same |
| `trade-booking/scripts/cashflow_db.py` | `row_to_payload` extended to expose `mappings` column if present |
| `trade-booking/scripts/cashflow_get.py` / `_recent.py` / `_history.py` | LEFT JOIN on map table |
| `trade-booking/scripts/loan_get.py` / `_recent.py` / `_history.py` | LEFT JOIN on map table |
| `trade-booking/src/TradeBookingForm.jsx` | Form state, picker, outputRecord, payloadToFormState, Deal Enquiry chips, History audit field |
| `trade-booking/docs/cashflow-schema-mapping.md` | Document the new `_meta.loan_deal_refs` field |
| `trade-booking/server.js` | No change — existing routes pass through |

## Verification

Smoke sequence (run against UAT):
1. Apply schema migration → confirm table + indexes exist.
2. Book a loan via `/api/loan/insert` → get MLA deal_ref.
3. Book a cashflow (type=INTEREST EXPENSE) with `_meta.loan_deal_refs: ["MLA..."]` → confirm mapping row inserted.
4. `GET /api/cashflow/<deal_ref>` → confirm `mappings` array populated.
5. `GET /api/loan/<deal_ref>` → confirm `mappings` array contains the cashflow.
6. Amend cashflow with `_meta.loan_deal_refs: []` → confirm mapping row deleted, cashflow row's v2 written.
7. Amend cashflow with two loan refs → confirm two rows in mapping table for that cashflow.
8. UI: open cashflow form, pick type=LOAN, confirm Loan picker appears; pick a loan, submit, confirm Deal Enquiry shows `↗ MLA...`.

## Open questions / future work

- **Split allocations**: when an operator does need to split one cashflow across loans by amount, surface a per-chip amount input. `mapped_amount` column already exists.
- **Standalone loan-ledger view**: if reconciliation needs grow, a future loan-ledger page can read `loan_cashflow_map` directly. Not in scope here.
- **Cross-portfolio mappings**: today picker filters to same portfolio. If you ever need a loan in PTF A and a cashflow in PTF B (intercompany), an "Allow cross-portfolio" toggle on the picker can unlock that. Not in scope.
