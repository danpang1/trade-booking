---
description: List your pending CASHFLOW drafts. Optional --status / --batch filters.
---

Run:

```bash
${CLAUDE_PLUGIN_ROOT}/bin/tokka-mo drafts list
```

Then render the output as a clean Markdown table. If the user added arguments (e.g. `/tokka-mo:drafts --status PENDING_REVIEW`), pass them through:

```bash
${CLAUDE_PLUGIN_ROOT}/bin/tokka-mo drafts list --status PENDING_REVIEW
```

If the CLI prints `not logged in`, suggest: "Run `/tokka-mo:login` first."

After listing, remind the user that approve/reject happens in the Middle Office web app at `<api_url>/pending` — the CLI is for submission only in v0.1.
