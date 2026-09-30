---
name: loan-booking
description: Book loan agreements (MLA) and the loan cashflows (MCF) that settle against them. Use when the request involves borrowing, lending, a drawdown, a loan repayment, loan interest, or tagging a cashflow to a loan.
---

# Loan booking

A loan in TMS is **two separate things**, and the whole job is knowing which
one the operator is asking for:

| | What it is | Deal ref | How it is created |
|---|---|---|---|
| **MLA** | Master Loan Agreement — the facility itself: who, how much, what rate | `MLA00000000` | **Written immediately.** No draft, no approval. |
| **MCF** | The cashflow that moves the money — drawdown, repayment, interest | `MCF00000000` | Draft → human approval, like every other cashflow |

One MLA has many MCFs. An MCF may be tagged to one or more MLAs, or to none.

## The asymmetry you must tell the operator about

An MCF is a **draft**: it waits for someone to approve it in TMS, and nothing
reaches the book until they do.

An MLA is **not**. `tokka-mo loan-open` writes to the production book the
moment it returns. There is no review step and no undo — a mistake has to be
amended to `CANCELLED` afterwards, which leaves a permanent row.

So never create an MLA to "see if it works", and never create one before the
operator has confirmed the details back to you. If you need to check a payload,
use `--dry-run`, which validates and sends nothing.

## LOAN is not MARGIN LOAN

This is the mistake to avoid. The distinction is **what kind of borrowing it
is**, never which venue it came from:

| | `LOAN` / `LOAN REPAYMENT` | `MARGIN LOAN` / `MARGIN REPAYMENT` |
|---|---|---|
| What | a borrowing facility with an MLA | margin financing on the risk book |
| Portfolio | **8888** treasury, always | **8041** central risk book, always |
| Counterparty | SQUID, BINANCE INVESTMENTS, ECHOCREEK, KRAKEN, ONDO … | **NATIVE CORE** only |
| Tagged to an MLA | yes — 97% of `LOAN`, 77% of `LOAN REPAYMENT` | no — none of them |

**A Binance VIP loan is a plain `LOAN`.** Every drawdown on account
`TK818@BINANCE` in PTF 8888 is booked `LOAN` / `INCOMING`, and repaying it is
`LOAN REPAYMENT` / `OUTGOING`. The word "margin" appearing near Binance — or
the loan being collateralised, which VIP loans are — does not make it a margin
loan. `MARGIN LOAN` has never once been booked in this system.

If you find yourself about to write `MARGIN LOAN`, check the portfolio: unless
it is 8041 against NATIVE CORE, it is wrong.

## Deciding which case you are in

Ask yourself: **does the facility already exist?**

```
"repay 500k USDC to Kraken"                    -> MCF only, tag an existing MLA
"book the interest on the Binance VIP loan"    -> MCF only, tag an existing MLA
"we drew down 2m from Ondo today"              -> MCF only IF the MLA exists
"new 5m facility from Galaxy at 6%, drawn today" -> MLA + MCF, both
```

The words rarely settle it. **Look it up** before asking:

```bash
python <cli> loan-list --counterparty GALAXY --status LIVE
```

- **Exactly one live MLA matches** the counterparty and asset → that is almost
  certainly the one. Name it in your preview and let them correct you.
- **Several match** → list them with principal, asset and rate, and ask which.
  Do not guess; two facilities with the same counterparty usually differ in
  rate or tenor, and tagging the wrong one misstates both.
- **None match** → say so plainly, and ask whether to create the facility.
  Never invent an MLA ref, and never book an MCF untagged just to get past it.

## Case 1 — MCF against an existing MLA (the common one)

Book a normal CASHFLOW draft with the mapping in `_meta`:

```json
{
  "txn_type": "CASHFLOW",
  "cashflow_type": "LOAN REPAYMENT",
  "direction": "OUTGOING",
  "...": "all the usual mandatory cashflow fields",
  "_meta": { "loan_deal_refs": ["MLA00000545"] }
}
```

`_meta` is stripped before the row is written, and the mapping is inserted in
the same transaction as the cashflow — they cannot come apart. The mapping type
is derived for you. For principal cashflows (`LOAN`, `LOAN REPAYMENT`) it comes
from the direction of the **cash against the direction of the loan**, not from
the label — a disbursement is principal moving from lender to borrower:

