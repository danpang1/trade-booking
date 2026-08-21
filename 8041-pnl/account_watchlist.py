"""Watchlist probe for accounts that exist in refdata but are NOT tracked
as recon columns (dust / dormant / conduit wallets).

Rationale: an untracked account that starts trading is invisible — the same
class of blind spot that hid the Binance HYPE-P leg and the EVM_05 GME
wallet until a manual cross-check found them. This probe reads each one's
current state and shouts if it exceeds the "asleep" thresholds recorded
below, so the daily cycle surfaces a wake-up instead of us discovering it
weeks later.

Run: python account_watchlist.py     (exit code 1 = something woke up)
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent

# name, goldrush chain, address, USD threshold above which we shout
WALLETS = [
    ("WALLET_CRB_EVM_01 (BSC)", "bsc-mainnet",
     "0xE71b2e6dDc88FFdECdcd0D750c57D0122AA586c2", 500),
    ("WALLET_CRB_EVM_02 (Ethereum)", "eth-mainnet",
     "0x9f736F87E6293AC1Bd9142E257dbfAC8b7AcF1ae", 500),
    ("WALLET_CRB_EVM_03 (BSC conduit)", "bsc-mainnet",
     "0x42A95A3B8d2FF2d12f3c393De42c7288FC943325", 5000),
    ("WALLET_CRB_EVM_06 (BSC)", "bsc-mainnet",
     "0x10C7E357c0B9cABDC36c4C81cfCD2788321ce32F", 500),
    ("WALLET_CRB_SOL_01 (Solana)", "solana-mainnet",
     "4SxZcm8pkvC6mGqRJecnn2nyrMACyCUkL7h9R3vYaMqf", 500),
]

# Paxos: dormant venue, 2 test fills ever (PAXG 06-18/19) — shout on a 3rd
PAXOS_KNOWN_ORDERS = 2
PAXOS_USD_THRESHOLD = 100


def _gr_key():
    env = (REPO / ".env").read_text(encoding="utf-8", errors="replace")
    return re.search(r"GOLDRUSH_API_KEY\s*[:=]\s*(\S+)", env).group(1).strip("\"'")


def check_wallets():
    key = _gr_key()
    ua = {"User-Agent": "tokka-mo", "Authorization": f"Bearer {key}"}
    alerts = []
    for label, chain, addr, thresh in WALLETS:
        url = (f"https://api.covalenthq.com/v1/{chain}/address/{addr}"
               f"/balances_v2/?no-spam=true")
        try:
            d = json.loads(urllib.request.urlopen(
                urllib.request.Request(url, headers=ua), timeout=60).read())
            items = d["data"].get("items") or []
        except Exception as e:
            print(f"  {label}: probe failed ({str(e)[:60]})")
            continue
        usd = sum(float(it.get("quote") or 0) for it in items)
        state = "AWAKE" if usd >= thresh else "asleep"
        print(f"  {label}: ${usd:,.2f} ({state}, threshold ${thresh:,})")
        if usd >= thresh:
            alerts.append(f"{label} holds ${usd:,.2f} (>= ${thresh:,}) — "
                          "consider adding a recon column")
    return alerts


def check_paxos():
    """MOON-TK@PAXOS: balances + order count via the mintburn credentials."""
    import os
    pax = Path(r"C:\Users\peter\OneDrive\Desktop\Claude\Paxos mintburn")
    if not (pax / ".env").exists():
        print("  MOON-TK@PAXOS: credentials not found — skipped")
        return []
    for line in (pax / ".env").read_text(encoding="utf-8",
                                         errors="replace").splitlines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, _, v = s.partition("=")
            os.environ.setdefault(k.strip(), v.strip())
    sys.path.insert(0, str(pax))
    try:
        import config
        import paxos_client
        c = paxos_client.PaxosClient(
            config.CLIENT_ID, config.CLIENT_SECRET, config.BASE_URL,
            getattr(config, "TOKEN_URL",
                    "https://oauth.paxos.com/oauth2/token"),
            getattr(config, "SCOPES",
                    ["funding:read_profile", "exchange:read_order"]))
        profs = c.get_profiles()
        items = profs.get("items", profs) if isinstance(profs, dict) else profs
        alerts = []
        for p in items or []:
            pid = p["id"]
            bal = c.get_balances(pid)
            bi = bal.get("items", bal) if isinstance(bal, dict) else bal
            usd = sum(float(b.get("available") or 0) for b in (bi or [])
                      if b.get("asset") in ("USD", "USDC", "USDG", "PYUSD"))
            orders = c.list_orders(pid, limit=50)
            oi = orders.get("items", orders) if isinstance(orders, dict) else orders
            n = len(oi or [])
            state = ("AWAKE" if (n > PAXOS_KNOWN_ORDERS
                                 or usd >= PAXOS_USD_THRESHOLD) else "asleep")
            print(f"  MOON-TK@PAXOS [{p.get('nickname')}]: ${usd:,.2f}, "
                  f"{n} orders ({state}; known {PAXOS_KNOWN_ORDERS})")
            if state == "AWAKE":
                alerts.append(f"MOON-TK@PAXOS active: {n} orders, ${usd:,.2f}"
                              " — needs ingest + a recon column")
        return alerts
    except Exception as e:
        print(f"  MOON-TK@PAXOS: probe failed ({str(e)[:80]})")
        return []


if __name__ == "__main__":
    print("[watchlist] untracked accounts — checking for wake-ups")
    alerts = check_wallets() + check_paxos()
    if alerts:
        print("\n*** WATCHLIST ALERTS ***")
        for a in alerts:
            print("  !", a)
        sys.exit(1)
    print("\n[watchlist] all quiet — nothing needs onboarding")
