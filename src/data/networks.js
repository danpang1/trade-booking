// Network dropdown options for the trade booking form.
//
// Sourced from MySQL reference_data.counterparty WHERE type='BLOCKCHAIN'
// (auto-generated snapshot — TODO: replace with a live fetch from a
// booking-API service).
//
// PRESENTATION ORDER: most-used chains first, then everything else alphabetical.
// Most-used roughly tracks native-token market cap weighted by how often we
// actually book cashflows on each chain. Adjust the PRIORITY list to taste —
// the OTHERS list stays alphabetical so new auto-gen entries land predictably.

const PRIORITY = [
  "ETHEREUM",
  "BINANCE SMART CHAIN",
  "SOLANA",
  "TRON",
  "BITCOIN",
  "POLYGON",
  "ARBITRUM",
  "BASE",
  "OPTIMISM",
  "AVALANCHE",
  "SUI",
  "APTOS",
  "TON",
  "RIPPLE",
  "CARDANO",
  "POLKADOT",
  "STELLAR",
  "HEDERA",
];

const ALL_ALPHABETICAL = [
  "APTOS",
  "ARBITRUM",
  "AVALANCHE",
  "BASE",
  "BERACHAIN",
  "BINANCE SMART CHAIN",
  "BITCOIN",
  "BITCOIN CASH",
  "BLAST",
  "CARDANO",
  "CELO",
  "CITREA",
  "DOGE",
  "ETHEREUM",
  "GNOSIS",
  "HEDERA",
  "HYPERCORE",
  "HYPEREVM",
  "LINEA",
  "MANTLE",
  "MANTRA",
  "MODE",
  "OPTIMISM",
  "PEAQ",
  "PLASMA",
  "POLKADOT",
  "POLYGON",
  "RIPPLE",
  "SAGAEVM",
  "SCROLL",
  "SOLANA",
  "SONEIUM",
  "SONIC",
  "STELLAR",
  "SUI",
  "TEMPO",
  "TON",
  "TRON",
  "UNICHAIN",
  "XRPLEVM",
  "ZETA",
  "ZKSYNC",
];

const priorityKnown = PRIORITY.filter((n) => ALL_ALPHABETICAL.includes(n));
const others = ALL_ALPHABETICAL.filter((n) => !priorityKnown.includes(n));

export const NETWORKS = [...priorityKnown, ...others];
