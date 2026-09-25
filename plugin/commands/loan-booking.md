---
description: Book a loan agreement (MLA) and/or the cashflow that settles against it (MCF). Invokes the loan-booking skill.
---

Activate the **loan-booking** skill for this turn.

If the user has already typed instructions after `/loan-booking`, treat those as the source. Otherwise, ask:

> What's the loan movement? (e.g. "repay 500k USDC to Kraken", or "new 5m facility from Galaxy at 6%, drawn today")

Then follow the skill's workflow:

1. Work out which case it is — a cashflow against an existing facility, or a new facility too. Run `tokka-mo loan-list --counterparty <name>` to check rather than asking the user something the book already answers.
2. Gather every mandatory field for whichever legs are involved. Ask for anything missing; never default one.
3. Preview both legs together and require an explicit `y`.
4. If a new facility is needed, say plainly that `loan-open` writes it to the book immediately with no approval step, then run it and read back the `MLA…` ref.
5. Book the cashflow with that ref in `_meta.loan_deal_refs`.

If step 5 fails after step 4 succeeded, report it directly — the facility exists with nothing against it, and re-running `loan-open` would create a second one.
