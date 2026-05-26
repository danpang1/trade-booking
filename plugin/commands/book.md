---
description: Start a CASHFLOW trade booking flow (single or batch). Invokes the trade-booking skill.
---

Activate the **trade-booking** skill for this turn.

If the user has already typed natural-language booking instructions after `/tokka-mo:book`, treat those as the source. Otherwise, ask:

> What would you like to book? (e.g. "500 USDC OPEX out of CDA to TOKKA TREASURY", or paste a multi-line list for a batch)

Then follow the skill's workflow: parse → ask for missing fields → preview → require `y` → shell out to the CLI:

- Single trade: `${CLAUDE_PLUGIN_ROOT}/bin/tokka-mo book` (payload JSON on stdin)
- Batch (N ≥ 2): `${CLAUDE_PLUGIN_ROOT}/bin/tokka-mo book-batch` (`{"trades":[...]}` on stdin)

The `${CLAUDE_PLUGIN_ROOT}` env var is expanded by Claude Code to the plugin's install directory, so PATH setup is not required.
