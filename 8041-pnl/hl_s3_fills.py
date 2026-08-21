"""Recover HL fills from Hyperliquid's official S3 node-data archive.

s3://hl-mainnet-node-data/node_fills/hourly/{YYYYMMDD}/{H}.lz4 — complete
fills written by the chain's node stream (requester-pays bucket: needs any
AWS credentials; cost is cents). This is the ONLY source that survives both
the venue API's ~10k-fill retention and collector outages, and it carries
REAL FEES (ClickHouse has none).

Credentials: AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY in 8041-pnl/.env
(or the standard AWS env/config locations).

Usage:
  python hl_s3_fills.py inspect 2026-07-17 2          # dump sample lines
  python hl_s3_fills.py pull 2026-07-17 1 5           # hours [1,5) -> JSON
Writes hl_s3_fills_{date}.json with our user's fills for later staging.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import boto3
import lz4.frame

REPO = Path(__file__).resolve().parent
BUCKET = "hl-mainnet-node-data"
USER = "0x45bef7096101ffe85c7e4fd0cfbfb3cb2bfa61e3"


_ENV_PATHS = (
    REPO / ".env",
    Path(r"C:\Users\peter\OneDrive\Desktop\Claude\recon-dashboard\.env"),
)


def _env(key):
    for p in _ENV_PATHS:
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if s.startswith(key):
                return s.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def client():
    ak, sk = _env("AWS_ACCESS_KEY_ID"), _env("AWS_SECRET_ACCESS_KEY")
    if ak and sk:
        return boto3.client("s3", aws_access_key_id=ak,
                            aws_secret_access_key=sk, region_name="us-east-1")
    return boto3.client("s3", region_name="us-east-1")   # ambient creds


# ── cost ledger: every byte we pull is metered locally ─────────────────
LEDGER = REPO / "s3_cost_ledger.json"
GB_PRICE = 0.114          # ap-northeast-1 internet egress $/GB (first 10TB)
GET_PRICE = 0.0004 / 1000  # $/GET request
COST_CAP_USD = 100.0      # hard stop (user-set 2026-07-31)


def _ledger_add(key, nbytes):
    led = (json.loads(LEDGER.read_text(encoding="utf-8"))
           if LEDGER.exists() else {"total_bytes": 0, "requests": 0,
                                    "pulls": []})
    led["total_bytes"] += nbytes
    led["requests"] += 1
    led["pulls"].append({"key": key, "bytes": nbytes})
    LEDGER.write_text(json.dumps(led, indent=1), encoding="utf-8")
    cost = led["total_bytes"] / 1e9 * GB_PRICE + led["requests"] * GET_PRICE
    # plain ASCII only: this prints to a cp1252 console and a UnicodeEncodeError
    # here would abort a pull AFTER the bytes were already paid for
    print(f"  [cost] +{nbytes / 1e6:.1f} MB, cumulative "
          f"{led['total_bytes'] / 1e9:.2f} GB ~ ${cost:.2f}", flush=True)
    if cost >= COST_CAP_USD:
        raise RuntimeError(
            f"COST CAP: cumulative ~ ${cost:.2f} >= ${COST_CAP_USD} - "
            "stopping all pulls")
    return cost


# `node_fills/` was RETIRED after 2025-07-27 — it still exists in the bucket,
# which is why a GET against it returns NoSuchKey for a 2026 date rather than
# an obvious error. The live stream is `node_fills_by_block/` (verified
# 2026-08-03: newest object minutes old). Both are listed here so a pull falls
# back for genuinely-2025 dates.
FILL_PREFIXES = ("node_fills_by_block/hourly", "node_fills/hourly")


def fetch_hour(s3, date_ymd, hour):
    for prefix in FILL_PREFIXES:
        try:
            return _fetch_key(s3, f"{prefix}/{date_ymd}/{hour}")
        except FileNotFoundError:
            continue
    raise FileNotFoundError(f"{date_ymd}/{hour} in {FILL_PREFIXES}")


def _fetch_key(s3, key):
    for suffix in (".lz4", ""):
        try:
            r = s3.get_object(Bucket=BUCKET, Key=key + suffix,
                              RequestPayer="requester")
            raw = r["Body"].read()
            _ledger_add(key + suffix, len(raw))
            return lz4.frame.decompress(raw) if suffix else raw
        except s3.exceptions.NoSuchKey:
            continue
    raise FileNotFoundError(key)


def extract_fills(block):
    """Our fills out of one `node_fills_by_block` record.

    Shape: {"local_time", "block_time", "block_number",
            "events": [[user_address, {fill}], ...]}
    The old `node_fills` layout nested differently, so this is not
    interchangeable with anything written before 2025-07-27.

    Each fill carries `fee` AND `deployerFee` (HIP-3 dex fee) plus `tid` in
    the SAME id-space as the venue API — which is what makes these rows
    dedup-safe against the existing store.
    """
    out = []
    for ev in block.get("events") or []:
        if not (isinstance(ev, list) and len(ev) == 2):
            continue
        addr, fill = ev
        if str(addr).lower() != USER.lower() or not isinstance(fill, dict):
            continue
        f = dict(fill)
        f["block_number"] = block.get("block_number")
        out.append(f)
    return out


def main():
    cmd, date = sys.argv[1], sys.argv[2]
    ymd = date.replace("-", "")
    s3 = client()
    if cmd == "inspect":
        hour = int(sys.argv[3])
        data = fetch_hour(s3, ymd, hour).decode("utf-8", errors="replace")
        lines = data.splitlines()
        print(f"{len(lines)} lines; first 3:")
        for ln in lines[:3]:
            print(ln[:600])
        hits = [ln for ln in lines if USER in ln.lower()]
        print(f"lines mentioning our user: {len(hits)}; first 2:")
        for ln in hits[:2]:
            print(ln[:600])
        return
    if cmd == "pull":
        h0 = int(sys.argv[3]) if len(sys.argv) > 3 else 0
        h1 = int(sys.argv[4]) if len(sys.argv) > 4 else 24
        ours = []
        for h in range(h0, h1):
            try:
                data = fetch_hour(s3, ymd, h).decode("utf-8", errors="replace")
            except FileNotFoundError:
                print(f"hour {h}: MISSING from archive")
                continue
            n = 0
            for ln in data.splitlines():
                # cheap prefilter before the expensive json.loads: these
                # files are ~150 MB decompressed and most blocks are not ours
                if not ln.strip() or USER not in ln.lower():
                    continue
                ours.extend(extract_fills(json.loads(ln)))
                n = len(ours)
            print(f"hour {h}: running total {n} fills", flush=True)
        out = REPO / f"hl_s3_fills_{ymd}.json"
        out.write_text(json.dumps(ours, indent=1), encoding="utf-8")
        print(f"wrote {out} ({len(ours)} fills)")


if __name__ == "__main__":
    main()
