"""Fill EVERY hour of balance history for the three plain-custody EVM wallets.

These wallets have no venue feed, so GoldRush is the only source and each hour
costs two paid calls (block lookup + balances-at-block). Snapshots were
therefore sparse by default — transfer hours plus a daily EOD anchor. This
script pays for the dense grid on request.

Scoped per wallet to its first observed activity, not a blanket window start:
EVM_02 opened 2026-06-24 and EVM_03 2026-06-29, so a common 06-09 start would
have bought ~800 hours of calls returning empty balances for wallets that did
not exist yet (~5,600 calls instead of ~7,300).

Resumable: ensure_snaps() only fetches hours absent from tq_hist_balance_mo, so
re-running after an interruption picks up where it stopped.

  python densify_custody_snaps.py [--dry-run]
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone

import evm_custody_wallets as ecw

# first observed balance/transfer per wallet — earlier hours are dead calls
INCEPTION = {
    "WALLET_CRB_EVM_01_BSC": datetime(2026, 6, 9),
    "WALLET_CRB_EVM_02_ETHEREUM": datetime(2026, 6, 24),
    "WALLET_CRB_EVM_03_BSC": datetime(2026, 6, 29),
}


def main():
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    dry = "--dry-run" in sys.argv
    total = 0
    for acct, t0 in INCEPTION.items():
        hours = int((now - t0).total_seconds() // 3600)
        print(f"[{acct}] window {t0:%Y-%m-%d} .. now = {hours}h "
              f"(<= {hours * 2} GoldRush calls)", flush=True)
        total += hours
    print(f"TOTAL upper bound: {total}h / ~{total * 2} calls "
          "(already-stored hours are skipped)", flush=True)
    if dry:
        print("(dry run — nothing fetched)")
        return
    for acct, t0 in INCEPTION.items():
        s = time.time()
        n = ecw.ensure_snaps(acct, t0, now, sparse=False)
        print(f"[{acct}] filled {n} hours in {time.time() - s:.0f}s",
              flush=True)
    print("DENSIFY_DONE")


if __name__ == "__main__":
    main()
