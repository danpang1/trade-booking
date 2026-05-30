// Standalone test for loanMatchesQuery. Run: node src/loanSearch.test.mjs
// Exits non-zero on the first failed assertion.
import { loanMatchesQuery } from "./loanSearch.js";

let failures = 0;
function check(name, cond) {
  if (cond) console.log(`ok   - ${name}`);
  else { failures += 1; console.error(`FAIL - ${name}`); }
}

const loan = {
  deal_ref: "MLA00000042",
  counterparty: "ALTERNITY FUND LTD",
  principal_asset: "BTC",
  interest_asset: "USDT",
  principal_amount: "49.900000000000000000",
  interest_rate_pa_pct: "3.000000",
  maturity_date: "2026-01-18T00:00:00+00:00",
};

check("empty query matches", loanMatchesQuery(loan, ""));
check("whitespace query matches", loanMatchesQuery(loan, "   "));
check("matches by deal_ref (full)", loanMatchesQuery(loan, "MLA00000042"));
check("matches by deal_ref (partial)", loanMatchesQuery(loan, "00042"));
check("matches by deal_ref (case-insensitive)", loanMatchesQuery(loan, "mla00000042"));
check("matches by counterparty", loanMatchesQuery(loan, "alternity"));
check("matches by principal asset", loanMatchesQuery(loan, "btc"));
check("matches by interest asset", loanMatchesQuery(loan, "usdt"));
check("matches by amount substring", loanMatchesQuery(loan, "49.9"));
check("matches by rate", loanMatchesQuery(loan, "3.0"));
check("matches by maturity date", loanMatchesQuery(loan, "2026-01-18"));
check("rejects non-matching token", !loanMatchesQuery(loan, "ethereum"));
check("rejects null loan with real query", !loanMatchesQuery(null, "btc"));
check("null loan + empty query still matches", loanMatchesQuery(null, ""));
check("handles missing optional fields", loanMatchesQuery({ deal_ref: "MLA1" }, "mla1"));

// Multi-term AND search (order-independent).
check("multi-term: counterparty + asset", loanMatchesQuery(loan, "alternity btc"));
check("multi-term: order-independent", loanMatchesQuery(loan, "btc alternity"));
check("multi-term: counterparty + amount + asset", loanMatchesQuery(loan, "alternity 49.9 btc"));
check("multi-term: extra spaces ignored", loanMatchesQuery(loan, "  btc   49.9  "));
check("multi-term: all must match (one missing → no match)", !loanMatchesQuery(loan, "alternity eth"));
check("multi-term: unrelated term fails", !loanMatchesQuery(loan, "echocreek btc"));

if (failures > 0) { console.error(`\n${failures} assertion(s) failed`); process.exit(1); }
console.log("\nAll loanSearch assertions passed");
