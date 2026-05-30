// Free-text match helper for the cashflow LoanPicker.
// Pure + framework-free so it can be unit-tested with plain `node`.
//
// Multi-term AND search: the query is split on whitespace into terms, and a
// loan matches only if EVERY term is found (case-insensitive substring) in the
// loan's searchable fields — in any order. So "echocreek 100 btc" matches a
// loan whose counterparty is ECHOCREEK, principal asset BTC, and amount 100.
// An empty / whitespace-only query matches everything.
//
// Searchable fields: deal_ref, counterparty, principal/interest asset, the
// text of principal_amount / interest_rate_pa_pct / maturity_date, plus
// direction, loan_type and interest_type.
export function loanMatchesQuery(loan, query) {
  const q = (query || "").trim().toLowerCase();
  if (!q) return true;
  if (!loan) return false;
  const hay = [
    loan.deal_ref,
    loan.counterparty,
    loan.principal_asset,
    loan.interest_asset,
    loan.principal_amount,
    loan.interest_rate_pa_pct,
    loan.maturity_date,
    loan.direction,
    loan.loan_type,
    loan.interest_type,
  ]
    .filter((v) => v != null)
    .map((v) => String(v).toLowerCase())
    .join(" ");
  const terms = q.split(/\s+/).filter(Boolean);
  return terms.every((t) => hay.includes(t));
}
