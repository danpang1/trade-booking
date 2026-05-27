---
description: Start a CASHFLOW trade booking flow (single or batch). Invokes the trade-booking skill.
---

Activate the **trade-booking** skill for this turn.

If the user has already typed natural-language booking instructions after `/trade-booking`, treat those as the source. Otherwise, ask:

> What would you like to book? (e.g. "500 USDC OPEX out of CDA to TOKKA TREASURY", or paste a multi-line list for a batch)

Then follow the skill's workflow: parse → ask for missing fields → preview → require `y` → shell out to `tokka-mo book` (single) or `tokka-mo book-batch` (multi).