| loan direction | cashflow direction | mapping_type |
|---|---|---|
| `BORROW` | `INCOMING` | `PRINCIPAL_DISBURSE` |
| `BORROW` | `OUTGOING` | `PRINCIPAL_REPAY` |
| `LEND` | `OUTGOING` | `PRINCIPAL_DISBURSE` |
| `LEND` | `INCOMING` | `PRINCIPAL_REPAY` |
| any | `INTEREST EXPENSE` / `INTEREST INCOME` | `INTEREST` |
| any | anything else | none (still linked, just untyped) |

So on a LEND, Tokka paying the principal out is the disbursement and the
counterparty paying it back is the repayment, whichever of `LOAN` /
`LOAN REPAYMENT` the row is labelled. Prefer the label that matches anyway —
`LOAN` for the disbursement, `LOAN REPAYMENT` for the repayment — so the
cashflow reads correctly on its own.

The MLA must exist and be **live**. Tagging a cancelled or superseded loan is
rejected at write time — which is a real check, not a formality, since
cancelled loans stay in the table.

## Case 2 — new facility and its first cashflow

Order matters: the MCF has to name the MLA, and the ref only exists once the
loan is written. So:

1. Gather **every** mandatory field for **both** legs before doing anything.
2. Show one combined preview — the facility and the cashflow together.
3. State plainly: *"The loan is created immediately and cannot be un-created;
   the cashflow still needs approval."*
4. Wait for an explicit yes.
5. `loan-open --yes` → read the `MLA…` ref out of the output.
6. `book` the MCF with that ref in `_meta.loan_deal_refs`.

If step 6 fails, **say so loudly**: the facility now exists with no cashflow
against it, and the operator has to either book the MCF by hand or cancel the
MLA. Do not quietly retry from step 5 — that creates a second facility.

## Mandatory MLA fields

All required; ask for any that are missing, exactly as with a cashflow. Never
default one to get moving.

| Field | Values |
|---|---|
| `direction` | `BORROW` (we owe) / `LEND` (we are owed) |
| `loan_type` | `EXTERNAL` / `INTERNAL` / `VIP LOAN` / `DEFI LENDING` |
| `entity` | the booking entity |
| `portfolio_id` + `portfolio_name` | must agree with each other |
| `counterparty` | who we borrowed from or lent to — an exact refdata name (`counterparty-list`); the server rejects free text and stamps the CID itself |
| `principal_asset` + `principal_amount` | must be > 0 |
| `interest_asset` | often the same as principal |
| `interest_type` | `FIXED` / `FLOATING` |
| `trade_date` | ISO 8601 with timezone |
| `status` | `LIVE` for a new facility |

## What to assume, and what to ask

Not every unstated field is a question. Two have a right answer when the
operator says nothing; one never does.

**Interest — if not stated, use `0`. Do not ask.** 87% of live facilities are
zero-rate, and every one stores a literal `0` rather than a null, so write
`"interest_rate_pa_pct": "0"` instead of omitting the field — omitting it shows
a blank rate where the desk expects a zero. Say "interest 0% (not stated)" in
the preview, so a real rate gets corrected before booking.

**Maturity — if not stated, it is open term. Do not ask, and never invent a
date.** Omit `maturity_date` entirely: all 116 live facilities have it null,
and the field is only populated once a loan has matured. Say "open term" in the
preview.

**Counterparty — always ask. Never assume, never infer.** Not from the account,
not from the venue, not from what is usually borrowed at that size. All 315
loans ever booked name one, so an absent counterparty is a gap in the request,
not a field that is legitimately empty. And unlike a rate or a maturity, a
wrong counterparty misstates who the firm owes, and cannot be repaired from the
cashflow side afterwards. It is required by this skill even though the server's
own validator does not enforce it.

The one exception: if the counterparty is stated **anywhere in the thread** —
an earlier message, or the request being booked — use it. Reading it out of the
conversation is not inferring it. Only a counterparty nobody has stated
anywhere needs asking for.

Everything else optional (`day_count_basis` — 360 or 365, defaults 365 —
`floating_benchmark`, `wht_pct`, `comment`) is worth asking for only when the
operator clearly has it to hand.

## Two things the data will not tell you

- **No live loan currently carries a `maturity_date`.** The field is only
  populated once a loan has matured. So you cannot answer "what is maturing
  next" from this table, and you should ask for the maturity explicitly rather
  than assuming an open-ended facility.
- **`collateral_asset` is empty on every row**, including VIP loans that
  demonstrably have collateral. Do not report a loan as uncollateralised on the
  strength of that field.

See `references/loan-schema.md` for the full field list and worked examples.
