---
description: One-time setup — log in to the Middle Office server and mint a long-lived API token.
---

Run:

```bash
${CLAUDE_PLUGIN_ROOT}/bin/tokka-mo login --api-url https://sg-tms.internal.tokkalabs.com
```

The CLI will prompt for username and password (the password is hidden as you type). On success it saves a 90-day Bearer token at `~/.config/tokka-mo/credentials` (chmod 600).

For UAT testing, use `--api-url https://test-jp-tms.internal.tokkalabs.com`.

**Note:** Both URLs are on `internal.tokkalabs.com` and require the Tokka VPN. If you see `cannot reach <url>: nodename nor servname provided`, connect to the VPN and retry.

After login, verify with:

```bash
${CLAUDE_PLUGIN_ROOT}/bin/tokka-mo whoami
```
