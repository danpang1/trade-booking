---
description: One-time setup — log in to the Middle Office server and mint a long-lived API token.
---

Run:

```bash
${CLAUDE_PLUGIN_ROOT}/bin/tokka-mo login --api-url https://mo-tools.tokkalabs.com
```

The CLI will prompt for username and password (the password is hidden as you type). On success it saves a 90-day Bearer token at `~/.config/tokka-mo/credentials` (chmod 600).

For UAT testing, use `--api-url https://mo-tools-uat.tokkalabs.com`.

After login, verify with:

```bash
${CLAUDE_PLUGIN_ROOT}/bin/tokka-mo whoami
```
