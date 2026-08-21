"""Standard asset symbol per raw leg label — HARDCODED, edit freely.

Key = the leg's raw base label (instrument up to the first '/'), value = the
standardized asset. Anything not listed maps to itself (plain tickers on
Bitstamp / Robinhood already ARE the standard symbol). When a new leg appears
(new venue wrapper, new perp), add one line here.

Wrapper conventions seen so far:
  {T}-P        Binance UM perp          -> T
  xyz:{T}-P    HL xyz HIP-3 perp        -> T
  {T}B         Native tokenized equity  -> T   (SPCXB, TSLAB, ...)
  SPCXD        HL spot SpaceX token     -> SPCX
"""

ASSET_MAP = {
    # Binance UM perps
    "SPCX-P": "SPCX",
    "QQQ-P": "QQQ",
    "XAG-P": "XAG",
    "CL-P": "CL",
    "SPY-P": "SPYX",   # user rate sheets pin the Binance SPY perp as SPYX
    "USAR-P": "USAR",
    "SKHY-P": "SKHY",
    "DRAM-P": "DRAM",
    "ETH-P": "ETH",
    "NVDA-P": "NVDA",
    "CRWV-P": "CRWV",
    "INTC-P": "INTC",
    "ORCL-P": "ORCL",
    "PLTR-P": "PLTR",
    "AMD-P": "AMD",      # plain Binance UM key; xyz:AMD-P already existed
    # Hyperliquid perps (main dex)
    "HYPE-P": "HYPE",
    "BTC-P": "BTC",
    # Hyperliquid xyz HIP-3 perps
    "xyz:GOLD-P": "GOLD",
    "xyz:NFLX-P": "NFLX",
    "xyz:AAPL-P": "AAPL",
    "xyz:AMD-P": "AMD",
    "xyz:AMZN-P": "AMZN",
    "xyz:BABA-P": "BABA",
    "xyz:BE-P": "BE",
    "xyz:COIN-P": "COIN",
    "xyz:CRCL-P": "CRCL",
    "xyz:CRWV-P": "CRWV",
    "xyz:GOOGL-P": "GOOGL",
    "xyz:INTC-P": "INTC",
    "xyz:META-P": "META",
    "xyz:MSFT-P": "MSFT",
    "xyz:MU-P": "MU",
    "xyz:NVDA-P": "NVDA",
    "xyz:ORCL-P": "ORCL",
    "xyz:PLTR-P": "PLTR",
    "xyz:SKHY-P": "SKHY",
    "xyz:SNDK-P": "SNDK",
    "xyz:SP500-P": "SP500",
    "xyz:SPCX-P": "SPCX",
    "xyz:TSLA-P": "TSLA",
    "xyz:USAR-P": "USAR",
    "xyz:XYZ100-P": "XYZ100",
    # Hyperliquid spot
    "SPCXD": "SPCX",
    # Native Core tokenized equities ({T}B wrappers)
    "SPCXB": "SPCX",
    "TSLAB": "TSLA",
    "CRCLB": "CRCL",
    "NVDAB": "NVDA",
    "SNDKB": "SNDK",
    "MUB": "MU",
    "QQQB": "QQQ",
    # Bitstamp / Robinhood legs are plain tickers -> identity fallback
}


def std_asset(raw):
    """Standardized asset for a raw leg base label (identity if unmapped)."""
    return ASSET_MAP.get(raw, raw)
