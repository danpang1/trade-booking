import React, { useState, useMemo, useEffect, useCallback, useRef, useContext, createContext } from "react";
import {
  Copy,
  Check,
  AlertCircle,
  RotateCcw,
  Upload,
  Paperclip,
  X,
  Link2,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Calendar,
} from "lucide-react";
import tokkaLogo from "./assets/tokka-labs-logo.png";
import {
  ACCOUNTS_EXCHANGE,
  ACCOUNTS_WALLET,
  ACCOUNTS_BROKER,
  ACCOUNT_VENUE_TYPES,
} from "./data/accounts.js";
import { NETWORKS } from "./data/networks.js";
import { TOKENS, ASSET_SYMBOLS } from "./data/tokens.js";

// Live token list — initialized from the bundled snapshot, replaced after
// fetch('/tokens.json') resolves (refreshed hourly by server.js). AssetPicker
// reads this context so the 12 call sites don't need any prop changes.
const TokensContext = createContext(TOKENS);

// ═════════════════════════════════════════════════════════════
// Altas editorial palette — mirrors the nxgen-mo dashboard's
// bone/ink/hair tokens (see dashboard/src/index.css @theme block).
// Same token names as before so downstream usage stays uniform.
// ═════════════════════════════════════════════════════════════
const BB = {
  bg: "#f2efe8",           // bone (canvas)
  surface: "#f8f6f1",      // chalk (panels)
  surface2: "#f8f6f1",     // chalk (inputs)
  border: "#d9d4c7",       // hair (hairline borders)
  borderHot: "#0d0d0d",    // ink (focus / hover)
  orange: "#1f63ea",       // tokka blue (primary accent — sampled from logo)
  amber: "#1a4fbb",        // tokka blue deep (headline / status)
  yellow: "#0d0d0d",       // ink (active input values — readable on chalk)
  cyan: "#0e7490",         // cyan-700 (IDs / refs)
  green: "#047857",        // emerald-700 (BUY / BOOKED / positive)
  red: "#b91c1c",          // red-700 (SELL / errors)
  magenta: "#86198f",      // fuchsia-800 (section accents)
  text: "#0d0d0d",         // ink (primary text)
  dim: "#3a3834",          // graphite (secondary text)
  mute: "#6a665c",         // slate (labels)
  faint: "#9a9488",        // muted (helpers)
};

// Pre-built className constants — using arbitrary Tailwind values
// to keep the theme scoped without touching index.css.
const cls = {
  label:
    "block text-[10px] uppercase tracking-[0.18em] text-[#3a3834] mb-1 font-mono",
  // Rest → hover → focus progression:
  //   rest:  hair border #d9d4c7 on chalk #f8f6f1
  //   hover: slate border #6a665c on white #ffffff  (lifted feel)
  //   focus: ink border #0d0d0d on white #ffffff
  input:
    "w-full bg-[#f8f6f1] border border-[#d9d4c7] px-2.5 py-1.5 text-[12px] text-[#0d0d0d] font-mono " +
    "hover:border-[#6a665c] hover:bg-[#ffffff] " +
    "focus:outline-none focus:border-[#0d0d0d] focus:bg-[#ffffff] " +
    "placeholder:text-[#9a9488] rounded-none transition-colors caret-[#1f63ea]",
  select:
    "w-full bg-[#f8f6f1] border border-[#d9d4c7] px-2.5 py-1.5 text-[12px] text-[#0d0d0d] font-mono " +
    "hover:border-[#6a665c] hover:bg-[#ffffff] " +
    "focus:outline-none focus:border-[#0d0d0d] focus:bg-[#ffffff] " +
    "rounded-none appearance-none cursor-pointer pr-7 transition-colors",
  textarea:
    "w-full bg-[#f8f6f1] border border-[#d9d4c7] px-2.5 py-1.5 text-[12px] text-[#0d0d0d] font-mono " +
    "hover:border-[#6a665c] hover:bg-[#ffffff] " +
    "focus:outline-none focus:border-[#0d0d0d] focus:bg-[#ffffff] " +
    "placeholder:text-[#9a9488] rounded-none resize-none transition-colors",
};

// ─────────────────────────────────────────────────────────────
// Reference data — unchanged from prototype
// ─────────────────────────────────────────────────────────────
// Canonical legal entities — sourced from MySQL select_category=COMMON ORGANISATION.
// Trade Summary's Entity field is derived from the chosen portfolio (PORTFOLIOS map below).
const ENTITIES = [
  "TOKKA LABS PTE LTD",
  "ECHO CREEK LIMITED",
  "IMAGINE LABS PTE LTD",
  "NATIVE TECHNOLOGY LIMITED",
  "RANGE PROTOCOL LIMITED",
  "SPRING MUD PTE LTD",
];

// Portfolio reference — snapshot from MySQL reference_data.portfolio
// WHERE deletedAt IS NULL AND status = 'ACTIVE' (33 rows). Each maps to its
// legal entity via the portfolio.organisation column, so selecting a portfolio
// auto-fills the Entity field. The 10 DORMANT portfolios (8002 / 8005 / 8008 /
// 8010 / 8011 / 8013 / 8015 / 8016 / 8018 / 8019) are intentionally excluded.
// TODO: swap to a live API fetch once the backend is up.
const PORTFOLIOS = [
  { number: 1000, name: "SOSOVALUE - SODEXMM", entity: "IMAGINE LABS PTE LTD" },
  { number: 8000, name: "TOKKA LABS - MM PMM - RFQ", entity: "TOKKA LABS PTE LTD" },
  { number: 8001, name: "TOKKA LABS - SSB - 1INCH FUSION", entity: "TOKKA LABS PTE LTD" },
  { number: 8003, name: "TOKKA LABS - CLOB - DEX MM BLUEFIN", entity: "TOKKA LABS PTE LTD" },
  { number: 8006, name: "TOKKA LABS - SSB - CDA ALTCHAINS", entity: "TOKKA LABS PTE LTD" },
  { number: 8007, name: "TOKKA LABS - SSB - MEV ETH", entity: "TOKKA LABS PTE LTD" },
  { number: 8009, name: "TOKKA LABS - INNOVATION LAB - TESTING", entity: "TOKKA LABS PTE LTD" },
  { number: 8012, name: "TOKKA LABS - CLOB - DBS DDEX MM", entity: "TOKKA LABS PTE LTD" },
  { number: 8017, name: "TOKKA LABS - SSB - BUILDER ETH", entity: "TOKKA LABS PTE LTD" },
  { number: 8020, name: "TOKKA LABS - SSB - COWSWAP", entity: "TOKKA LABS PTE LTD" },
  { number: 8021, name: "TOKKA LABS - SSB - PYTH EXPRESS RELAY", entity: "TOKKA LABS PTE LTD" },
  { number: 8022, name: "TOKKA LABS - MM LP - ALKIMIYA", entity: "TOKKA LABS PTE LTD" },
  { number: 8023, name: "TOKKA LABS - SSB - CDA SOL", entity: "TOKKA LABS PTE LTD" },
  { number: 8025, name: "TOKKA LABS - SSB PYTH", entity: "TOKKA LABS PTE LTD" },
  { number: 8026, name: "TOKKA LABS - CLOB - DEX REYA", entity: "TOKKA LABS PTE LTD" },
  { number: 8027, name: "TOKKA LABS - MM LP - SOSOVALUE", entity: "TOKKA LABS PTE LTD" },
  { number: 8028, name: "TOKKA LABS - MM PMM - CROSSCHAIN", entity: "TOKKA LABS PTE LTD" },
  { number: 8029, name: "TOKKA LABS - SSB - SEARCHER SOLANA", entity: "TOKKA LABS PTE LTD" },
  { number: 8030, name: "TOKKA LABS - CLOB - SYNFUTURES DEX", entity: "TOKKA LABS PTE LTD" },
  { number: 8031, name: "TOKKA LABS - SSB - CDA TON HG", entity: "TOKKA LABS PTE LTD" },
  { number: 8032, name: "TOKKA LABS - CLOB - HYPERLIQUID", entity: "TOKKA LABS PTE LTD" },
  { number: 8033, name: "TOKKA LABS - CLOB - GRVT VERTEX", entity: "TOKKA LABS PTE LTD" },
  { number: 8034, name: "TOKKA LABS - SSB - VEROLA", entity: "TOKKA LABS PTE LTD" },
  { number: 8035, name: "TOKKA LABS - MM LP - ARMSTROM", entity: "TOKKA LABS PTE LTD" },
  { number: 8036, name: "TOKKA LABS - MM LP - SOSOVAULT", entity: "TOKKA LABS PTE LTD" },
  { number: 8037, name: "TOKKA LABS - SSB - LIQUIDATION", entity: "TOKKA LABS PTE LTD" },
  { number: 8038, name: "TOKKA LABS - ARB - HYPERARBITRAGE", entity: "TOKKA LABS PTE LTD" },
  { number: 8039, name: "TOKKA LABS - SPP - SODEX", entity: "TOKKA LABS PTE LTD" },
  { number: 8040, name: "TOKKA LABS - RFQ - PROPAMM", entity: "TOKKA LABS PTE LTD" },
  { number: 8041, name: "TOKKA LABS - MM - CENTRAL RISK BOOK", entity: "TOKKA LABS PTE LTD" },
  { number: 8888, name: "TOKKA LABS - TREASURY", entity: "TOKKA LABS PTE LTD" },
  { number: 8889, name: "TOKKA LABS - TREASURY - INVESTMENTS", entity: "TOKKA LABS PTE LTD" },
  { number: 9999, name: "TOKKA LABS - DUMMY", entity: "TOKKA LABS PTE LTD" },
];

// Counterparty reference — snapshot from MySQL reference_data.counterparty
// WHERE deletedAt IS NULL AND (status IS NULL OR status='ACTIVE') (168 rows).
// Each entry carries type + subType so the picker can show useful context
// (e.g. EXCHANGE (CEX) / SMART CONTRACTS / LENDER).
// TODO: swap to a live API fetch once the backend is up.
const COUNTERPARTIES = [
  { name: "0XRICK LIMITED", type: "LENDER", subType: "LENDER" },
  { name: "1INCH FUSION+", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "1INCH LIMITED", type: "PROTOCOL", subType: "SMART CONTRACTS" },
  { name: "21SHARES US LLC", type: "TRADING VENUE", subType: "BROKER/OVER-THE-COUNTER (OTC)" },
  { name: "ACROSS", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "ADEVAR LABS INC", type: "SERVICE PROVIDER/VENDOR", subType: "VENDOR" },
  { name: "AERODROME", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "AGORA FINANCE", type: "ISSUER", subType: "BROKER/OVER-THE-COUNTER (OTC)" },
  { name: "AIRSWAP", type: "PROTOCOL", subType: "SMART CONTRACTS" },
  { name: "ALGEBRA FINANCE", type: "TRADING VENUE", subType: "SMART CONTRACTS" },
  { name: "ALKIMIYA", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "ALTERNITY FUND LTD", type: "LENDER", subType: "CORPORATION" },
  { name: "AMBIENT FINANCE", type: "TRADING VENUE", subType: "EXCHANGE (CEX)" },
  { name: "APTOS", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "AQUA PROTOCOL", type: "PROTOCOL", subType: "SMART CONTRACTS" },
  { name: "ARBITRUM", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "AVALANCHE", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "BACKED.FI", type: "ISSUER", subType: "CORPORATION" },
  { name: "BACKPACK", type: "TRADING VENUE", subType: "EXCHANGE (CEX)" },
  { name: "BASE", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "BEBOP LTD", type: "PROTOCOL", subType: "SMART CONTRACTS" },
  { name: "BERACHAIN", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "BERASWAP", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "BINANCE", type: "TRADING VENUE", subType: "EXCHANGE (CEX)" },
  { name: "BINANCE SMART CHAIN", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "BINANCE_ALPHA", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "BITCOIN", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "BITCOIN CASH", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "BITGET", type: "TRADING VENUE", subType: "EXCHANGE (CEX)" },
  { name: "BITGLOBAL", type: "SERVICE PROVIDER/VENDOR", subType: "VENDOR" },
  { name: "BITGO TRUST COMPANY INC", type: "TRADING VENUE", subType: "CORPORATION" },
  { name: "BITMEX", type: "TRADING VENUE", subType: "EXCHANGE (CEX)" },
  { name: "BLAST", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "BLITZ", type: "PROTOCOL", subType: "SMART CONTRACTS" },
  { name: "BLOCKPI NETWORK", type: "SERVICE PROVIDER/VENDOR", subType: "CORPORATION" },
  { name: "BLUEFIN", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "BYBIT", type: "TRADING VENUE", subType: "EXCHANGE (CEX)" },
  { name: "CARDANO", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "CELO", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "CENTRIFUGE", type: "ISSUER", subType: "BROKER/OVER-THE-COUNTER (OTC)" },
  { name: "CETUS PROTOCOL", type: "PROTOCOL", subType: "SMART CONTRACTS" },
  { name: "CHAINFLIP", type: "PROTOCOL", subType: "SMART CONTRACTS" },
  { name: "CHEN GUO", type: "NOT APPLICABLE", subType: "INDIVIDUAL" },
  { name: "CIRCLE INTERNET FINANCIAL", type: "TRADING VENUE", subType: "EXCHANGE (CEX)" },
  { name: "CITREA", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "COINBASE", type: "TRADING VENUE", subType: "EXCHANGE (CEX)" },
  { name: "COINROUTES INC", type: "SERVICE PROVIDER/VENDOR", subType: "SERVICE PROVIDER" },
  { name: "CONNEXT FOUNDATION - EVERCLEAR", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "COWSWAP DAO", type: "PROTOCOL", subType: "SMART CONTRACTS" },
  { name: "DBS DIGITAL EXCHANGE (DDEX)", type: "TRADING VENUE", subType: "EXCHANGE (CEX)" },
  { name: "DEDUST", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "DEXALOT", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "DIGITAL FORCE LTD.", type: "LENDER", subType: "LENDER" },
  { name: "DIGITAL GAS MANAGEMENT LIMITED (ETHGAS)", type: "INVESTMENT", subType: "CORPORATION" },
  { name: "DOGE", type: "BLOCKCHAIN", subType: "NOT APPLICABLE" },
  { name: "DOURO LABS", type: "PROTOCOL", subType: "CORPORATION" },
  { name: "DRIFT", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "DYDX", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "ETHENA LABS GMBH", type: "ISSUER", subType: "BROKER/OVER-THE-COUNTER (OTC)" },
  { name: "ETHEREUM", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "ETHGAS", type: "TRADING VENUE", subType: "VENDOR" },
  { name: "FRAX", type: "ISSUER", subType: "BROKER/OVER-THE-COUNTER (OTC)" },
  { name: "GATE", type: "TRADING VENUE", subType: "EXCHANGE (CEX)" },
  { name: "GMR LIMITED", type: "LENDER", subType: "CORPORATION" },
  { name: "GNOSIS", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "GRVT MARKETS LIMITED (GML)", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "HASHFLOW FOUNDATION", type: "PROTOCOL", subType: "SMART CONTRACTS" },
  { name: "HEDERA", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "HELIUS BLOCKCHAIN TECHNOLOGIES, INC.", type: "SERVICE PROVIDER/VENDOR", subType: "CORPORATION" },
  { name: "HUOBI", type: "TRADING VENUE", subType: "EXCHANGE (CEX)" },
  { name: "HYPERCORE", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "HYPEREVM", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "HYPERLIQUID", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "INJECTIVE", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "INTERACTIVE BROKERS", type: "TRADING VENUE", subType: "BROKER/OVER-THE-COUNTER (OTC)" },
  { name: "IZISWAP", type: "TRADING VENUE", subType: "EXCHANGE (CEX)" },
  { name: "IZUMI", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "JITO NETWORK", type: "PROTOCOL", subType: "BLOCKCHAIN" },
  { name: "JUPITER", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "JUPITER Z", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "KANA LABS LIMITED", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "KODIAK", type: "TRADING VENUE", subType: "SMART CONTRACTS" },
  { name: "KRAKEN", type: "TRADING VENUE", subType: "EXCHANGE (CEX)" },
  { name: "KUCOIN", type: "TRADING VENUE", subType: "EXCHANGE (CEX)" },
  { name: "KYBERSWAP", type: "PROTOCOL", subType: "SMART CONTRACTS" },
  { name: "LBANK EXCHANGE", type: "TRADING VENUE", subType: "EXCHANGE (CEX)" },
  { name: "LI.FI", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "LIGHTER", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "LINEA", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "MANTLE", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "MANTRA", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "MAYAN FOUNDATION", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "MERCHANT MOE", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "META PROTOCOL INTERNATIONAL, INC (ZETA)", type: "LENDER", subType: "LENDER" },
  { name: "MEXC", type: "TRADING VENUE", subType: "EXCHANGE (CEX)" },
  { name: "MIDAS SOFTWARDS GMBH", type: "ISSUER", subType: "BROKER/OVER-THE-COUNTER (OTC)" },
  { name: "MODE", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "NATIVE MARKETS", type: "ISSUER", subType: "BROKER/OVER-THE-COUNTER (OTC)" },
  { name: "NATIVE TECHNOLOGY LIMITED", type: "TRADING VENUE", subType: "CORPORATION" },
  { name: "OKX", type: "TRADING VENUE", subType: "EXCHANGE (CEX)" },
  { name: "OKX (SG)", type: "TRADING VENUE", subType: "EXCHANGE (CEX)" },
  { name: "OKX DEX", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "OKX DEX AGGREGATOR", type: "PROTOCOL", subType: "SMART CONTRACTS" },
  { name: "ONDO GLOBAL MARKETS (BVI) LIMITED", type: "ISSUER", subType: "BROKER/OVER-THE-COUNTER (OTC)" },
  { name: "ONDO USDY LLC", type: "ISSUER", subType: "BROKER/OVER-THE-COUNTER (OTC)" },
  { name: "OPTIMEX", type: "PROTOCOL", subType: "SMART CONTRACTS" },
  { name: "OPTIMISM", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "PANCAKESWAP (PCS)", type: "PROTOCOL", subType: "SMART CONTRACTS" },
  { name: "PANCAKESWAP-X", type: "PROTOCOL", subType: "SMART CONTRACTS" },
  { name: "PARADEX", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "PARASWAP", type: "PROTOCOL", subType: "SMART CONTRACTS" },
  { name: "PEAQ", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "PLASMA", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "POLKADOT", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "POLYGON", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "PRM LBS LIMITED (ARKIS)", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "PROPELLERHEADS AG", type: "INVESTMENT", subType: "CORPORATION" },
  { name: "PYTH DATA ASSOCIATION (PYTH)", type: "PROTOCOL", subType: "CORPORATION" },
  { name: "RAYDIUM", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "REYA", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "RIPPLE", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "ROUTER PROTOCOL", type: "PROTOCOL", subType: "SMART CONTRACTS" },
  { name: "SAGAEVM", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "SCROLL", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "SEARCHER.WTF", type: "SERVICE PROVIDER/VENDOR", subType: "CORPORATION" },
  { name: "SHADOW", type: "TRADING VENUE", subType: "SMART CONTRACTS" },
  { name: "SHADOW_SIMULATION", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "SHINAMI", type: "SERVICE PROVIDER/VENDOR", subType: "CORPORATION" },
  { name: "SODEX", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "SOLANA", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "SONEIUM", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "SONIC", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "SOSOVALUE", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "SPRING MUD LIMITED", type: "LENDER", subType: "LENDER" },
  { name: "SPRING MUD PTE LTD", type: "LENDER", subType: "LENDER" },
  { name: "SQUID", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "STARGATE", type: "TRADING VENUE", subType: "SMART CONTRACTS" },
  { name: "STELLAR", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "STON.FI", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "SUI", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "SUPERSTATE INC", type: "ISSUER", subType: "BROKER/OVER-THE-COUNTER (OTC)" },
  { name: "SYNCSWAP", type: "TRADING VENUE", subType: "SMART CONTRACTS" },
  { name: "SYNFUTURES DEX", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "T1 LABS INC. (T1 PROTOCOL)", type: "INVESTMENT", subType: "CORPORATION" },
  { name: "TEMPO", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "TESTING ACCOUNTS", type: "NOT APPLICABLE", subType: "INDIVIDUAL" },
  { name: "THRUSTER", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "TOKKA LABS PTE LTD", type: "NOT APPLICABLE", subType: "NOT APPLICABLE" },
  { name: "TOKKA TREASURY", type: "INTERNAL COUNTERPARTY", subType: "CORPORATION" },
  { name: "TON", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "TPLUS LABS INC", type: "INVESTMENT", subType: "CORPORATION" },
  { name: "TRON", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "TURBOS", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "UNICHAIN", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "UNISWAP", type: "PROTOCOL", subType: "SMART CONTRACTS" },
  { name: "UNISWAPX", type: "TRADING VENUE", subType: "SMART CONTRACTS" },
  { name: "VERTEX PROTOCOL", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "VERTEX_ARBITRUM", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "VERTEX_BLITZ", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "VERTEX_MANTLE", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "VERTEX_SEI", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "WISDOMTREE", type: "ISSUER", subType: "CORPORATION" },
  { name: "WORMHOLE", type: "TRADING VENUE", subType: "EXCHANGE (DEX)" },
  { name: "XRPLEVM", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "ZEROEX INC (0X LABS)", type: "PROTOCOL", subType: "SMART CONTRACTS" },
  { name: "ZEROEX INC_V3 (0X LABS)", type: "PROTOCOL", subType: "SMART CONTRACTS" },
  { name: "ZETA", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
  { name: "ZKSYNC", type: "BLOCKCHAIN", subType: "BLOCKCHAIN" },
];
const CATEGORIES = ["SPOT", "FUTURE", "CASHFLOW", "LOAN"];
const VENUE_TYPES = ["CEX", "DEX", "OnChain", "OTC", "Internal", "RWA"];

// FUTURE constants
const FUTURE_CONTRACT_TYPES = ["PERP", "DATED"];
const FUTURE_MARGIN_MODES = ["CROSS", "ISOLATED"];

// CASHFLOW constants — direction-aware subtype menus.
// Captures the original brainstorm's 34 trade-types collapsed into one flow.
const CASHFLOW_DIRECTIONS = ["PAY", "RECEIVE"];
// Placeholder cashflow types — backend will swap to MySQL select_category=CASHFLOW TYPE (28 values).
const CASHFLOW_TYPES = [
  "INTER PTF FUNDING",
  "INTEREST EXPENSE",
  "INTEREST INCOME",
  "TRADING FEES",
  "FUNDING FEE",
  "GAS FEE",
  "FEE REBATE",
  "DEPOSIT",
  "WITHDRAW",
  "OTHERS",
];
// Trade lifecycle status — SPOT / FUTURE / CASHFLOW share this enum.
// Matches the trades_cashflow.status CHECK constraint in UAT Postgres.
// Default is PENDING on a fresh booking.
const TRADE_STATUSES = [
  "PENDING",
  "CONFIRMED",
  "PROCESSED",
  "SETTLED",
  "CANCELLED",
];
// LOAN lifecycle: LIVE (outstanding) → MATURED (settled), with CANCELLED
// as a terminal state when a loan is reversed pre-maturity. Default LIVE on
// a fresh booking.
const LOAN_STATUSES = ["LIVE", "MATURED", "CANCELLED"];
const statusOptionsFor = (category) =>
  category === "LOAN" ? LOAN_STATUSES : TRADE_STATUSES;
const defaultStatusFor = (category) =>
  category === "LOAN" ? "LIVE" : "PENDING";
const VENUES = {
  CEX: ["Binance", "Binance Sub", "Kraken", "Bitget", "OKX", "Coinbase"],
  DEX: ["Hyperliquid", "dYdX", "GMX", "Jupiter", "Uniswap"],
  OnChain: ["ETH Wallet", "SOL Wallet", "ARB Wallet", "BASE Wallet", "TRON Wallet"],
  OTC: ["OTC Counterparty"],
  Internal: ["Treasury"],
  RWA: ["Ondo", "Backed.fi", "BlackRock BUIDL", "Paxos"],
};
// Asset symbols snapshot — sourced from reference_data.instrument_token_grouped
// via src/data/tokens.js (947 active tokens, deduped by commonIdentifier).
const ASSETS = ASSET_SYMBOLS;
// Placeholder loan types — backend will swap to a DB-backed list later.
// Adjust freely; first value is the default on a fresh booking.
const LOAN_TYPES = [
  "TERM",
  "REVOLVING",
  "MARGIN",
  "REPO",
  "DEFI LENDING",
  "VIP LOAN",
  "BRIDGE",
];

// Source: reference_data.user — WHERE isActive=1 AND roleName='superadmin'
// (5 active superadmins on sg-ro-mysql, snapshot 2026-05-13)
// TODO: replace with live fetch once the booking-API service is up.
const SUPERADMIN_USERS = [
  "danny.pang",
  "irven.heng",
  "mo",
  "weehowe.ang",
  "yaqing.bie",
];

// Display name + role for sidebar profile chip. All 5 are roleName=superadmin
// in MySQL; presented as "Admin" to match the dashboard's labelling.
const USER_PROFILES = {
  "danny.pang":   { name: "Danny Pang",   role: "Admin" },
  "irven.heng":   { name: "Irven Heng",   role: "Admin" },
  "mo":           { name: "Mo",           role: "Admin" },
  "weehowe.ang":  { name: "Wee Howe Ang", role: "Admin" },
  "yaqing.bie":   { name: "Yaqing Bie",   role: "Admin" },
};

// Internal-trade-id prefix per category. The 8-digit suffix is a placeholder
// queue number — backend will allocate the real sequence on submit.
const TRADE_ID_PREFIX = {
  SPOT: "MFX",
  FUTURE: "MFP",
  CASHFLOW: "MCF",
  LOAN: "MLA",
};

const genTradeId = (category = "SPOT") => {
  // New trades show only the prefix as a placeholder. The numeric portion
  // is allocated server-side from trade_seq_<product> when the trade is
  // saved, so the deal_ref is only meaningful after submit.
  // CASHFLOW uses no separator (MCF + 8-digit pad); other products keep
  // the legacy dash-then-number convention.
  const prefix = TRADE_ID_PREFIX[category] || "MFX";
  return category === "CASHFLOW" ? prefix : `${prefix}-`;
};
const isoNow = () => new Date().toISOString();
// Current time formatted for <input type="datetime-local"> ("YYYY-MM-DDTHH:mm")
// Slicing from toISOString() means the value is UTC, not browser-local.
const nowUtc = () => new Date().toISOString().slice(0, 16);
// Today at 00:00 UTC (12 AM) — used as the default for trade/value date so
// users land on a clean midnight stamp instead of the current minute.
const today00Utc = () => new Date().toISOString().slice(0, 10) + "T00:00";
// Helpers for the fused date+time field: state stays as one
// "YYYY-MM-DDTHH:mm" string; the UI exposes a date <input> + a time <input>.
const splitDt = (dt) => {
  if (!dt) return { d: "", t: "00:00" };
  const [d, t = "00:00"] = dt.split("T");
  return { d, t: t.slice(0, 5) };
};
const joinDt = (d, t) => `${d || today00Utc().slice(0, 10)}T${(t || "00:00").slice(0, 5)}`;
const fmtSize = (b) => {
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / 1024 / 1024).toFixed(2)} MB`;
};

// ─────────────────────────────────────────────────────────────
// Atoms
// ─────────────────────────────────────────────────────────────
const Label = ({ children, required }) => (
  <label className={cls.label}>
    {children}
    {required && <span className="text-[#b91c1c] ml-1">*</span>}
  </label>
);

const Input = (props) => <input {...props} className={`${cls.input} ${props.className || ""}`} />;

// Format a clean numeric string with thousands separators ("1234.5" → "1,234.5").
// Leaves a trailing "." or empty integer part alone so a focused-then-blurred field
// without content doesn't render "NaN".
const fmtThousands = (s) => {
  if (s === "" || s == null) return "";
  const str = String(s);
  const neg = str.startsWith("-");
  const body = neg ? str.slice(1) : str;
  const [int, dec] = body.split(".");
  const withCommas = (int || "0").replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const out = dec !== undefined ? `${withCommas}.${dec}` : withCommas;
  return neg ? `-${out}` : out;
};

// Strip everything except digits, a single leading minus, and one decimal point.
const cleanNumeric = (s) => {
  const raw = String(s ?? "").replace(/,/g, "");
  let r = raw.replace(/[^\d.\-]/g, "");
  // Allow leading "-" only at position 0
  r = r.replace(/(?!^)-/g, "");
  // Keep only the first "."
  const firstDot = r.indexOf(".");
  if (firstDot >= 0) {
    r = r.slice(0, firstDot + 1) + r.slice(firstDot + 1).replace(/\./g, "");
  }
  return r;
};

// Numeric input with thousands separators displayed when not focused.
// Stores a clean numeric string ("1234.5") in form state so compute math works,
// renders "1,234.5" once the user tabs/clicks away.
const NumberInput = ({ value, onChange, className, ...rest }) => {
  const [focused, setFocused] = useState(false);
  const display = focused ? (value ?? "") : fmtThousands(value);
  return (
    <input
      {...rest}
      type="text"
      inputMode="decimal"
      value={display}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      onChange={(e) => onChange(cleanNumeric(e.target.value))}
      className={`${cls.input} ${className || ""}`}
    />
  );
};
const Select = ({ children, ...props }) => (
  <div className="relative">
    <select {...props} className={`${cls.select} ${props.className || ""}`}>
      {children}
    </select>
    <span
      className="absolute right-2 top-1/2 -translate-y-1/2 text-[#6a665c] pointer-events-none text-[9px] font-mono"
      aria-hidden
    >
      ▾
    </span>
  </div>
);
const Textarea = (props) => (
  <textarea {...props} className={`${cls.textarea} ${props.className || ""}`} />
);

// Normalize whatever the user types into a strict "HH:MM" 24-hour string.
// Accepts "9", "9:5", "0930", "23 45", "26:99", etc. and clamps to a sane value.
const normalizeTime24 = (raw) => {
  if (raw == null) return "";
  const digits = String(raw).replace(/\D/g, "").slice(0, 4);
  if (!digits) return "";
  let h, m;
  if (digits.length <= 2) {
    h = parseInt(digits, 10);
    m = 0;
  } else {
    h = parseInt(digits.slice(0, digits.length - 2), 10);
    m = parseInt(digits.slice(-2), 10);
  }
  if (isNaN(h)) h = 0;
  if (isNaN(m)) m = 0;
  h = Math.max(0, Math.min(23, h));
  m = Math.max(0, Math.min(59, m));
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
};

const MONTH_NAMES = [
  "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
  "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
];
const WEEKDAY_HEADERS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"];
const HOURS = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, "0"));
const MINUTES = Array.from({ length: 60 }, (_, i) => String(i).padStart(2, "0"));

// Scrollable selector column for hour or minute — fixed-height with
// scroll-snap, selected row highlighted in orange.
const TimeColumn = ({ values, selected, onSelect, ariaLabel }) => {
  const ref = useRef(null);
  // Center the selected row whenever it changes (or the column mounts)
  useEffect(() => {
    const el = ref.current?.querySelector('[data-sel="true"]');
    if (el && el.scrollIntoView) el.scrollIntoView({ block: "center" });
  }, [selected]);
  return (
    <div
      ref={ref}
      role="listbox"
      aria-label={ariaLabel}
      className="overflow-y-auto flex-1"
      style={{
        height: 112,
        background: "#f8f6f1",
        border: `1px solid ${BB.border}`,
        scrollSnapType: "y mandatory",
        scrollbarWidth: "thin",
      }}
    >
      {values.map((v) => {
        const isSel = v === selected;
        return (
          <button
            key={v}
            type="button"
            data-sel={isSel ? "true" : "false"}
            onClick={() => onSelect(v)}
            className="block w-full text-center py-1 text-[12px] font-mono transition-colors"
            style={{
              color: isSel ? "#ffffff" : BB.text,
              background: isSel ? BB.orange : "transparent",
              scrollSnapAlign: "center",
              fontWeight: isSel ? 600 : 400,
            }}
            onMouseEnter={(ev) => {
              if (!isSel) ev.currentTarget.style.background = "#ece7dd";
            }}
            onMouseLeave={(ev) => {
              if (!isSel) ev.currentTarget.style.background = "transparent";
            }}
          >
            {v}
          </button>
        );
      })}
    </div>
  );
};

// Single combined date+time picker. One trigger button, one popup containing
// both a month calendar AND a 24h-only HH:MM input. Fully custom-rendered so
// the OS locale can never inject AM/PM.
const DateTimePicker24 = ({ value, onChange, syncLabel, onSync }) => {
  const { d, t } = splitDt(value);
  const [open, setOpen] = useState(false);
  const [viewYM, setViewYM] = useState(() => {
    const ref = d ? new Date(`${d}T00:00:00Z`) : new Date();
    return { y: ref.getUTCFullYear(), m: ref.getUTCMonth() };
  });
  const [timeDraft, setTimeDraft] = useState(t);
  const popRef = useRef(null);
  const triggerRef = useRef(null);

  // Keep local draft in sync when parent value changes (sync checkbox)
  useEffect(() => setTimeDraft(t), [t]);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (popRef.current?.contains(e.target)) return;
      if (triggerRef.current?.contains(e.target)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  // Re-anchor the calendar to the currently-selected date whenever the popup opens
  useEffect(() => {
    if (!open) return;
    if (!d) return;
    const ref = new Date(`${d}T00:00:00Z`);
    setViewYM({ y: ref.getUTCFullYear(), m: ref.getUTCMonth() });
  }, [open, d]);

  const commitTime = () => {
    const normalized = normalizeTime24(timeDraft) || "00:00";
    setTimeDraft(normalized);
    onChange(joinDt(d, normalized));
  };

  const pickDate = (yyyy, mm, dd) => {
    // Clicking a new date snaps time → 00:00
    const newD = `${yyyy}-${String(mm + 1).padStart(2, "0")}-${String(dd).padStart(2, "0")}`;
    setTimeDraft("00:00");
    onChange(joinDt(newD, "00:00"));
  };

  const setNow = () => {
    const now = new Date();
    const yyyy = now.getUTCFullYear();
    const mm = now.getUTCMonth();
    const dd = now.getUTCDate();
    const hh = String(now.getUTCHours()).padStart(2, "0");
    const mi = String(now.getUTCMinutes()).padStart(2, "0");
    const newD = `${yyyy}-${String(mm + 1).padStart(2, "0")}-${String(dd).padStart(2, "0")}`;
    setViewYM({ y: yyyy, m: mm });
    setTimeDraft(`${hh}:${mi}`);
    onChange(joinDt(newD, `${hh}:${mi}`));
  };

  const setMidnightToday = () => {
    const now = new Date();
    const yyyy = now.getUTCFullYear();
    const mm = now.getUTCMonth();
    const dd = now.getUTCDate();
    const newD = `${yyyy}-${String(mm + 1).padStart(2, "0")}-${String(dd).padStart(2, "0")}`;
    setViewYM({ y: yyyy, m: mm });
    setTimeDraft("00:00");
    onChange(joinDt(newD, "00:00"));
  };

  // Build the calendar grid for viewYM (Mon-first week)
  const { y: vy, m: vm } = viewYM;
  const firstDow = new Date(Date.UTC(vy, vm, 1)).getUTCDay(); // 0=Sun
  const leadingBlanks = (firstDow + 6) % 7; // Mon-first
  const daysInMonth = new Date(Date.UTC(vy, vm + 1, 0)).getUTCDate();
  const today = new Date();
  const todayStr = `${today.getUTCFullYear()}-${String(today.getUTCMonth() + 1).padStart(2, "0")}-${String(today.getUTCDate()).padStart(2, "0")}`;

  const cells = [];
  for (let i = 0; i < leadingBlanks; i++) cells.push(null);
  for (let i = 1; i <= daysInMonth; i++) cells.push(i);
  while (cells.length % 7 !== 0) cells.push(null);

  const goPrev = () => setViewYM((s) => (s.m === 0 ? { y: s.y - 1, m: 11 } : { ...s, m: s.m - 1 }));
  const goNext = () => setViewYM((s) => (s.m === 11 ? { y: s.y + 1, m: 0 } : { ...s, m: s.m + 1 }));

  return (
    <div className="relative w-full">
      {/* Trigger — looks like the rest of the form's inputs */}
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 text-[12px] text-[#0d0d0d] font-mono text-left transition-colors"
        style={{
          background: "#f8f6f1",
          border: `1px solid ${open ? BB.orange : BB.border}`,
        }}
        onMouseEnter={(ev) => {
          if (open) return;
          ev.currentTarget.style.background = "#ffffff";
          ev.currentTarget.style.borderColor = "#6a665c";
        }}
        onMouseLeave={(ev) => {
          if (open) return;
          ev.currentTarget.style.background = "#f8f6f1";
          ev.currentTarget.style.borderColor = BB.border;
        }}
      >
        <Calendar size={12} style={{ color: BB.orange }} />
        <span className="flex-1 tracking-[0.04em]">
          {d || "----"} <span style={{ color: BB.faint }}>·</span> {t}
        </span>
        <span className="text-[10px]" style={{ color: BB.faint }}>▾</span>
      </button>

      {open && (
        <div
          ref={popRef}
          className="absolute z-50 mt-1 p-2.5"
          style={{
            background: "#ffffff",
            border: `1px solid ${BB.orange}`,
            boxShadow: "0 12px 32px rgba(13,13,13,0.12)",
            minWidth: 380,
          }}
        >
          {/* Body: calendar on the left, time selector on the right */}
          <div className="flex gap-3 mb-2.5">
            {/* ── LEFT: calendar ── */}
            <div className="flex-1 min-w-0">
              {/* Header — month/year + nav */}
              <div className="flex items-center justify-between mb-2 font-mono">
                <button
                  type="button"
                  onClick={goPrev}
                  className="p-1"
                  style={{ color: BB.amber }}
                  aria-label="Previous month"
                >
                  <ChevronLeft size={14} />
                </button>
                <div className="text-[11px] tracking-[0.24em] uppercase" style={{ color: BB.orange }}>
                  {MONTH_NAMES[vm]} {vy}
                </div>
                <button
                  type="button"
                  onClick={goNext}
                  className="p-1"
                  style={{ color: BB.amber }}
                  aria-label="Next month"
                >
                  <ChevronRight size={14} />
                </button>
              </div>

              {/* Weekday header */}
              <div className="grid grid-cols-7 gap-0.5 mb-1">
                {WEEKDAY_HEADERS.map((w) => (
                  <div
                    key={w}
                    className="text-center text-[9px] tracking-[0.15em] font-mono py-0.5"
                    style={{ color: BB.mute }}
                  >
                    {w}
                  </div>
                ))}
              </div>

              {/* Day grid */}
              <div className="grid grid-cols-7 gap-0.5">
                {cells.map((cell, i) => {
                  if (cell == null) return <div key={i} />;
                  const cellStr = `${vy}-${String(vm + 1).padStart(2, "0")}-${String(cell).padStart(2, "0")}`;
                  const isSelected = cellStr === d;
                  const isToday = cellStr === todayStr;
                  return (
                    <button
                      key={i}
                      type="button"
                      onClick={() => pickDate(vy, vm, cell)}
                      className="text-center text-[11px] font-mono py-1.5 transition-colors"
                      style={{
                        background: isSelected ? BB.orange : "transparent",
                        color: isSelected ? "#ffffff" : isToday ? BB.cyan : BB.text,
                        border: isToday && !isSelected ? `1px solid ${BB.cyan}` : "1px solid transparent",
                      }}
                      onMouseEnter={(ev) => {
                        if (!isSelected) ev.currentTarget.style.background = "#ece7dd";
                      }}
                      onMouseLeave={(ev) => {
                        if (!isSelected) ev.currentTarget.style.background = "transparent";
                      }}
                    >
                      {cell}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* ── RIGHT: time selector ── */}
            <div style={{ width: 116 }} className="flex flex-col">
              <div className="flex items-center justify-between mb-1">
                <span className="text-[9px] uppercase tracking-[0.22em] font-mono" style={{ color: BB.mute }}>
                  Time · UTC
                </span>
              </div>
              <div className="text-[14px] font-mono tracking-[0.1em] mb-1.5 text-center py-1" style={{ color: BB.amber, background: "#ffffff", border: `1px solid ${BB.border}` }}>
                {timeDraft || "00:00"}
              </div>
              <div className="flex items-stretch gap-1 flex-1">
                <TimeColumn
                  values={HOURS}
                  selected={(timeDraft || "00:00").split(":")[0]}
                  ariaLabel="Hour (00-23)"
                  onSelect={(hh) => {
                    const mm = (timeDraft || "00:00").split(":")[1] || "00";
                    const t = `${hh}:${mm}`;
                    setTimeDraft(t);
                    onChange(joinDt(d, t));
                  }}
                />
                <span className="self-center text-[14px] font-mono" style={{ color: BB.orange }}>
                  :
                </span>
                <TimeColumn
                  values={MINUTES}
                  selected={(timeDraft || "00:00").split(":")[1] || "00"}
                  ariaLabel="Minute (00-59)"
                  onSelect={(mm) => {
                    const hh = (timeDraft || "00:00").split(":")[0] || "00";
                    const t = `${hh}:${mm}`;
                    setTimeDraft(t);
                    onChange(joinDt(d, t));
                  }}
                />
              </div>
            </div>
          </div>

          {/* Action row */}
          <div className="flex gap-1.5">
            <button
              type="button"
              onClick={setMidnightToday}
              className="flex-1 py-1 text-[10px] uppercase tracking-[0.18em] font-mono transition-colors"
              style={{
                background: BB.surface2,
                color: BB.dim,
                border: `1px solid ${BB.border}`,
              }}
              onMouseEnter={(ev) => { ev.currentTarget.style.borderColor = BB.amber; ev.currentTarget.style.color = BB.amber; }}
              onMouseLeave={(ev) => { ev.currentTarget.style.borderColor = BB.border; ev.currentTarget.style.color = BB.dim; }}
            >
              Today · 00:00
            </button>
            <button
              type="button"
              onClick={setNow}
              className="flex-1 py-1 text-[10px] uppercase tracking-[0.18em] font-mono transition-colors"
              style={{
                background: BB.surface2,
                color: BB.dim,
                border: `1px solid ${BB.border}`,
              }}
              onMouseEnter={(ev) => { ev.currentTarget.style.borderColor = BB.cyan; ev.currentTarget.style.color = BB.cyan; }}
              onMouseLeave={(ev) => { ev.currentTarget.style.borderColor = BB.border; ev.currentTarget.style.color = BB.dim; }}
            >
              Now UTC
            </button>
            <button
              type="button"
              onClick={() => { commitTime(); setOpen(false); }}
              className="flex-1 py-1 text-[10px] uppercase tracking-[0.18em] font-mono font-semibold transition-colors"
              style={{
                background: BB.orange,
                color: "#ffffff",
                border: `1px solid ${BB.orange}`,
              }}
              onMouseEnter={(ev) => { ev.currentTarget.style.background = BB.amber; }}
              onMouseLeave={(ev) => { ev.currentTarget.style.background = BB.orange; }}
            >
              Done
            </button>
          </div>

          {/* Sync row (bottom) — push this picker's value to the linked field */}
          {onSync && syncLabel && (
            <button
              type="button"
              onClick={() => {
                commitTime();
                onSync(joinDt(d, normalizeTime24(timeDraft) || "00:00"));
              }}
              className="w-full mt-1.5 py-1 text-[10px] uppercase tracking-[0.2em] font-mono transition-colors flex items-center justify-center gap-1.5"
              style={{
                background: "transparent",
                color: BB.cyan,
                border: `1px solid ${BB.cyan}`,
              }}
              onMouseEnter={(ev) => {
                ev.currentTarget.style.background = "#ecfeff";
              }}
              onMouseLeave={(ev) => {
                ev.currentTarget.style.background = "transparent";
              }}
              title="Copy this value to the linked field"
            >
              <Link2 size={11} /> {syncLabel}
            </button>
          )}
        </div>
      )}
    </div>
  );
};

const Field = ({ label, required, children, span = 1, hint }) => (
  <div style={{ gridColumn: `span ${span}` }}>
    <div className="flex items-baseline justify-between">
      <Label required={required}>{label}</Label>
      {hint && (
        <span
          className="text-[9px] tracking-[0.2em] uppercase font-mono mb-1"
          style={{ color: BB.orange }}
        >
          {hint}
        </span>
      )}
    </div>
    {children}
  </div>
);

// Note: `kicker` and `accent` props are intentionally ignored — section
// headers are uniformly rendered in ink black with no kicker subtitle and
// no corner abbreviation. The props remain for backwards compatibility
// with existing call sites; either drop them at the call site or leave.
const Section = ({ title, children }) => (
  <div className="mb-5">
    <div
      className="flex items-baseline gap-3 mb-4 pb-2"
      style={{ borderBottom: `1px solid ${BB.border}` }}
    >
      <span
        className="text-[10px] tracking-[0.24em] uppercase font-mono font-semibold"
        style={{ color: BB.text }}
      >
        ◆ {title}
      </span>
      <span className="flex-1" />
    </div>
    <div className="grid grid-cols-12 gap-2.5">{children}</div>
  </div>
);

// Function-key style category button (F1..F6)
const FKey = ({ index, label, active, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    className="group flex items-stretch font-mono text-[11px] tracking-[0.18em] uppercase border transition-colors"
    style={{
      borderColor: active ? BB.orange : BB.border,
      background: active ? BB.orange : "transparent",
      color: active ? "#ffffff" : BB.text,
    }}
    onMouseEnter={(ev) => {
      if (active) return;
      ev.currentTarget.style.borderColor = "#6a665c";
      ev.currentTarget.style.background = "#ffffff";
      ev.currentTarget.firstChild.style.borderColor = "#6a665c";
      ev.currentTarget.firstChild.style.background = "#ffffff";
    }}
    onMouseLeave={(ev) => {
      if (active) return;
      ev.currentTarget.style.borderColor = BB.border;
      ev.currentTarget.style.background = "transparent";
      ev.currentTarget.firstChild.style.borderColor = BB.border;
      ev.currentTarget.firstChild.style.background = BB.surface;
    }}
  >
    <span
      className="px-1.5 py-1 border-r font-semibold transition-colors"
      style={{
        borderColor: active ? "#ffffff" : BB.border,
        color: active ? "#ffffff" : BB.amber,
        background: active ? BB.orange : BB.surface,
      }}
    >
      F{index + 1}
    </span>
    <span className="px-2.5 py-1">{label}</span>
  </button>
);

// ─────────────────────────────────────────────────────────────
// Searchable portfolio combobox — type to filter by number or name.
// Replaces a native <select> for fields where the option list is
// long and scrolling is slow.
// ─────────────────────────────────────────────────────────────
const PortfolioPicker = ({ value, onChange, options }) => {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const wrapRef = useRef(null);
  const inputRef = useRef(null);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (!wrapRef.current?.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  // Auto-focus the search input when opened
  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  const selected = options.find((o) => String(o.number) === String(value));
  const q = search.trim().toLowerCase();
  const filtered = q
    ? options.filter(
        (o) =>
          String(o.number).includes(q) || o.name.toLowerCase().includes(q)
      )
    : options;

  return (
    <div ref={wrapRef} className="relative w-full">
      <button
        type="button"
        onClick={() => {
          setOpen((o) => !o);
          setSearch("");
        }}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 text-[12px] text-[#0d0d0d] font-mono text-left transition-colors"
        style={{
          background: "#f8f6f1",
          border: `1px solid ${open ? "#1f63ea" : "#d9d4c7"}`,
        }}
        onMouseEnter={(ev) => {
          if (open) return;
          ev.currentTarget.style.background = "#ffffff";
          ev.currentTarget.style.borderColor = "#6a665c";
        }}
        onMouseLeave={(ev) => {
          if (open) return;
          ev.currentTarget.style.background = "#f8f6f1";
          ev.currentTarget.style.borderColor = "#d9d4c7";
        }}
      >
        <span className="flex-1 truncate">
          {selected ? (
            <>
              <span style={{ color: "#1f63ea" }}>{selected.number}</span>
              <span style={{ color: "#9a9488" }}> · </span>
              <span>{selected.name}</span>
            </>
          ) : (
            <span style={{ color: "#9a9488" }}>— select portfolio —</span>
          )}
        </span>
        <span className="text-[10px]" style={{ color: "#9a9488" }}>
          ▾
        </span>
      </button>

      {open && (
        <div
          className="absolute z-50 mt-1 left-0"
          style={{
            background: "#ffffff",
            border: "1px solid #1f63ea",
            boxShadow: "0 12px 32px rgba(13,13,13,0.12)",
            minWidth: "100%",
            width: 420,
          }}
        >
          <div className="p-1.5" style={{ borderBottom: "1px solid #d9d4c7" }}>
            <input
              ref={inputRef}
              type="text"
              placeholder="Type to filter — number or name…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  e.preventDefault();
                  setOpen(false);
                }
                if (e.key === "Enter" && filtered.length === 1) {
                  e.preventDefault();
                  onChange(String(filtered[0].number));
                  setOpen(false);
                  setSearch("");
                }
              }}
              className="w-full bg-[#f8f6f1] border border-[#d9d4c7] px-2.5 py-1.5 text-[12px] text-[#0d0d0d] font-mono focus:outline-none focus:border-[#0d0d0d] focus:bg-[#ffffff] placeholder:text-[#9a9488] rounded-none caret-[#1f63ea]"
            />
          </div>
          <div className="overflow-y-auto" style={{ maxHeight: 280 }}>
            {filtered.length === 0 && (
              <div className="text-[11px] text-center py-3 font-mono" style={{ color: "#9a9488" }}>
                No matching portfolios
              </div>
            )}
            {filtered.map((o) => {
              const isSel = String(value) === String(o.number);
              return (
                <button
                  key={o.number}
                  type="button"
                  onClick={() => {
                    onChange(String(o.number));
                    setOpen(false);
                    setSearch("");
                  }}
                  className="w-full text-left px-3 py-1.5 text-[12px] font-mono transition-colors"
                  style={{
                    background: isSel ? "#ece7dd" : "transparent",
                    borderLeft: `2px solid ${isSel ? "#1f63ea" : "transparent"}`,
                  }}
                  onMouseEnter={(ev) => {
                    if (!isSel) ev.currentTarget.style.background = "#ece7dd";
                  }}
                  onMouseLeave={(ev) => {
                    if (!isSel) ev.currentTarget.style.background = "transparent";
                  }}
                >
                  <span style={{ color: "#1f63ea", fontWeight: 600 }}>{o.number}</span>
                  <span style={{ color: "#9a9488" }}> · </span>
                  <span style={{ color: "#0d0d0d" }}>{o.name}</span>
                  <div className="text-[9px] mt-0.5 tracking-[0.16em] uppercase" style={{ color: "#6a665c" }}>
                    {o.entity}
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};

// Searchable counterparty combobox — value is the counterparty NAME (string).
// Filter is by name or subType (so typing "DEX" or "LENDER" narrows the list).
const CounterpartyPicker = ({ value, onChange, options }) => {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const wrapRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (!wrapRef.current?.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  const selected = options.find((o) => o.name === value);
  const q = search.trim().toLowerCase();
  const filtered = q
    ? options.filter(
        (o) =>
          o.name.toLowerCase().includes(q) ||
          (o.subType && o.subType.toLowerCase().includes(q)) ||
          (o.type && o.type.toLowerCase().includes(q))
      )
    : options;

  return (
    <div ref={wrapRef} className="relative w-full">
      <button
        type="button"
        onClick={() => {
          setOpen((o) => !o);
          setSearch("");
        }}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 text-[12px] text-[#0d0d0d] font-mono text-left transition-colors"
        style={{
          background: "#f8f6f1",
          border: `1px solid ${open ? "#1f63ea" : "#d9d4c7"}`,
        }}
        onMouseEnter={(ev) => {
          if (open) return;
          ev.currentTarget.style.background = "#ffffff";
          ev.currentTarget.style.borderColor = "#6a665c";
        }}
        onMouseLeave={(ev) => {
          if (open) return;
          ev.currentTarget.style.background = "#f8f6f1";
          ev.currentTarget.style.borderColor = "#d9d4c7";
        }}
      >
        <span className="flex-1 truncate">
          {selected ? (
            <>
              <span>{selected.name}</span>
              {selected.subType && (
                <span style={{ color: "#9a9488" }}> · {selected.subType}</span>
              )}
            </>
          ) : (
            <span style={{ color: "#9a9488" }}>— select counterparty —</span>
          )}
        </span>
        <span className="text-[10px]" style={{ color: "#9a9488" }}>
          ▾
        </span>
      </button>

      {open && (
        <div
          className="absolute z-50 mt-1 left-0"
          style={{
            background: "#ffffff",
            border: "1px solid #1f63ea",
            boxShadow: "0 12px 32px rgba(13,13,13,0.12)",
            minWidth: "100%",
            width: 460,
          }}
        >
          <div className="p-1.5" style={{ borderBottom: "1px solid #d9d4c7" }}>
            <input
              ref={inputRef}
              type="text"
              placeholder="Type to filter — name, type, sub-type…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  e.preventDefault();
                  setOpen(false);
                }
                if (e.key === "Enter" && filtered.length === 1) {
                  e.preventDefault();
                  onChange(filtered[0].name);
                  setOpen(false);
                  setSearch("");
                }
              }}
              className="w-full bg-[#f8f6f1] border border-[#d9d4c7] px-2.5 py-1.5 text-[12px] text-[#0d0d0d] font-mono focus:outline-none focus:border-[#0d0d0d] focus:bg-[#ffffff] placeholder:text-[#9a9488] rounded-none caret-[#1f63ea]"
            />
          </div>
          <div className="overflow-y-auto" style={{ maxHeight: 320 }}>
            {filtered.length === 0 && (
              <div className="text-[11px] text-center py-3 font-mono" style={{ color: "#9a9488" }}>
                No matching counterparties
              </div>
            )}
            {filtered.map((o) => {
              const isSel = value === o.name;
              return (
                <button
                  key={o.name}
                  type="button"
                  onClick={() => {
                    onChange(o.name);
                    setOpen(false);
                    setSearch("");
                  }}
                  className="w-full text-left px-3 py-1.5 text-[12px] font-mono transition-colors"
                  style={{
                    background: isSel ? "#ece7dd" : "transparent",
                    borderLeft: `2px solid ${isSel ? "#1f63ea" : "transparent"}`,
                  }}
                  onMouseEnter={(ev) => {
                    if (!isSel) ev.currentTarget.style.background = "#ece7dd";
                  }}
                  onMouseLeave={(ev) => {
                    if (!isSel) ev.currentTarget.style.background = "transparent";
                  }}
                >
                  <span style={{ color: "#0d0d0d", fontWeight: 500 }}>{o.name}</span>
                  <div className="text-[9px] mt-0.5 tracking-[0.16em] uppercase" style={{ color: "#6a665c" }}>
                    {o.type}{o.subType ? ` · ${o.subType}` : ""}
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};

// Searchable asset combobox — value is the token SYMBOL (string).
// Options come from TOKENS (snapshot of reference_data.instrument_token_grouped).
// Filter matches symbol or long name (e.g. typing "apple" finds AAPLON/AAPLX).
const AssetPicker = ({ value, onChange, options, placeholder = "— select asset —" }) => {
  const ctxTokens = useContext(TokensContext);
  const list = options || ctxTokens;
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const wrapRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (!wrapRef.current?.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  const selected = list.find((o) => o.symbol === value);
  const q = search.trim().toLowerCase();
  const filtered = q
    ? list.filter(
        (o) =>
          o.symbol.toLowerCase().includes(q) ||
          (o.name && o.name.toLowerCase().includes(q))
      )
    : list;

  return (
    <div ref={wrapRef} className="relative w-full">
      <button
        type="button"
        onClick={() => {
          setOpen((o) => !o);
          setSearch("");
        }}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 text-[12px] text-[#0d0d0d] font-mono text-left transition-colors"
        style={{
          background: "#f8f6f1",
          border: `1px solid ${open ? "#1f63ea" : "#d9d4c7"}`,
        }}
        onMouseEnter={(ev) => {
          if (open) return;
          ev.currentTarget.style.background = "#ffffff";
          ev.currentTarget.style.borderColor = "#6a665c";
        }}
        onMouseLeave={(ev) => {
          if (open) return;
          ev.currentTarget.style.background = "#f8f6f1";
          ev.currentTarget.style.borderColor = "#d9d4c7";
        }}
      >
        <span className="flex-1 truncate">
          {selected ? (
            <>
              <span style={{ fontWeight: 600 }}>{selected.symbol}</span>
              {selected.name && (
                <span style={{ color: "#9a9488" }}> · {selected.name}</span>
              )}
            </>
          ) : (
            <span style={{ color: "#9a9488" }}>{placeholder}</span>
          )}
        </span>
        <span className="text-[10px]" style={{ color: "#9a9488" }}>
          ▾
        </span>
      </button>

      {open && (
        <div
          className="absolute z-50 mt-1 left-0"
          style={{
            background: "#ffffff",
            border: "1px solid #1f63ea",
            boxShadow: "0 12px 32px rgba(13,13,13,0.12)",
            minWidth: "100%",
            width: 380,
          }}
        >
          <div className="p-1.5" style={{ borderBottom: "1px solid #d9d4c7" }}>
            <input
              ref={inputRef}
              type="text"
              placeholder="Type to filter — symbol or token name…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  e.preventDefault();
                  setOpen(false);
                }
                if (e.key === "Enter" && filtered.length === 1) {
                  e.preventDefault();
                  onChange(filtered[0].symbol);
                  setOpen(false);
                  setSearch("");
                }
              }}
              className="w-full bg-[#f8f6f1] border border-[#d9d4c7] px-2.5 py-1.5 text-[12px] text-[#0d0d0d] font-mono focus:outline-none focus:border-[#0d0d0d] focus:bg-[#ffffff] placeholder:text-[#9a9488] rounded-none caret-[#1f63ea]"
            />
          </div>
          <div className="overflow-y-auto" style={{ maxHeight: 320 }}>
            {filtered.length === 0 && (
              <div className="text-[11px] text-center py-3 font-mono" style={{ color: "#9a9488" }}>
                No matching assets
              </div>
            )}
            {filtered.slice(0, 200).map((o) => {
              const isSel = value === o.symbol;
              return (
                <button
                  key={o.symbol}
                  type="button"
                  onClick={() => {
                    onChange(o.symbol);
                    setOpen(false);
                    setSearch("");
                  }}
                  className="w-full text-left px-3 py-1.5 text-[12px] font-mono transition-colors"
                  style={{
                    background: isSel ? "#ece7dd" : "transparent",
                    borderLeft: `2px solid ${isSel ? "#1f63ea" : "transparent"}`,
                  }}
                  onMouseEnter={(ev) => {
                    if (!isSel) ev.currentTarget.style.background = "#ece7dd";
                  }}
                  onMouseLeave={(ev) => {
                    if (!isSel) ev.currentTarget.style.background = "transparent";
                  }}
                >
                  <span style={{ color: "#0d0d0d", fontWeight: 600 }}>{o.symbol}</span>
                  {o.name && (
                    <div className="text-[9px] mt-0.5 tracking-[0.16em] uppercase" style={{ color: "#6a665c" }}>
                      {o.name}
                    </div>
                  )}
                </button>
              );
            })}
            {filtered.length > 200 && (
              <div className="text-[10px] text-center py-2 font-mono" style={{ color: "#9a9488" }}>
                Showing first 200 of {filtered.length} — refine your search
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

// Searchable account-name combobox. Caller picks the list to pass based on
// the currently-chosen Account Venue (Exchange / Wallet / Broker — each one
// is a separate MySQL table).
const AccountPicker = ({ value, onChange, options, placeholder = "— select account —" }) => {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const wrapRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (!wrapRef.current?.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  const selected = options.find((o) => o.name === value);
  const q = search.trim().toLowerCase();
  const filtered = q
    ? options.filter(
        (o) =>
          o.name.toLowerCase().includes(q) ||
          (o.venue && o.venue.toLowerCase().includes(q)) ||
          (o.portfolio && o.portfolio.toLowerCase().includes(q))
      )
    : options;

  return (
    <div ref={wrapRef} className="relative w-full">
      <button
        type="button"
        onClick={() => {
          setOpen((o) => !o);
          setSearch("");
        }}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 text-[12px] text-[#0d0d0d] font-mono text-left transition-colors"
        style={{
          background: "#f8f6f1",
          border: `1px solid ${open ? "#1f63ea" : "#d9d4c7"}`,
        }}
        onMouseEnter={(ev) => {
          if (open) return;
          ev.currentTarget.style.background = "#ffffff";
          ev.currentTarget.style.borderColor = "#6a665c";
        }}
        onMouseLeave={(ev) => {
          if (open) return;
          ev.currentTarget.style.background = "#f8f6f1";
          ev.currentTarget.style.borderColor = "#d9d4c7";
        }}
      >
        <span className="flex-1 truncate">
          {selected ? (
            <span>{selected.name}</span>
          ) : (
            <span style={{ color: "#9a9488" }}>{placeholder}</span>
          )}
        </span>
        <span className="text-[10px]" style={{ color: "#9a9488" }}>▾</span>
      </button>

      {open && (
        <div
          className="absolute z-50 mt-1 left-0"
          style={{
            background: "#ffffff",
            border: "1px solid #1f63ea",
            boxShadow: "0 12px 32px rgba(13,13,13,0.12)",
            minWidth: "100%",
            width: 480,
          }}
        >
          <div className="p-1.5" style={{ borderBottom: "1px solid #d9d4c7" }}>
            <input
              ref={inputRef}
              type="text"
              placeholder="Type to filter — name, venue, portfolio…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  e.preventDefault();
                  setOpen(false);
                }
                if (e.key === "Enter" && filtered.length === 1) {
                  e.preventDefault();
                  onChange(filtered[0].name);
                  setOpen(false);
                  setSearch("");
                }
              }}
              className="w-full bg-[#f8f6f1] border border-[#d9d4c7] px-2.5 py-1.5 text-[12px] text-[#0d0d0d] font-mono focus:outline-none focus:border-[#0d0d0d] focus:bg-[#ffffff] placeholder:text-[#9a9488] rounded-none caret-[#1f63ea]"
            />
          </div>
          <div className="overflow-y-auto" style={{ maxHeight: 320 }}>
            {options.length === 0 && (
              <div className="text-[11px] text-center py-3 font-mono" style={{ color: "#9a9488" }}>
                Pick an Account Type first
              </div>
            )}
            {options.length > 0 && filtered.length === 0 && (
              <div className="text-[11px] text-center py-3 font-mono" style={{ color: "#9a9488" }}>
                No matching accounts
              </div>
            )}
            {filtered.map((o) => {
              const isSel = value === o.name;
              return (
                <button
                  key={o.name}
                  type="button"
                  onClick={() => {
                    onChange(o.name);
                    setOpen(false);
                    setSearch("");
                  }}
                  className="w-full text-left px-3 py-1.5 text-[12px] font-mono transition-colors"
                  style={{
                    background: isSel ? "#ece7dd" : "transparent",
                    borderLeft: `2px solid ${isSel ? "#1f63ea" : "transparent"}`,
                  }}
                  onMouseEnter={(ev) => {
                    if (!isSel) ev.currentTarget.style.background = "#ece7dd";
                  }}
                  onMouseLeave={(ev) => {
                    if (!isSel) ev.currentTarget.style.background = "transparent";
                  }}
                >
                  <span style={{ color: "#0d0d0d", fontWeight: 500 }}>{o.name}</span>
                  <div className="text-[9px] mt-0.5 tracking-[0.16em] uppercase" style={{ color: "#6a665c" }}>
                    {o.venue || "—"}
                    {o.portfolio ? <span style={{ color: "#9a9488" }}> · {o.portfolio}</span> : null}
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};

// ─────────────────────────────────────────────────────────────
// Left navigation sidebar — mirrors the nxgen-mo dashboard's
// pattern: bone bg, hair right border, small mono-cap group
// headers, lucide icons next to labels, 2px ink left bar on
// active. See dashboard/src/App.jsx renderTabRow for the source.
// ─────────────────────────────────────────────────────────────
const SIDEBAR_CATEGORIES = [
  { key: "SPOT", label: "Spot" },
  { key: "FUTURE", label: "Futures", comingSoon: true },
  { key: "CASHFLOW", label: "Cashflow" },
  { key: "LOAN", label: "Loan" },
];

const NavTabRow = ({ label, active, onClick, align = "left", indent = false }) => (
  <button
    type="button"
    onClick={onClick}
    className={`w-full flex items-center ${
      indent ? "pl-10" : "pl-5"
    } pr-5 py-2 text-[13px] transition-colors border-l-2 ${
      active
        ? "bg-[#f8f6f1] text-[#0d0d0d] font-medium border-l-[#0d0d0d]"
        : "text-[#3a3834] border-l-transparent hover:bg-[#f8f6f1] hover:text-[#0d0d0d]"
    }`}
  >
    <span
      className={`truncate flex-1 ${align === "right" ? "text-right" : "text-left"}`}
    >
      {label}
    </span>
  </button>
);

const NavGroupLabel = ({ children, className = "" }) => (
  <div
    className={`px-5 pb-2 text-[9px] tracking-[0.24em] uppercase text-[#6a665c] font-mono ${className}`}
  >
    {children}
  </div>
);

// Renders identically to NavTabRow (text-[13px], normal case) but with a
// trailing chevron to indicate expand/collapse. Use for parent items that
// have child rows underneath.
const NavGroupToggle = ({ label, open, onClick, hasActive }) => (
  <button
    type="button"
    onClick={onClick}
    className={`w-full flex items-center pl-5 pr-5 py-2 text-[13px] transition-colors border-l-2 border-l-transparent ${
      hasActive
        ? "text-[#0d0d0d] font-medium"
        : "text-[#3a3834] hover:bg-[#f8f6f1] hover:text-[#0d0d0d]"
    }`}
    title={open ? "Collapse" : "Expand"}
  >
    <span className="truncate flex-1 text-left">{label}</span>
    {open ? (
      <ChevronDown size={12} style={{ color: hasActive ? "#0d0d0d" : "#6a665c" }} />
    ) : (
      <ChevronRight size={12} style={{ color: hasActive ? "#0d0d0d" : "#6a665c" }} />
    )}
  </button>
);

const PlaceholderView = ({ title, subtitle }) => (
  <div className="flex items-center justify-center px-8 py-32 min-h-[60vh]">
    <div className="text-center max-w-md">
      <div
        className="text-[10px] tracking-[0.32em] uppercase font-mono mb-4"
        style={{ color: BB.orange }}
      >
        ◆ Coming Soon
      </div>
      <div
        className="text-[28px] font-mono mb-3"
        style={{ color: BB.text, letterSpacing: "-0.01em", fontWeight: 600 }}
      >
        {title}
      </div>
      <div className="text-[12px] font-mono leading-relaxed" style={{ color: BB.dim }}>
        {subtitle}
      </div>
    </div>
  </div>
);

function SubmitFeedback({ feedback, onDismiss }) {
  if (!feedback) return null;
  const palette = {
    error:   { bg: "#fff0eb", text: "#7a1f00", border: "#e08a6a" },
    success: { bg: "#eef5e9", text: "#1f4a1f", border: "#7ea66a" },
  }[feedback.kind] || { bg: "#fff7e0", text: "#5a4400", border: "#d6b656" };
  return (
    <div
      className="px-3 py-2 mb-2 text-[12px]"
      style={{
        background: palette.bg,
        color: palette.text,
        border: `1px solid ${palette.border}`,
        fontFamily: "'IBM Plex Mono', ui-monospace, monospace",
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <span>{feedback.message}</span>
        <button
          type="button"
          onClick={onDismiss}
          className="opacity-60 hover:opacity-100"
        >×</button>
      </div>
      {feedback.detail && (
        <details className="mt-1 opacity-80">
          <summary className="cursor-pointer">detail</summary>
          <pre className="whitespace-pre-wrap text-[11px] mt-1">{feedback.detail}</pre>
        </details>
      )}
    </div>
  );
}

function ConflictModal({ open, dealRef, message, onReload, onClose }) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(0,0,0,0.45)" }}
    >
      <div
        className="px-6 py-5 max-w-md w-full"
        style={{
          background: "#f6f3ec",
          border: "1px solid #d9d4c7",
          fontFamily: "'IBM Plex Mono', ui-monospace, monospace",
        }}
      >
        <div className="text-[13px] font-medium mb-2">Booking already amended</div>
        <div className="text-[12px] mb-4">
          {message || `${dealRef} was amended by another session while you were editing it.`}
        </div>
        <div className="flex gap-2 justify-end">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1 text-[12px]"
            style={{ border: "1px solid #aaa" }}
          >Cancel</button>
          <button
            type="button"
            onClick={onReload}
            className="px-3 py-1 text-[12px]"
            style={{ background: "#1f1f1f", color: "#f2efe8" }}
          >Reload latest</button>
        </div>
      </div>
    </div>
  );
}

function DealEnquiry({ onSelect, BB }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [lastFetchedAt, setLastFetchedAt] = useState(null);

  const fetchRecent = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch("http://localhost:5181/api/cashflow/recent?limit=20");
      const j = await r.json();
      if (!j.ok) throw new Error(j.error || "fetch failed");
      setRows(j.rows || []);
      setLastFetchedAt(new Date());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchRecent(); }, [fetchRecent]);

  return (
    <div className="px-5 pt-4 pb-8">
      <div className="flex items-baseline justify-between mb-3">
        <div>
          <div
            className="text-[11px] tracking-[0.25em] uppercase opacity-60"
            style={{ fontFamily: "'IBM Plex Mono', ui-monospace, monospace" }}
          >Deal Enquiry</div>
          <div
            className="text-[22px] mt-1"
            style={{ fontFamily: "'Cormorant Garamond', 'EB Garamond', Georgia, serif" }}
          >Recent Cashflow Bookings</div>
        </div>
        <button
          type="button"
          onClick={fetchRecent}
          disabled={loading}
          className="px-3 py-1 text-[12px]"
          style={{
            background: BB?.surface || "#f6f3ec",
            border: `1px solid ${BB?.border || "#d9d4c7"}`,
            color: BB?.text || "#1f1f1f",
            opacity: loading ? 0.5 : 1,
          }}
        >{loading ? "Loading…" : "↻ Refresh"}{lastFetchedAt ? ` · ${lastFetchedAt.toLocaleTimeString()}` : ""}</button>
      </div>

      {error && (
        <div
          className="px-3 py-2 mb-3 text-[12px]"
          style={{ background: "#fff0eb", border: "1px solid #e08a6a", color: "#7a1f00" }}
        >Error: {error}</div>
      )}

      <div
        style={{
          background: BB?.surface || "#f6f3ec",
          border: `1px solid ${BB?.border || "#d9d4c7"}`,
        }}
      >
        <table className="w-full text-[12px]" style={{ fontFamily: "'IBM Plex Mono', ui-monospace, monospace" }}>
          <thead>
            <tr style={{ background: "rgba(0,0,0,0.04)", color: BB?.mute || "#666" }}>
              <th className="px-3 py-2 text-left">Deal Ref</th>
              <th className="px-3 py-2 text-left">Trade Date</th>
              <th className="px-3 py-2 text-left">Portfolio</th>
              <th className="px-3 py-2 text-left">Counterparty</th>
              <th className="px-3 py-2 text-left">Cashflow Type</th>
              <th className="px-3 py-2 text-left">Dir</th>
              <th className="px-3 py-2 text-left">Asset</th>
              <th className="px-3 py-2 text-right">Amount</th>
              <th className="px-3 py-2 text-left">Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && !loading && (
              <tr><td colSpan={9} className="px-3 py-6 text-center opacity-60">No live cashflow bookings yet.</td></tr>
            )}
            {rows.map((r) => (
              <tr
                key={r.deal_ref}
                onClick={() => onSelect(r.deal_ref)}
                className="cursor-pointer"
                style={{ borderTop: `1px solid ${BB?.border || "#d9d4c7"}` }}
                onMouseEnter={(e) => e.currentTarget.style.background = "rgba(0,0,0,0.03)"}
                onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
              >
                <td className="px-3 py-2">{r.deal_ref}</td>
                <td className="px-3 py-2">{(r.trade_date || "").slice(0, 10)}</td>
                <td className="px-3 py-2">{r.portfolio_id}</td>
                <td className="px-3 py-2">{r.counterparty || "—"}</td>
                <td className="px-3 py-2">{r.cashflow_type}</td>
                <td className="px-3 py-2">{r.direction}</td>
                <td className="px-3 py-2">{r.asset}</td>
                <td className="px-3 py-2 text-right">{r.amount}</td>
                <td className="px-3 py-2">{r.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="text-[11px] mt-3 opacity-60" style={{ fontFamily: "'IBM Plex Mono', ui-monospace, monospace" }}>
        Click a row to load it into the booking form for amendment.
      </div>
    </div>
  );
}

// Running clock for header strip
function useClock() {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return now;
}

export default function TradeBookingForm() {
  const fileInputRef = useRef(null);
  const clock = useClock();

  // Fetch the live token list from server.js (refreshed hourly). On failure
  // we silently keep the bundled TOKENS seed so the form still works offline.
  // server.js is on a separate port (5181) — we try same-origin first (in
  // case it's proxied), then fall back to the explicit API URL.
  const [liveTokens, setLiveTokens] = useState(TOKENS);
  useEffect(() => {
    const urls = ["/tokens.json", "http://localhost:5181/tokens.json"];
    (async () => {
      for (const u of urls) {
        try {
          const r = await fetch(u, { cache: "no-cache" });
          if (!r.ok) continue;
          const j = await r.json();
          if (Array.isArray(j?.tokens) && j.tokens.length > 0) {
            setLiveTokens(j.tokens);
            return;
          }
        } catch {
          /* try next url */
        }
      }
    })();
  }, []);

  const initial = () => ({
    trade_id: genTradeId("SPOT"),
    external_trade_id: "",
    created_at: isoNow(),
    last_modified_at: isoNow(),
    created_by: SUPERADMIN_USERS[0],
    trade_date: nowUtc(),
    value_date: nowUtc(),
    // Portfolio is the source of truth — entity is derived from it
    // via PORTFOLIOS[].entity. Empty string means "not yet selected".
    portfolio: "",
    account_id: "",
    venue_type: "CEX",
    venue: "Binance",
    category: "SPOT",
    status: "PENDING",
    tx_id: "",
    notes: "",
    // SPOT
    spot_direction: "LONG",
    base_asset: "BTC",
    base_amount: "",
    quote_asset: "USDT",
    quote_amount: "",
    price: "",
    fee_asset: "USDT",
    fee_amount: "",
    account_venue_type: "EXCHANGE",
    account_name: "",
    counterparty: "",
    // FUTURE
    fut_side: "BUY",
    fut_contract_type: "PERP",
    fut_symbol: "",
    fut_base_asset: "BTC",
    fut_quote_asset: "USDT",
    fut_contract_size: "1",
    fut_quantity: "",
    fut_price: "",
    fut_leverage: "",
    fut_margin_mode: "CROSS",
    fut_expiry: "",
    fut_funding_rate: "",
    fut_fee: "",
    fut_fee_asset: "USDT",
    fut_pnl_realized: "",
    fut_is_closing: false,
    // CASHFLOW (absorbs old TRANSFER + EXPENSE + INCOME + OTHER)
    cf_direction: "PAY",
    cf_type: "",
    cf_mirror: false,
    cf_asset: "USDT",
    cf_amount: "",
    network: "",
    gas_fee: "",
    gas_asset: "ETH",
    tx_hash: "",
    loan_direction: "BORROW",
    loan_type: "TERM",
    loan_term_days: "",
    principal_asset: "USDT",
    interest_asset: "USDT",
    principal_amount: "",
    interest_rate: "",
    interest_type: "FIXED",
    floating_benchmark: "",
    collateral_asset: "",
    collateral_amount: "",
    is_hedged: false,
    hedged_asset: "BTC",
    hedged_qty: "",
    hedged_price: "",
    hedge_proceeds_asset: "USDT",
    hedge_proceeds_amount: "",
    attachments: [],
  });

  const [form, setForm] = useState(initial);
  const [submittedRecord, setSubmittedRecord] = useState(null);
  const [copied, setCopied] = useState(false);
  const [env, setEnv] = useState("PROD");
  const [view, setView] = useState("TRADE_INPUT");
  const [tradeInputOpen, setTradeInputOpen] = useState(true);
  // Per-category snapshot of shared fields. When you switch from SPOT to
  // LOAN, the current SPOT values for dates/portfolio/counterparty/status/etc.
  // are stashed here under "SPOT"; when you switch back to SPOT, they're
  // restored. This keeps each product form independent.
  const [categoryCache, setCategoryCache] = useState({});
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v, last_modified_at: isoNow() }));
  const setMany = (patch) => setForm((f) => ({ ...f, ...patch, last_modified_at: isoNow() }));

  // Fields that EVERY product form has but with its own value space — these
  // get snapshotted on category switch.
  const SHARED_KEYS = [
    "trade_id", "external_trade_id",
    "trade_date", "value_date",
    "portfolio", "status",
    "counterparty",
    "account_venue_type", "account_name", "account_id",
    "fee_asset", "fee_amount",
    "network", "tx_hash", "gas_fee", "gas_asset",
    "venue_type", "venue", "tx_id",
    "notes",
  ];

  const initialSharedForCategory = (cat) => ({
    trade_id: genTradeId(cat),
    external_trade_id: "",
    trade_date: nowUtc(),
    value_date: nowUtc(),
    portfolio: "",
    status: defaultStatusFor(cat),
    counterparty: "",
    account_venue_type: "EXCHANGE",
    account_name: "",
    account_id: "",
    fee_asset: "USDT",
    fee_amount: "",
    network: "",
    tx_hash: "",
    gas_fee: "",
    gas_asset: "ETH",
    venue_type: "CEX",
    venue: "Binance",
    tx_id: "",
    notes: "",
  });

  const switchCategory = (newCat) => {
    if (newCat === form.category) return;
    // 1. Snapshot the current category's shared fields.
    const snapshot = SHARED_KEYS.reduce((acc, k) => {
      acc[k] = form[k];
      return acc;
    }, {});
    setCategoryCache((c) => ({ ...c, [form.category]: snapshot }));
    // 2. Restore the new category's snapshot, or initialize fresh.
    const restored = categoryCache[newCat] || initialSharedForCategory(newCat);
    setForm((f) => ({
      ...f,
      ...restored,
      category: newCat,
      last_modified_at: isoNow(),
    }));
  };

  // SPOT auto-compute. Rule: base × price = quote.
  // Editing base or price recomputes quote. Editing quote recomputes price.
  const setSpotField = (field, value) => {
    setForm((f) => {
      const next = { ...f, [field]: value, last_modified_at: isoNow() };
      const b = parseFloat(next.base_amount);
      const q = parseFloat(next.quote_amount);
      const p = parseFloat(next.price);
      const fmt = (n) => (isFinite(n) ? parseFloat(n.toPrecision(12)).toString() : "");
      if (field === "base_amount" || field === "price") {
        if (isFinite(b) && isFinite(p)) next.quote_amount = fmt(b * p);
      } else if (field === "quote_amount") {
        if (isFinite(q) && isFinite(b) && b !== 0) next.price = fmt(q / b);
      }
      return next;
    });
  };

  // HEDGE auto-compute. Same shape as setSpotField:
  //   hedged_qty × hedged_price = hedge_proceeds_amount.
  // Editing qty or price recomputes amount. Editing amount recomputes price.
  const setHedgeField = (field, value) => {
    setForm((f) => {
      const next = { ...f, [field]: value, last_modified_at: isoNow() };
      const q = parseFloat(next.hedged_qty);
      const p = parseFloat(next.hedged_price);
      const a = parseFloat(next.hedge_proceeds_amount);
      const fmt = (n) => (isFinite(n) ? parseFloat(n.toPrecision(12)).toString() : "");
      if (field === "hedged_qty" || field === "hedged_price") {
        if (isFinite(q) && isFinite(p)) next.hedge_proceeds_amount = fmt(q * p);
      } else if (field === "hedge_proceeds_amount") {
        if (isFinite(a) && isFinite(q) && q !== 0) next.hedged_price = fmt(a / q);
      }
      return next;
    });
  };

  // LOAN date/term auto-compute. Rule: maturity − start = term (days).
  // Editing start or term recomputes maturity. Editing maturity recomputes term.
  // Field values are "YYYY-MM-DD" strings for dates and integer days for term;
  // trade_date/value_date are stored as "YYYY-MM-DDT00:00" to stay compatible
  // with the rest of the form's datetime format.
  const setLoanField = (field, value) => {
    setForm((f) => {
      const next = { ...f, [field]: value, last_modified_at: isoNow() };
      const startStr =
        field === "trade_date" ? value : (next.trade_date || "").slice(0, 10);
      const matStr =
        field === "value_date" ? value : (next.value_date || "").slice(0, 10);
      const termStr =
        field === "loan_term_days" ? value : next.loan_term_days;
      const parseDay = (s) => (s ? new Date(`${s}T00:00:00Z`) : null);
      const start = parseDay(startStr);
      const mat = parseDay(matStr);
      const term = parseInt(termStr, 10);
      const dayMs = 86400000;
      const fmtDate = (d) => d.toISOString().slice(0, 10);

      if (field === "trade_date" || field === "loan_term_days") {
        // Recompute maturity from (start + term)
        if (start && isFinite(term) && term >= 0) {
          const newMat = new Date(start.getTime() + term * dayMs);
          next.value_date = `${fmtDate(newMat)}T00:00`;
        }
        // Normalize trade_date into the YYYY-MM-DDT00:00 storage form
        if (field === "trade_date" && value) {
          next.trade_date = `${value}T00:00`;
        }
      } else if (field === "value_date") {
        // Recompute term from (maturity − start); clearing maturity = open term
        if (!value) {
          next.value_date = "";
          next.loan_term_days = "";
        } else {
          next.value_date = `${value}T00:00`;
          if (start && mat) {
            const diff = Math.round((mat - start) / dayMs);
            next.loan_term_days = diff >= 0 ? String(diff) : "";
          }
        }
      }
      return next;
    });
  };

  useEffect(() => {
    const list = VENUES[form.venue_type] || [];
    if (list.length && !list.includes(form.venue)) set("venue", list[0]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.venue_type]);

  const handleFiles = (fileList) => {
    const files = Array.from(fileList);
    const added = files.map((f) => ({
      name: f.name,
      size: f.size,
      mime: f.type || "application/octet-stream",
      status: "pending_upload",
      drive_file_id: null,
      drive_url: null,
      _file: f,
    }));
    setForm((f) => ({
      ...f,
      attachments: [...f.attachments, ...added],
      last_modified_at: isoNow(),
    }));
  };

  const removeAttachment = (idx) =>
    setForm((f) => ({
      ...f,
      attachments: f.attachments.filter((_, i) => i !== idx),
      last_modified_at: isoNow(),
    }));

  // Accounts available for the chosen portfolio + venue type. Empty if portfolio
  // not selected, so the picker doesn't show every account before context is set.
  const accountOptions = useMemo(() => {
    const portfolioName = PORTFOLIOS.find(
      (p) => String(p.number) === String(form.portfolio)
    )?.name;
    if (!portfolioName) return [];
    const pool =
      form.account_venue_type === "EXCHANGE"
        ? ACCOUNTS_EXCHANGE
        : form.account_venue_type === "WALLET"
        ? ACCOUNTS_WALLET
        : form.account_venue_type === "BROKER"
        ? ACCOUNTS_BROKER
        : [];
    return pool.filter((a) => a.portfolio === portfolioName);
  }, [form.portfolio, form.account_venue_type]);

  const outputRecord = useMemo(() => {
    // Resolve the portfolio entry (number → {name, entity}) so we can emit
    // both the portfolio number AND the derived entity into the record.
    const portfolioEntry = PORTFOLIOS.find(
      (p) => String(p.number) === String(form.portfolio)
    );

    // ─── CASHFLOW: flat, schema-aligned to trades_cashflow ──────────────
    // Every top-level key maps 1:1 to a column in the trades_cashflow
    // table (see trade-booking/docs/cashflow-schema-mapping.md). Backend
    // can build INSERT VALUES (...) without renaming. UI-only metadata
    // sits in `_meta` so the backend can strip it cleanly.
    if (form.category === "CASHFLOW") {
      // Directional sign convention: user types a positive magnitude
      // in the Notional Amount input; the stored value is negative
      // when direction=PAY and positive when direction=RECEIVE. Same
      // for fees (fees are always a cost → negated, but always positive
      // input; we leave fee_amount unsigned since fees are conventionally
      // recorded as outflows). Mirror-leg 2 negates the leg-1 amount
      // because leg 2's direction is flipped (see below).
      const cfMagnitude = Math.abs(parseFloat(form.cf_amount) || 0);
      const cfSignedAmount = form.cf_direction === "PAY" ? -cfMagnitude : cfMagnitude;
      // Key order mirrors trades_cashflow column order exactly. effective_*
      // are server-set on INSERT; emitted here as null placeholders so the
      // JSON shape lines up 1:1 with the table for backend mapping.
      const cfRecord = {
        deal_ref: form.trade_id,
        external_trade_id: form.external_trade_id || null,
        txn_type: "CASHFLOW",
        cashflow_type: form.cf_type || null,
        direction: form.cf_direction,
        entity: portfolioEntry ? portfolioEntry.entity : null,
        portfolio_id: portfolioEntry ? portfolioEntry.number : null,
        portfolio_name: portfolioEntry ? portfolioEntry.name : null,
        counterparty: form.counterparty || null,
        account: form.account_name || null,
        account_type: form.account_venue_type,
        asset: form.cf_asset,
        amount: cfSignedAmount,
        fee_asset: form.fee_asset,
        fee_amount: parseFloat(form.fee_amount) || 0,
        trade_date: form.trade_date,
        value_date: form.value_date,
        network: form.network || null,
        txid_reference: form.tx_hash || null,
        effective_start: null,
        effective_end: null,
        user_id: form.created_by || null,
        status: form.status,
        comment: form.notes || null,
        // Non-schema metadata
        _meta: {
          mirror: form.cf_type === "INTER PTF FUNDING" && form.cf_mirror,
          attachments: form.attachments.map(({ _file, ...rest }) => rest),
        },
      };

      // Mirror Trade → two flat records (leg 1 + offsetting leg 2).
      if (cfRecord._meta.mirror && cfRecord.counterparty) {
        const cpEntry = PORTFOLIOS.find(
          (p) => String(p.number) === String(form.counterparty)
        );
        const leg2 = {
          ...cfRecord,
          deal_ref: genTradeId("CASHFLOW"),
          entity: cpEntry ? cpEntry.entity : null,
          portfolio_id: cpEntry ? cpEntry.number : null,
          portfolio_name: cpEntry ? cpEntry.name : null,
          counterparty: portfolioEntry ? String(portfolioEntry.number) : null,
          account: null,
          account_type: null,
          direction: cfRecord.direction === "PAY" ? "RECEIVE" : "PAY",
          // Mirror leg flips sign with the direction: the two legs sum to zero.
          amount: -cfRecord.amount,
          _meta: { ...cfRecord._meta, mirror_leg: 2 },
        };
        return [
          { ...cfRecord, _meta: { ...cfRecord._meta, mirror_leg: 1 } },
          leg2,
        ];
      }
      return cfRecord;
    }

    // ─── SPOT / FUTURE / LOAN: legacy base+payload split ────────────────
    // Their target tables haven't been designed yet, so the JSON keeps a
    // form-driven shape until schemas are nailed down.
    const base = {
      trade_id: form.trade_id,
      external_trade_id: form.external_trade_id || null,
      created_at: form.created_at,
      last_modified_at: form.last_modified_at,
      trade_date: form.trade_date,
      value_date: form.value_date,
      created_by: form.created_by || null,
      portfolio: portfolioEntry
        ? {
            number: portfolioEntry.number,
            name: portfolioEntry.name,
          }
        : null,
      entity: portfolioEntry ? portfolioEntry.entity : null,
      category: form.category,
      status: form.status,
      notes: form.notes || null,
      attachments: form.attachments.map(({ _file, ...rest }) => rest),
    };

    let payload = {};
    if (form.category === "SPOT") {
      payload = {
        direction: form.spot_direction,
        base_asset: form.base_asset,
        base_amount: parseFloat(form.base_amount) || 0,
        quote_asset: form.quote_asset,
        quote_amount: parseFloat(form.quote_amount) || 0,
        price: parseFloat(form.price) || 0,
        fee_asset: form.fee_asset,
        fee_amount: parseFloat(form.fee_amount) || 0,
        account_venue_type: form.account_venue_type,
        account_name: form.account_name || null,
        tx_hash: form.tx_hash || null,
        counterparty: form.counterparty || null,
      };
    } else if (form.category === "FUTURE") {
      const qty = parseFloat(form.fut_quantity) || 0;
      const px = parseFloat(form.fut_price) || 0;
      const size = parseFloat(form.fut_contract_size) || 1;
      payload = {
        side: form.fut_side,
        contract_type: form.fut_contract_type,
        symbol: form.fut_symbol || null,
        base_asset: form.fut_base_asset,
        quote_asset: form.fut_quote_asset,
        contract_size: size,
        quantity: qty,
        price: px,
        notional: +(qty * px * size).toFixed(8),
        leverage: parseFloat(form.fut_leverage) || null,
        margin_mode: form.fut_margin_mode,
        expiry: form.fut_contract_type === "DATED" ? form.fut_expiry || null : null,
        funding_rate_pct:
          form.fut_contract_type === "PERP"
            ? parseFloat(form.fut_funding_rate) || null
            : null,
        fee: parseFloat(form.fut_fee) || 0,
        fee_asset: form.fut_fee_asset,
        is_closing: form.fut_is_closing,
        realized_pnl: form.fut_is_closing
          ? parseFloat(form.fut_pnl_realized) || 0
          : null,
        // tradeVenueFields — only FUTURE renders these in the UI.
        venue_type: form.venue_type,
        venue: form.venue,
        account_id: form.account_id || null,
        tx_id: form.tx_id || null,
        tx_hash: form.tx_hash || null,
        network: form.network || null,
        gas_fee: parseFloat(form.gas_fee) || null,
        gas_asset: form.network ? form.gas_asset : null,
      };
    } else if (form.category === "LOAN") {
      const hedgedQty = parseFloat(form.hedged_qty) || 0;
      const hedgedPx = parseFloat(form.hedged_price) || 0;
      payload = {
        direction: form.loan_direction,
        loan_type: form.loan_type,
        loan_term_days: parseInt(form.loan_term_days, 10) || null,
        counterparty: form.counterparty || null,
        account_venue_type: form.account_venue_type,
        account_name: form.account_name || null,
        principal_asset: form.principal_asset,
        principal_amount: parseFloat(form.principal_amount) || 0,
        interest_asset: form.interest_asset,
        interest_rate_pa_pct: parseFloat(form.interest_rate) || 0,
        interest_type: form.interest_type,
        floating_benchmark:
          form.interest_type === "FLOATING" ? form.floating_benchmark || null : null,
        collateral_asset: form.collateral_asset || null,
        collateral_amount: parseFloat(form.collateral_amount) || 0,
        hedge: form.is_hedged
          ? {
              hedged_asset: form.hedged_asset,
              hedged_qty: hedgedQty,
              hedged_price: hedgedPx,
              hedge_proceeds_asset: form.hedge_proceeds_asset,
              hedge_proceeds_amount: parseFloat(form.hedge_proceeds_amount) || 0,
            }
          : null,
      };
    }

    return { ...base, payload };
  }, [form]);

  const errors = useMemo(() => {
    const e = [];
    if (!form.created_by) e.push("Created by is required");
    if (!form.portfolio) e.push("Portfolio is required");
    if (form.category === "SPOT") {
      if (!form.base_amount || parseFloat(form.base_amount) <= 0)
        e.push("Base amount must be > 0");
      if (!form.quote_amount || parseFloat(form.quote_amount) <= 0)
        e.push("Quote amount must be > 0");
      if (!form.price || parseFloat(form.price) <= 0) e.push("Price must be > 0");
      if (form.base_asset === form.quote_asset) e.push("Base and quote assets must differ");
      if (!form.account_name) e.push("Account name is required");
    }
    if (form.category === "FUTURE") {
      if (!form.fut_symbol) e.push("Futures symbol required");
      if (!form.fut_quantity || parseFloat(form.fut_quantity) <= 0)
        e.push("Quantity must be > 0");
      if (!form.fut_price || parseFloat(form.fut_price) <= 0) e.push("Price must be > 0");
      if (form.fut_contract_type === "DATED" && !form.fut_expiry)
        e.push("Expiry date required for dated contract");
    }
    if (form.category === "CASHFLOW") {
      if (!form.cf_type) e.push("Cashflow type required");
      if (!form.counterparty) e.push("Counterparty is required");
      if (!form.cf_amount || parseFloat(form.cf_amount) <= 0)
        e.push("Notional amount must be > 0");
      if (!form.account_name) e.push("Account name is required");
    }
    if (form.category === "LOAN") {
      if (!form.counterparty) e.push("Counterparty required");
      if (!form.principal_amount || parseFloat(form.principal_amount) <= 0)
        e.push("Principal must be > 0");
      if (form.is_hedged) {
        if (!form.hedged_qty || parseFloat(form.hedged_qty) <= 0)
          e.push("Hedged qty must be > 0");
        if (!form.hedged_price || parseFloat(form.hedged_price) <= 0)
          e.push("Hedged price must be > 0");
      }
    }
    return e;
  }, [form]);

  const canSubmit = errors.length === 0;

  // Booking submission feedback. Cleared when the form is edited again
  // or after ~4s on success.
  const [feedback, setFeedback] = useState(null);
  // null | { dealRef: string, message: string }
  const [conflictModal, setConflictModal] = useState(null);
  // null | "MCF-42"  — when set, form is in amend mode (PUT vs POST)
  const [amendingDealRef, setAmendingDealRef] = useState(null);

  // Convert a backend cashflow row (mapping-doc shape) into the slice
  // of form state the cashflow tab consumes. Inverse of outputRecord
  // for category="CASHFLOW". Unknown fields are ignored.
  function payloadToFormState(row) {
    return {
      category: "CASHFLOW",
      trade_id: row.deal_ref,
      external_trade_id: row.external_trade_id || "",
      cf_type: row.cashflow_type,
      cf_direction: row.direction,
      portfolio: String(row.portfolio_id),
      counterparty: row.counterparty || "",
      account_name: row.account || "",
      account_venue_type: row.account_type || "",
      cf_asset: row.asset,
      // Form input is the positive magnitude; sign is derived from
      // direction at submit time (see outputRecord CASHFLOW branch).
      cf_amount: row.amount == null
        ? ""
        : String(Math.abs(parseFloat(row.amount))),
      fee_asset: row.fee_asset || "",
      fee_amount: row.fee_amount || "0",
      trade_date: row.trade_date,
      value_date: row.value_date,
      network: row.network || "",
      tx_hash: row.txid_reference || "",
      created_by: row.user_id,
      status: row.status,
      notes: row.comment || "",
    };
  }

  async function loadIntoForm(dealRef) {
    setFeedback(null);
    let res;
    try {
      res = await fetch(`http://localhost:5181/api/cashflow/${encodeURIComponent(dealRef)}`);
    } catch (e) {
      setFeedback({ kind: "error", message: "Server unreachable", detail: String(e) });
      return;
    }
    const result = await res.json().catch(() => ({ ok: false, error: "non-JSON server response" }));
    if (!result.ok) {
      setFeedback({ kind: "error", message: result.error || "Failed to load deal" });
      return;
    }
    const row = result.rows[0];
    // setMany is the existing bulk-patch helper (TradeBookingForm.jsx:1815);
    // it merges the patch and refreshes last_modified_at.
    setMany(payloadToFormState(row));
    setAmendingDealRef(row.deal_ref);
    setView("TRADE_INPUT");
  }

  const handleSubmit = async () => {
    if (form.category !== "CASHFLOW") {
      // SPOT/FUTURE/LOAN: not wired to backend yet — keep the existing
      // JSON preview behavior so those forms still work.
      if (!canSubmit) return;
      setSubmittedRecord(outputRecord);
      return;
    }
    if (!canSubmit) return;
    setFeedback(null);
    const endpoint = amendingDealRef
      ? "http://localhost:5181/api/cashflow/amend"
      : "http://localhost:5181/api/cashflow/insert";
    let res;
    try {
      res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(outputRecord),
      });
    } catch (e) {
      setFeedback({ kind: "error", message: "Server unreachable", detail: String(e) });
      return;
    }
    const result = await res.json().catch(() => ({ ok: false, error: "non-JSON server response" }));
    if (result.ok && result.rows && result.rows.length > 0) {
      setSubmittedRecord(result.rows.length === 1 ? result.rows[0] : result.rows);
      const verb = amendingDealRef ? "Updated" : "Booked";
      const ref = result.rows[0].deal_ref;
      setAmendingDealRef(null);
      setFeedback({ kind: "success", message: `${verb} ${ref}` });
      setTimeout(() => {
        setFeedback((f) => (f && f.kind === "success" ? null : f));
      }, 4000);
    } else if (res.status === 409) {
      setConflictModal({ dealRef: amendingDealRef, message: result.error });
    } else {
      setFeedback({ kind: "error", message: result.error || "Booking failed", detail: result.detail });
    }
  };

  // Reset is scoped to the currently-active product form. Clicking Reset on
  // the LOAN form only clears loan-specific fields (+ the per-trade economics
  // helpers that loan uses); SPOT/FUTURE/CASHFLOW state stays put, as do the
  // shared summary fields (trade_id, dates, portfolio, counterparty, status,
  // notes, attachments).
  const RESET_SLICES = {
    SPOT: {
      spot_direction: "LONG",
      base_asset: "BTC",
      base_amount: "",
      quote_asset: "USDT",
      quote_amount: "",
      price: "",
      fee_asset: "USDT",
      fee_amount: "",
      account_venue_type: "EXCHANGE",
      account_name: "",
      account_id: "",
      tx_id: "",
      tx_hash: "",
      network: "",
      gas_fee: "",
      gas_asset: "ETH",
      venue_type: "CEX",
      venue: "Binance",
    },
    FUTURE: {
      fut_side: "BUY",
      fut_contract_type: "PERP",
      fut_symbol: "",
      fut_base_asset: "BTC",
      fut_quote_asset: "USDT",
      fut_contract_size: "1",
      fut_quantity: "",
      fut_price: "",
      fut_leverage: "",
      fut_margin_mode: "CROSS",
      fut_expiry: "",
      fut_funding_rate: "",
      fut_fee: "",
      fut_fee_asset: "USDT",
      fut_pnl_realized: "",
      fut_is_closing: false,
    },
    CASHFLOW: {
      cf_direction: "PAY",
      cf_type: "",
      cf_mirror: false,
      cf_asset: "USDT",
      cf_amount: "",
      fee_asset: "USDT",
      fee_amount: "",
      account_venue_type: "EXCHANGE",
      account_name: "",
      network: "",
      tx_hash: "",
    },
    LOAN: {
      loan_direction: "BORROW",
      loan_type: "TERM",
      loan_term_days: "",
      principal_asset: "USDT",
      interest_asset: "USDT",
      principal_amount: "",
      interest_rate: "",
      interest_type: "FIXED",
      floating_benchmark: "",
      collateral_asset: "",
      collateral_amount: "",
      is_hedged: false,
      hedged_asset: "BTC",
      hedged_qty: "",
      hedged_price: "",
      hedge_proceeds_asset: "USDT",
      hedge_proceeds_amount: "",
      account_venue_type: "EXCHANGE",
      account_name: "",
    },
  };

  const handleReset = () => {
    // Hard-refresh equivalent — scoped to the active product. Resets BOTH the
    // category-specific economics (RESET_SLICES) AND the shared identity
    // fields (initialSharedForCategory). Attachments + submitted record
    // also wipe since the user is starting a new trade for this product.
    // Other categories' state (in form + categoryCache) stays untouched.
    const cat = form.category;
    const slice = RESET_SLICES[cat];
    if (!slice) return;
    setForm((prev) => ({
      ...prev,
      ...initialSharedForCategory(cat),
      ...slice,
      attachments: [],
      last_modified_at: isoNow(),
    }));
    setCategoryCache((c) => {
      const next = { ...c };
      delete next[cat];
      return next;
    });
    setSubmittedRecord(null);
  };

  const copyJson = async () => {
    await navigator.clipboard.writeText(JSON.stringify(outputRecord, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const venueList = VENUES[form.venue_type] || [];

  // Shared venue/account/tx block — rendered at the TOP of every category's
  // Trade Details section. Kept as JSX in a variable so we can include it from
  // each conditional Section without duplicating the markup.
  const tradeVenueFields = (
    <>
      <Field label="Venue Type" span={3}>
        <Select value={form.venue_type} onChange={(e) => set("venue_type", e.target.value)}>
          {VENUE_TYPES.map((x) => (
            <option key={x}>{x}</option>
          ))}
        </Select>
      </Field>
      <Field label="Venue" span={3}>
        <Select value={form.venue} onChange={(e) => set("venue", e.target.value)}>
          {venueList.map((x) => (
            <option key={x}>{x}</option>
          ))}
        </Select>
      </Field>
      <Field label="Account ID" span={3}>
        <Input
          placeholder="sub-account / wallet"
          value={form.account_id}
          onChange={(e) => set("account_id", e.target.value)}
        />
      </Field>
      <Field label="Tx ID / Order ID" span={3}>
        <Input
          placeholder="0x… / exchange order id"
          value={form.tx_id}
          onChange={(e) => set("tx_id", e.target.value)}
        />
      </Field>
      <Field label="Tx Hash (if on-chain)" span={12}>
        <Input
          placeholder="0x… (optional)"
          value={form.tx_hash}
          onChange={(e) => set("tx_hash", e.target.value)}
        />
      </Field>
      {(form.category === "CASHFLOW" ||
        form.venue_type === "OnChain" ||
        form.venue_type === "DEX") && (
        <>
          <div
            className="col-span-12 mt-1.5 text-[10px] uppercase tracking-[0.24em] font-mono pb-0.5"
            style={{ color: BB.dim, borderBottom: `1px dashed ${BB.border}` }}
          >
            ◇ On-chain (optional)
          </div>
          <Field label="Network" span={4}>
            <Select value={form.network} onChange={(e) => set("network", e.target.value)}>
              <option value="">— off-chain / book entry —</option>
              {NETWORKS.map((x) => (
                <option key={x}>{x}</option>
              ))}
            </Select>
          </Field>
          <Field label="Gas Fee" span={4}>
            <NumberInput
              value={form.gas_fee}
              onChange={(v) => set("gas_fee", v)}
            />
          </Field>
          <Field label="Gas Asset" span={4}>
            <AssetPicker value={form.gas_asset} onChange={(v) => set("gas_asset", v)} />
          </Field>
        </>
      )}
      {/* Divider between venue/tx fields and the category-specific economics */}
      <div
        className="col-span-12 mt-2 mb-1 text-[10px] uppercase tracking-[0.24em] font-mono pb-0.5"
        style={{ color: BB.dim, borderBottom: `1px dashed ${BB.border}` }}
      >
        ◇ {form.category} economics
      </div>
    </>
  );

  // Syntax-highlighted JSON renderer (Bloomberg-style colored tokens)
  const renderJsonHighlighted = (obj) => {
    const json = JSON.stringify(obj, null, 2);
    const escaped = json
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
    const html = escaped.replace(
      /("(\\u[\dA-Fa-f]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g,
      (m) => {
        let color = BB.yellow; // numbers
        if (/^"/.test(m)) color = /:$/.test(m) ? BB.orange : BB.green;
        else if (/true|false/.test(m)) color = BB.cyan;
        else if (/null/.test(m)) color = BB.faint;
        return `<span style="color:${color}">${m}</span>`;
      }
    );
    return { __html: html };
  };

  return (
    <TokensContext.Provider value={liveTokens}>
    <div
      className="h-screen flex flex-col overflow-hidden"
      style={{
        background: BB.bg,
        color: BB.text,
        fontFamily: "'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace",
      }}
    >
      {/* ════ BANNER — one clean black strip ════ */}
      <header
        className="flex items-center justify-between px-6 py-3 mb-4"
        style={{
          background: "#0d0d0d",
        }}
      >
        {/* LEFT — logo + system name as one vertical lockup */}
        <div className="flex flex-col items-start gap-1.5">
          <img
            src={tokkaLogo}
            alt="Tokka Labs"
            className="block"
            style={{ height: 32, width: "auto", objectFit: "contain" }}
          />
          <span
            className="text-[9px] tracking-[0.24em] uppercase font-mono"
            style={{ color: "#9a9488", fontWeight: 400, paddingLeft: 1 }}
          >
            Trade Management System
          </span>
        </div>

        {/* RIGHT — env toggle (stacked: label on top, indicator + value below) + UTC date/time */}
        <div className="flex items-center gap-5 text-[10px] tracking-[0.22em] uppercase font-mono">
          {/* ENV toggle — vertical: ENV label on top, ● PROD below */}
          <button
            type="button"
            onClick={() => setEnv((e) => (e === "PROD" ? "UAT" : "PROD"))}
            className="flex flex-col items-start gap-0.5 transition-opacity hover:opacity-80 leading-none"
            title="Click to switch environment"
          >
            <span style={{ color: "#6a665c" }}>ENV</span>
            <span className="flex items-center gap-1.5">
              <span
                aria-hidden
                className="inline-block"
                style={{
                  width: 7,
                  height: 7,
                  background: env === "PROD" ? BB.green : "#1f63ea",
                  boxShadow: `0 0 6px ${env === "PROD" ? BB.green : "#1f63ea"}`,
                }}
              />
              <span
                style={{
                  color: env === "PROD" ? "#6ee7b7" : "#bfdbfe",
                  fontWeight: 600,
                  letterSpacing: "0.18em",
                }}
              >
                {env}
              </span>
            </span>
          </button>

          <span aria-hidden className="h-4 w-px" style={{ background: "#3a3834" }} />

          {/* UTC date · time */}
          <div className="flex items-baseline gap-2">
            <span
              className="tabular-nums"
              style={{ color: "#ece7dd", letterSpacing: "0.1em" }}
            >
              {clock.toISOString().slice(0, 10)}
              <span style={{ color: "#6a665c" }} className="mx-2">·</span>
              {clock.toISOString().slice(11, 19)}
            </span>
            <span style={{ color: "#6a665c" }}>UTC</span>
          </div>
        </div>
      </header>

      {/* ════ BODY — left sidebar + main panel ════ */}
      <div className="flex flex-1 min-h-0">
        {/* ─── SIDEBAR ─── */}
        <aside
          className="shrink-0 flex flex-col"
          style={{
            width: 208,
            borderRight: `1px solid ${BB.border}`,
            background: BB.bg,
          }}
        >
          <div className="flex-1 overflow-y-auto py-4">
            {/* Trade Input — collapsible group */}
            <NavGroupToggle
              label="Trade Input"
              open={tradeInputOpen}
              onClick={() => setTradeInputOpen((o) => !o)}
              hasActive={view === "TRADE_INPUT"}
            />
            {tradeInputOpen && (
              <div>
                {SIDEBAR_CATEGORIES.map((c) => (
                  <NavTabRow
                    key={c.key}
                    label={
                      c.comingSoon ? (
                        <span className="inline-flex items-center gap-2">
                          {c.label}
                          <span
                            className="text-[8px] tracking-[0.2em] uppercase font-mono px-1.5 py-0.5"
                            style={{
                              color: BB.faint,
                              border: `1px solid ${BB.border}`,
                              background: BB.surface2,
                            }}
                          >
                            soon
                          </span>
                        </span>
                      ) : (
                        c.label
                      )
                    }
                    indent
                    active={view === "TRADE_INPUT" && form.category === c.key}
                    onClick={() => {
                      setView("TRADE_INPUT");
                      switchCategory(c.key);
                    }}
                  />
                ))}
              </div>
            )}

            {/* Separator between Trade Input group and standalone items */}
            <div
              className="mx-5 my-3"
              style={{ borderTop: `1px dashed #d9d4c7` }}
            />

            <NavTabRow
              label="Deal Enquiry"
              active={view === "DEAL_ENQUIRY"}
              onClick={() => setView("DEAL_ENQUIRY")}
            />
            <NavTabRow
              label="Pending Bookings"
              active={view === "PENDING_BOOKINGS"}
              onClick={() => setView("PENDING_BOOKINGS")}
            />
          </div>

          {/* ─── User profile footer (clock lives in the top banner) ─── */}
          {(() => {
            const profile = USER_PROFILES[form.created_by] || {
              name: form.created_by,
              role: "User",
            };
            const initial = (profile.name || "?").charAt(0).toUpperCase();
            return (
              <div
                className="px-5 py-4"
                style={{ borderTop: `1px solid ${BB.border}` }}
              >
                <div className="flex items-center gap-3">
                  <div
                    aria-hidden
                    className="w-9 h-9 flex items-center justify-center text-[15px] font-medium leading-none shrink-0"
                    style={{
                      background: BB.text,
                      color: "#f2efe8",
                      fontFamily:
                        "'Cormorant Garamond', 'EB Garamond', Georgia, serif",
                    }}
                  >
                    {initial}
                  </div>
                  <div className="min-w-0">
                    <div
                      className="text-[12px] font-medium leading-tight truncate"
                      style={{ color: BB.text }}
                    >
                      {profile.name}
                    </div>
                    <div
                      className="text-[9px] tracking-[0.2em] uppercase font-mono leading-tight mt-1"
                      style={{ color: BB.mute }}
                    >
                      {profile.role}
                    </div>
                  </div>
                </div>
              </div>
            );
          })()}
        </aside>

        {/* ─── MAIN PANEL ─── */}
        <main className="flex-1 min-w-0 pb-8 overflow-y-auto">
          {view === "DEAL_ENQUIRY" && (
            <DealEnquiry
              BB={BB}
              onSelect={(dealRef) => loadIntoForm(dealRef)}
            />
          )}
          {view === "PENDING_BOOKINGS" && (
            <PlaceholderView
              title="Pending Bookings"
              subtitle="Bookings awaiting approval, attached documentation, or settlement confirmation. Approve, reject, or amend from here. Coming soon."
            />
          )}
          {view === "TRADE_INPUT" && form.category === "FUTURE" && (
            <PlaceholderView
              title="Futures Booking"
              subtitle="Manual futures booking (perpetual + dated) ships in the next milestone. The schema, validation, and Output Record payload for FUTURE are already wired — only the form rendering is paused. Pick Spot, Cashflow, or Loan to keep working."
            />
          )}
          {view === "TRADE_INPUT" && form.category !== "FUTURE" && (
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 px-5 pt-4">
        {/* ═══════════ LEFT — form ═══════════ */}
        <div
          className="lg:col-span-2 p-4"
          style={{
            background: BB.surface,
            border: `1px solid ${BB.border}`,
          }}
        >
          {/* ═════ 1. SUMMARY (category-specific title) ═════ */}
          <Section
            title={
              form.category === "SPOT"
                ? "Spot Summary"
                : form.category === "FUTURE"
                ? "Future Summary"
                : form.category === "CASHFLOW"
                ? "Cashflow Summary"
                : form.category === "LOAN"
                ? "Loan Summary"
                : "Trade Summary"
            }
            accent={BB.amber}
          >
            <Field label="Internal Trade Id" span={6}>
              <Input
                value={form.trade_id}
                readOnly
                title="System-generated, immutable"
                style={{
                  background: "#ece7dd",
                  color: BB.dim,
                  cursor: "not-allowed",
                }}
              />
            </Field>
            <Field label="External Trade Id (optional)" span={6}>
              <Input
                placeholder="exchange order id / counterparty ref / 0x…"
                value={form.external_trade_id}
                onChange={(e) => set("external_trade_id", e.target.value)}
              />
            </Field>
            {form.category === "LOAN" ? (
              <>
                <Field label="Start Date" required span={3}>
                  <Input
                    type="date"
                    value={(form.trade_date || "").slice(0, 10)}
                    onChange={(e) => setLoanField("trade_date", e.target.value)}
                  />
                </Field>
                <Field
                  label="Maturity Date"
                  span={3}
                  hint={
                    form.value_date ? (
                      <button
                        type="button"
                        onClick={() => setLoanField("value_date", "")}
                        className="hover:underline cursor-pointer"
                        style={{
                          color: BB.orange,
                          background: "transparent",
                          border: "none",
                          padding: 0,
                          font: "inherit",
                        }}
                        title="Clear maturity → open-term loan"
                      >
                        × clear
                      </button>
                    ) : null
                  }
                >
                  <Input
                    type="date"
                    value={(form.value_date || "").slice(0, 10)}
                    onChange={(e) => setLoanField("value_date", e.target.value)}
                  />
                </Field>
                <Field label="Terms (Days)" span={2}>
                  {/* When both Maturity and Terms are blank the loan is open-term;
                      we surface "OPEN" as a strong visual indicator (text type so
                      the styled string renders) but typing a number flips back to
                      a numeric input and re-engages the auto-compute. */}
                  {!form.value_date && !form.loan_term_days ? (
                    <Input
                      type="text"
                      value="OPEN"
                      onChange={(e) => {
                        const v = e.target.value.replace(/[^\d]/g, "");
                        setLoanField("loan_term_days", v);
                      }}
                      style={{
                        color: BB.orange,
                        fontWeight: 600,
                        background: "#ece7dd",
                      }}
                      title="Open-term loan — type a number to set a fixed term"
                    />
                  ) : (
                    <NumberInput
                      placeholder="days"
                      value={form.loan_term_days}
                      onChange={(v) => setLoanField("loan_term_days", v)}
                    />
                  )}
                </Field>
              </>
            ) : (
              <>
                <Field label="Trade Date · UTC" required span={4}>
                  <DateTimePicker24
                    value={form.trade_date}
                    onChange={(v) => set("trade_date", v)}
                    syncLabel="Sync → Value Date"
                    onSync={(v) => set("value_date", v)}
                  />
                </Field>
                <Field label="Value Date · UTC" required span={4}>
                  <DateTimePicker24
                    value={form.value_date}
                    onChange={(v) => set("value_date", v)}
                    syncLabel="Sync → Trade Date"
                    onSync={(v) => set("trade_date", v)}
                  />
                </Field>
              </>
            )}
            <Field label="Created by" required span={4}>
              <Select
                value={form.created_by}
                onChange={(e) => set("created_by", e.target.value)}
              >
                {SUPERADMIN_USERS.map((u) => (
                  <option key={u}>{u}</option>
                ))}
              </Select>
            </Field>
            <Field label="Portfolio" required span={6}>
              <PortfolioPicker
                value={form.portfolio}
                onChange={(v) => setMany({ portfolio: v, account_name: "" })}
                options={PORTFOLIOS}
              />
            </Field>
            <Field label="Entity (auto from portfolio)" span={6}>
              <Input
                value={
                  PORTFOLIOS.find(
                    (p) => String(p.number) === String(form.portfolio)
                  )?.entity || ""
                }
                readOnly
                placeholder="—"
                title="Derived from the selected portfolio"
                style={{
                  background: "#ece7dd",
                  color: BB.dim,
                  cursor: "not-allowed",
                }}
              />
            </Field>
            <Field
              label="Counterparty"
              required={form.category === "LOAN"}
              span={6}
            >
              {form.category === "CASHFLOW" && form.cf_type === "INTER PTF FUNDING" ? (
                <PortfolioPicker
                  value={form.counterparty}
                  onChange={(v) => set("counterparty", String(v))}
                  options={PORTFOLIOS.filter(
                    (p) => String(p.number) !== String(form.portfolio)
                  )}
                />
              ) : (
                <CounterpartyPicker
                  value={form.counterparty}
                  onChange={(v) => set("counterparty", v)}
                  options={
                    form.category === "LOAN"
                      ? COUNTERPARTIES.filter((c) => c.subType === "LENDER")
                      : COUNTERPARTIES
                  }
                />
              )}
            </Field>
            <Field label="Status" required span={6}>
              <Select
                value={form.status}
                onChange={(e) => set("status", e.target.value)}
              >
                {statusOptionsFor(form.category).map((x) => (
                  <option key={x}>{x}</option>
                ))}
              </Select>
            </Field>
          </Section>

          {form.category === "SPOT" && (
            <Section title="Spot Details" kicker="Spot · OTC / CEX / DEX" accent={BB.green}>
              {/* Direction */}
              <Field label="Direction" required span={12}>
                <div className="flex gap-2">
                  {["LONG", "SHORT"].map((d) => {
                    const active = form.spot_direction === d;
                    const tone = d === "LONG" ? BB.green : BB.red;
                    return (
                      <button
                        key={d}
                        type="button"
                        onClick={() => set("spot_direction", d)}
                        className="px-4 py-1.5 text-[11px] tracking-[0.2em] uppercase font-mono transition-colors"
                        style={{
                          background: BB.surface2,
                          color: active ? tone : BB.dim,
                          border: `1px solid ${active ? tone : BB.border}`,
                          boxShadow: active ? `inset 0 0 0 1px ${tone}` : "none",
                          fontWeight: active ? 600 : 500,
                        }}
                      >
                        {d}
                      </button>
                    );
                  })}
                </div>
              </Field>

              {/* Base / Quote */}
              <Field label="Base Asset" required span={3}>
                <AssetPicker value={form.base_asset} onChange={(v) => set("base_asset", v)} />
              </Field>
              <Field label="Base Amount" required span={3}>
                <NumberInput
                  value={form.base_amount}
                  onChange={(v) => setSpotField("base_amount", v)}
                />
              </Field>
              <Field label="Quote Asset" required span={3}>
                <AssetPicker value={form.quote_asset} onChange={(v) => set("quote_asset", v)} />
              </Field>
              <Field label="Quote Amount" required span={3}>
                <NumberInput
                  value={form.quote_amount}
                  onChange={(v) => setSpotField("quote_amount", v)}
                />
              </Field>

              {/* Price */}
              <Field label="Price" required span={4}>
                <NumberInput
                  value={form.price}
                  onChange={(v) => setSpotField("price", v)}
                />
              </Field>

              {/* Fee */}
              <Field label="Fee Asset" span={4}>
                <AssetPicker value={form.fee_asset} onChange={(v) => set("fee_asset", v)} />
              </Field>
              <Field label="Fee Amount" span={4}>
                <NumberInput value={form.fee_amount} onChange={(v) => set("fee_amount", v)} />
              </Field>

              {/* Account venue + name — venue picks which table (exchange/wallet/broker),
                  name pulls from that table */}
              <Field label="Account Type" required span={4}>
                <Select
                  value={form.account_venue_type}
                  onChange={(e) =>
                    // Clear account_name when switching tables so a stale value
                    // from another venue type doesn't linger.
                    setMany({ account_venue_type: e.target.value, account_name: "" })
                  }
                >
                  {ACCOUNT_VENUE_TYPES.map((v) => (
                    <option key={v.key} value={v.key}>
                      {v.label}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Account Name" required span={8}>
                <AccountPicker
                  value={form.account_name}
                  onChange={(v) => set("account_name", v)}
                  options={accountOptions}
                  placeholder={
                    !form.portfolio
                      ? "— select portfolio first —"
                      : accountOptions.length === 0
                      ? "— no accounts for this portfolio + venue —"
                      : "— select account —"
                  }
                />
              </Field>

              {/* Tx hash (optional) */}
              <Field label="Tx Hash (optional)" span={12}>
                <Input
                  placeholder="0x… (on-chain hash, if applicable)"
                  value={form.tx_hash}
                  onChange={(e) => set("tx_hash", e.target.value)}
                />
              </Field>
            </Section>
          )}

          {form.category === "FUTURE" && (
            <Section title="Future Details" kicker="Futures · Perpetual or Dated" accent={BB.cyan}>
              {tradeVenueFields}
              <Field label="Side" required span={3}>
                <Select
                  value={form.fut_side}
                  onChange={(e) => set("fut_side", e.target.value)}
                  style={{ color: form.fut_side === "BUY" ? BB.green : BB.red }}
                >
                  <option>BUY</option>
                  <option>SELL</option>
                </Select>
              </Field>
              <Field label="Contract Type" required span={3}>
                <Select
                  value={form.fut_contract_type}
                  onChange={(e) => set("fut_contract_type", e.target.value)}
                >
                  {FUTURE_CONTRACT_TYPES.map((x) => (
                    <option key={x}>{x}</option>
                  ))}
                </Select>
              </Field>
              <Field label="Symbol / Contract" required span={6}>
                <Input
                  placeholder={
                    form.fut_contract_type === "PERP" ? "e.g. BTC-PERP" : "e.g. BTC-USD-260626"
                  }
                  value={form.fut_symbol}
                  onChange={(e) => set("fut_symbol", e.target.value)}
                />
              </Field>
              <Field label="Base Asset" required span={3}>
                <AssetPicker
                  value={form.fut_base_asset}
                  onChange={(v) => set("fut_base_asset", v)}
                />
              </Field>
              <Field label="Quote / Settle" required span={3}>
                <AssetPicker
                  value={form.fut_quote_asset}
                  onChange={(v) => set("fut_quote_asset", v)}
                />
              </Field>
              <Field label="Contract Size" span={3}>
                <NumberInput
                  placeholder="multiplier (e.g. 1)"
                  value={form.fut_contract_size}
                  onChange={(v) => set("fut_contract_size", v)}
                />
              </Field>
              <Field label="Margin Mode" span={3}>
                <Select
                  value={form.fut_margin_mode}
                  onChange={(e) => set("fut_margin_mode", e.target.value)}
                >
                  {FUTURE_MARGIN_MODES.map((x) => (
                    <option key={x}>{x}</option>
                  ))}
                </Select>
              </Field>
              <Field label="Quantity (contracts)" required span={4}>
                <NumberInput
                  value={form.fut_quantity}
                  onChange={(v) => set("fut_quantity", v)}
                />
              </Field>
              <Field label="Price" required span={4}>
                <NumberInput
                  value={form.fut_price}
                  onChange={(v) => set("fut_price", v)}
                />
              </Field>
              <Field label="Notional (auto)" span={4}>
                <Input
                  readOnly
                  value={
                    form.fut_quantity && form.fut_price
                      ? (
                          parseFloat(form.fut_quantity) *
                          parseFloat(form.fut_price) *
                          (parseFloat(form.fut_contract_size) || 1)
                        ).toLocaleString(undefined, { maximumFractionDigits: 8 })
                      : ""
                  }
                  style={{ color: BB.cyan, background: "#ece7dd" }}
                />
              </Field>
              <Field label="Leverage (x)" span={3}>
                <NumberInput
                  placeholder="e.g. 5"
                  value={form.fut_leverage}
                  onChange={(v) => set("fut_leverage", v)}
                />
              </Field>
              {form.fut_contract_type === "DATED" ? (
                <Field label="Expiry" required span={3}>
                  <Input
                    type="date"
                    value={form.fut_expiry}
                    onChange={(e) => set("fut_expiry", e.target.value)}
                  />
                </Field>
              ) : (
                <Field label="Funding Rate %" span={3}>
                  <NumberInput
                    placeholder="snapshot, e.g. 0.01"
                    value={form.fut_funding_rate}
                    onChange={(v) => set("fut_funding_rate", v)}
                  />
                </Field>
              )}
              <Field label="Fee" span={3}>
                <NumberInput
                  value={form.fut_fee}
                  onChange={(v) => set("fut_fee", v)}
                />
              </Field>
              <Field label="Fee Asset" span={3}>
                <AssetPicker
                  value={form.fut_fee_asset}
                  onChange={(v) => set("fut_fee_asset", v)}
                />
              </Field>
              <div className="col-span-12 flex items-center gap-2 mt-1">
                <input
                  type="checkbox"
                  id="fut_is_closing"
                  checked={form.fut_is_closing}
                  onChange={(e) => set("fut_is_closing", e.target.checked)}
                  style={{ accentColor: BB.orange }}
                />
                <label
                  htmlFor="fut_is_closing"
                  className="text-[11px] cursor-pointer font-mono"
                  style={{ color: BB.text }}
                >
                  This is a closing entry (record realized PnL)
                </label>
              </div>
              {form.fut_is_closing && (
                <Field label="Realized PnL" span={6}>
                  <NumberInput
                    placeholder="positive = profit, negative = loss"
                    value={form.fut_pnl_realized}
                    onChange={(v) => set("fut_pnl_realized", v)}
                  />
                </Field>
              )}
            </Section>
          )}

          {form.category === "CASHFLOW" && (
            <Section
              title="Cashflow Details"
              kicker="Cashflow · transfer / expense / income / funding / fee"
              accent={form.cf_direction === "RECEIVE" ? BB.green : BB.red}
            >
              {/* Direction — RECEIVE / PAY toggle */}
              <Field label="Direction" required span={12}>
                <div className="flex gap-2">
                  {CASHFLOW_DIRECTIONS.map((d) => {
                    const active = form.cf_direction === d;
                    const tone = d === "RECEIVE" ? BB.green : BB.red;
                    return (
                      <button
                        key={d}
                        type="button"
                        onClick={() => set("cf_direction", d)}
                        className="px-4 py-1.5 text-[11px] tracking-[0.2em] uppercase font-mono transition-colors"
                        style={{
                          background: BB.surface2,
                          color: active ? tone : BB.dim,
                          border: `1px solid ${active ? tone : BB.border}`,
                          boxShadow: active ? `inset 0 0 0 1px ${tone}` : "none",
                          fontWeight: active ? 600 : 500,
                        }}
                      >
                        {d}
                      </button>
                    );
                  })}
                </div>
              </Field>

              <Field label="Cashflow Type" required span={4}>
                <Select
                  value={form.cf_type}
                  onChange={(e) => {
                    // Counterparty semantics change between INTER PTF FUNDING
                    // (portfolio number) and other types (counterparty name).
                    // Also reset the mirror flag when leaving INTER PTF FUNDING.
                    const nextType = e.target.value;
                    const wasIPF = form.cf_type === "INTER PTF FUNDING";
                    const nowIPF = nextType === "INTER PTF FUNDING";
                    if (wasIPF !== nowIPF) {
                      setMany({
                        cf_type: nextType,
                        counterparty: "",
                        cf_mirror: false,
                      });
                    } else {
                      set("cf_type", nextType);
                    }
                  }}
                >
                  <option value="">— select —</option>
                  {CASHFLOW_TYPES.map((x) => (
                    <option key={x}>{x}</option>
                  ))}
                </Select>
              </Field>
              {/* Mirror checkbox sits in the same row as Cashflow Type when
                  INTER PTF FUNDING is selected; otherwise the row spacer just
                  fills the remaining 8 cols. Checking Mirror flags that an
                  offsetting leg should be auto-booked on the counterparty
                  portfolio — no extra portfolio picker needed. */}
              {form.cf_type === "INTER PTF FUNDING" ? (
                <div
                  className="col-span-8 flex items-end pb-1.5 pl-3"
                  style={{ minHeight: 0 }}
                >
                  <label className="text-[11px] cursor-pointer flex items-center gap-2 font-mono" style={{ color: BB.text }}>
                    <input
                      type="checkbox"
                      checked={form.cf_mirror}
                      onChange={(e) => set("cf_mirror", e.target.checked)}
                      style={{ accentColor: BB.orange }}
                    />
                    Mirror Trade
                  </label>
                </div>
              ) : (
                <div className="col-span-8" />
              )}

              <Field label="Notional Asset" required span={3}>
                <AssetPicker value={form.cf_asset} onChange={(v) => set("cf_asset", v)} />
              </Field>
              <Field label="Notional Amount" required span={3}>
                <NumberInput value={form.cf_amount} onChange={(v) => set("cf_amount", v)} />
              </Field>
              <Field label="Fee Asset" span={3}>
                <AssetPicker value={form.fee_asset} onChange={(v) => set("fee_asset", v)} />
              </Field>
              <Field label="Fee Amount" span={3}>
                <NumberInput value={form.fee_amount} onChange={(v) => set("fee_amount", v)} />
              </Field>

              <Field label="Account Type" required span={4}>
                <Select
                  value={form.account_venue_type}
                  onChange={(e) =>
                    setMany({ account_venue_type: e.target.value, account_name: "" })
                  }
                >
                  {ACCOUNT_VENUE_TYPES.map((v) => (
                    <option key={v.key} value={v.key}>
                      {v.label}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Account Name" required span={8}>
                <AccountPicker
                  value={form.account_name}
                  onChange={(v) => set("account_name", v)}
                  options={accountOptions}
                  placeholder={
                    !form.portfolio
                      ? "— select portfolio first —"
                      : accountOptions.length === 0
                      ? "— no accounts for this portfolio + venue —"
                      : "— select account —"
                  }
                />
              </Field>

              <Field label="Network" span={4}>
                <Select value={form.network} onChange={(e) => set("network", e.target.value)}>
                  <option value="">— off-chain —</option>
                  {NETWORKS.map((x) => (
                    <option key={x}>{x}</option>
                  ))}
                </Select>
              </Field>
              <Field label="Tx Hash (optional)" span={8}>
                <Input
                  placeholder="0x… (on-chain hash, if applicable)"
                  value={form.tx_hash}
                  onChange={(e) => set("tx_hash", e.target.value)}
                />
              </Field>
            </Section>
          )}

          {form.category === "LOAN" && (
            <>
              <Section title="Loan Details" kicker="Loan · principal · rate · maturity" accent={BB.magenta}>
                {/* Direction — full-row toggle (matches CASHFLOW / SPOT / FUTURE) */}
                <Field label="Direction" required span={12}>
                  <div className="flex gap-2">
                    {["BORROW", "LEND"].map((d) => {
                      const active = form.loan_direction === d;
                      const tone = d === "BORROW" ? BB.red : BB.green;
                      return (
                        <button
                          key={d}
                          type="button"
                          onClick={() => set("loan_direction", d)}
                          className="px-4 py-1.5 text-[11px] tracking-[0.2em] uppercase font-mono transition-colors"
                          style={{
                            background: BB.surface2,
                            color: active ? tone : BB.dim,
                            border: `1px solid ${active ? tone : BB.border}`,
                            boxShadow: active ? `inset 0 0 0 1px ${tone}` : "none",
                            fontWeight: active ? 600 : 500,
                          }}
                        >
                          {d}
                        </button>
                      );
                    })}
                  </div>
                </Field>

                {/* Loan Type + spacer (matches cashflow's "Cashflow Type" row) */}
                <Field label="Loan Type" required span={4}>
                  <Select
                    value={form.loan_type}
                    onChange={(e) => set("loan_type", e.target.value)}
                  >
                    {LOAN_TYPES.map((x) => (
                      <option key={x}>{x}</option>
                    ))}
                  </Select>
                </Field>
                <div className="col-span-8" />

                {/* Economics — Principal + Interest (analog to cashflow's notional+fee row) */}
                <Field label="Principal Asset" required span={3}>
                  <AssetPicker
                    value={form.principal_asset}
                    onChange={(v) =>
                      setForm((f) => {
                        const next = {
                          ...f,
                          principal_asset: v,
                          last_modified_at: isoNow(),
                        };
                        // Interest Asset (and Hedged Asset, which mirrors it)
                        // auto-follow Principal until the user diverges them.
                        if (f.interest_asset === f.principal_asset) {
                          next.interest_asset = v;
                          next.hedged_asset = v;
                        }
                        return next;
                      })
                    }
                  />
                </Field>
                <Field label="Principal Amount" required span={3}>
                  <NumberInput
                    value={form.principal_amount}
                    onChange={(v) => set("principal_amount", v)}
                  />
                </Field>
                <Field label="Interest Asset" required span={3}>
                  <AssetPicker
                    value={form.interest_asset}
                    onChange={(v) =>
                      setMany({ interest_asset: v, hedged_asset: v })
                    }
                  />
                </Field>
                <Field label="Interest Rate P.A (%)" span={3}>
                  <NumberInput
                    placeholder="e.g. 8.5"
                    value={form.interest_rate}
                    onChange={(v) => set("interest_rate", v)}
                  />
                </Field>
                <Field label="Interest Type" span={4}>
                  <Select
                    value={form.interest_type}
                    onChange={(e) => set("interest_type", e.target.value)}
                  >
                    <option>FIXED</option>
                    <option>FLOATING</option>
                  </Select>
                </Field>
                {form.interest_type === "FLOATING" ? (
                  <Field label="Floating Benchmark" span={8}>
                    <Input
                      placeholder="e.g. SOFR + 200bps, Aave borrow rate"
                      value={form.floating_benchmark}
                      onChange={(e) => set("floating_benchmark", e.target.value)}
                    />
                  </Field>
                ) : (
                  <div className="col-span-8" />
                )}

                {/* Account (matches cashflow) */}
                <Field label="Account Type" required span={4}>
                  <Select
                    value={form.account_venue_type}
                    onChange={(e) =>
                      setMany({ account_venue_type: e.target.value, account_name: "" })
                    }
                  >
                    {ACCOUNT_VENUE_TYPES.map((v) => (
                      <option key={v.key} value={v.key}>
                        {v.label}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Account Name" required span={8}>
                  <AccountPicker
                    value={form.account_name}
                    onChange={(v) => set("account_name", v)}
                    options={accountOptions}
                    placeholder={
                      !form.portfolio
                        ? "— select portfolio first —"
                        : accountOptions.length === 0
                        ? "— no accounts for this portfolio + account type —"
                        : "— select account —"
                    }
                  />
                </Field>

                {/* Collateral — loan-specific extras at the bottom */}
                <Field label="Collateral Asset" span={6}>
                  <AssetPicker
                    value={form.collateral_asset}
                    onChange={(v) => set("collateral_asset", v)}
                    placeholder="— unsecured —"
                  />
                </Field>
                <Field label="Collateral Amount" span={6}>
                  <NumberInput
                    value={form.collateral_amount}
                    onChange={(v) => set("collateral_amount", v)}
                  />
                </Field>
              </Section>

              <Section
                title="Hedge Link"
                kicker="Optional · ties to a booked SPOT"
                accent={BB.cyan}
              >
                <div className="col-span-12 flex items-center gap-2 mb-1">
                  <input
                    type="checkbox"
                    id="is_hedged"
                    checked={form.is_hedged}
                    onChange={(e) => set("is_hedged", e.target.checked)}
                    style={{ accentColor: BB.orange }}
                  />
                  <label
                    htmlFor="is_hedged"
                    className="text-[11px] cursor-pointer flex items-center gap-1.5 font-mono"
                    style={{ color: BB.text }}
                  >
                    <Link2 size={11} style={{ color: BB.cyan }} />
                    This loan is hedged with a spot trade
                  </label>
                </div>
                {form.is_hedged && (
                  <>
                    <Field label="Hedged Asset" span={4}>
                      <AssetPicker
                        value={form.hedged_asset}
                        onChange={(v) => set("hedged_asset", v)}
                      />
                    </Field>
                    <Field label="Hedged Qty" required span={4}>
                      <NumberInput
                        value={form.hedged_qty}
                        onChange={(v) => setHedgeField("hedged_qty", v)}
                      />
                    </Field>
                    <Field label="Hedged Price" required span={4}>
                      <NumberInput
                        value={form.hedged_price}
                        onChange={(v) => setHedgeField("hedged_price", v)}
                      />
                    </Field>
                    <Field label="Hedge Proceeds Asset" required span={4}>
                      <AssetPicker
                        value={form.hedge_proceeds_asset}
                        onChange={(v) => set("hedge_proceeds_asset", v)}
                      />
                    </Field>
                    <Field label="Hedge Proceeds Amount" required span={8}>
                      <NumberInput
                        value={form.hedge_proceeds_amount}
                        onChange={(v) => setHedgeField("hedge_proceeds_amount", v)}
                      />
                    </Field>
                  </>
                )}
              </Section>
            </>
          )}

          {/* ═════ 3. COMMENTS & ATTACHMENTS ═════ */}
          <Section
            title="Comments & Attachments"
            kicker={
              form.category === "LOAN"
                ? "Term sheet · supporting docs · free-form notes"
                : "Supporting docs · free-form notes"
            }
            accent={BB.dim}
          >
            <Field label="Free-form notes / comments" span={12}>
              <Textarea
                rows={3}
                placeholder="context, caveats, follow-ups, related ticket numbers…"
                value={form.notes}
                onChange={(e) => set("notes", e.target.value)}
              />
            </Field>
            <div className="col-span-12">
              <div
                onClick={() => fileInputRef.current?.click()}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  handleFiles(e.dataTransfer.files);
                }}
                className="p-6 text-center cursor-pointer transition-colors"
                style={{
                  border: `1px dashed ${BB.border}`,
                  background: BB.surface2,
                }}
                onMouseEnter={(ev) => {
                  ev.currentTarget.style.borderColor = BB.orange;
                  ev.currentTarget.style.background = "#dbeafe";
                }}
                onMouseLeave={(ev) => {
                  ev.currentTarget.style.borderColor = BB.border;
                  ev.currentTarget.style.background = BB.surface2;
                }}
              >
                <Upload size={18} className="mx-auto mb-1.5" style={{ color: BB.orange }} />
                <div className="text-[12px] font-mono" style={{ color: BB.text }}>
                  Drop term sheet / agreement / invoice — or{" "}
                  <span style={{ color: BB.orange, textDecoration: "underline" }}>
                    click to browse
                  </span>
                </div>
                <div className="text-[10px] mt-1 font-mono" style={{ color: BB.mute }}>
                  PDF · DOCX · IMG &nbsp;»&nbsp; uploaded to Drive on submit
                </div>
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  className="hidden"
                  onChange={(e) => handleFiles(e.target.files)}
                />
              </div>
              {form.attachments.length > 0 && (
                <div className="mt-2.5 space-y-1">
                  {form.attachments.map((a, i) => (
                    <div
                      key={i}
                      className="flex items-center gap-2 px-2.5 py-1.5 text-[11px] font-mono"
                      style={{
                        background: BB.surface2,
                        border: `1px solid ${BB.border}`,
                      }}
                    >
                      <Paperclip size={11} style={{ color: BB.orange }} className="shrink-0" />
                      <div className="flex-1 truncate">
                        <span style={{ color: BB.text }}>{a.name}</span>
                        <span className="ml-2" style={{ color: BB.mute }}>
                          {fmtSize(a.size)}
                        </span>
                      </div>
                      <span
                        className="text-[9px] uppercase tracking-[0.2em]"
                        style={{ color: BB.amber }}
                      >
                        {a.status}
                      </span>
                      <button
                        onClick={() => removeAttachment(i)}
                        style={{ color: BB.mute }}
                        className="hover:!text-[#b91c1c]"
                        aria-label="Remove attachment"
                      >
                        <X size={11} />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </Section>

          {errors.length > 0 && (
            <div
              className="mb-3 p-2.5"
              style={{
                border: `1px solid #fecaca`,
                background: "#fef2f2",
              }}
            >
              <div
                className="flex items-center gap-2 text-[10px] uppercase tracking-[0.22em] font-mono mb-1.5"
                style={{ color: BB.red }}
              >
                <AlertCircle size={12} />
                <span>Validation · {errors.length} issue{errors.length > 1 ? "s" : ""}</span>
              </div>
              <ul className="text-[11px] space-y-0.5 font-mono" style={{ color: "#7f1d1d" }}>
                {errors.map((e, i) => (
                  <li key={i}>· {e}</li>
                ))}
              </ul>
            </div>
          )}

          {/* ════ COMMAND BAR ════ */}
              <SubmitFeedback feedback={feedback} onDismiss={() => setFeedback(null)} />
          <div className="flex gap-2 pt-1">
            <button
              onClick={handleSubmit}
              disabled={!canSubmit}
              className="flex-1 py-3 text-[12px] font-semibold uppercase tracking-[0.28em] transition-colors font-mono"
              style={{
                background: canSubmit ? BB.orange : BB.surface2,
                color: canSubmit ? "#ffffff" : BB.faint,
                border: `1px solid ${canSubmit ? BB.orange : BB.border}`,
                cursor: canSubmit ? "pointer" : "not-allowed",
                letterSpacing: "0.28em",
              }}
              onMouseEnter={(ev) => {
                if (canSubmit) ev.currentTarget.style.background = BB.amber;
              }}
              onMouseLeave={(ev) => {
                if (canSubmit) ev.currentTarget.style.background = BB.orange;
              }}
            >
              {amendingDealRef ? `Update ${amendingDealRef}` : (
                form.category === "CASHFLOW" ? "Book Cashflow" : "Generate Output"
              )}
            </button>
            {amendingDealRef && (
              <button
                type="button"
                onClick={() => {
                  setAmendingDealRef(null);
                  setFeedback(null);
                }}
                className="mt-2 text-[11px] opacity-70 hover:opacity-100 underline"
              >× cancel amend</button>
            )}
            <button
              onClick={handleReset}
              className="px-5 text-[11px] uppercase tracking-[0.24em] transition-colors flex items-center gap-2 font-mono"
              style={{
                background: BB.surface2,
                color: BB.dim,
                border: `1px solid ${BB.border}`,
              }}
              onMouseEnter={(ev) => {
                ev.currentTarget.style.borderColor = BB.red;
                ev.currentTarget.style.color = BB.red;
              }}
              onMouseLeave={(ev) => {
                ev.currentTarget.style.borderColor = BB.border;
                ev.currentTarget.style.color = BB.dim;
              }}
            >
              <RotateCcw size={12} /> Reset
            </button>
          </div>
        </div>

        {/* ═══════════ RIGHT — terminal record preview ═══════════ */}
        <div className="lg:col-span-1">
          <div className="sticky top-4">
            <div
              className="flex items-center justify-between px-2.5 py-1.5 text-[10px] tracking-[0.22em] uppercase font-mono"
              style={{
                background: "#0d0d0d",
                border: `1px solid ${BB.border}`,
                borderBottom: "none",
                color: BB.orange,
              }}
            >
              <span>◆ RECORD &nbsp;»&nbsp; LIVE JSON</span>
              <button
                onClick={copyJson}
                className="flex items-center gap-1 transition-colors"
                style={{ color: copied ? BB.green : BB.dim }}
                onMouseEnter={(ev) => {
                  if (!copied) ev.currentTarget.style.color = BB.orange;
                }}
                onMouseLeave={(ev) => {
                  if (!copied) ev.currentTarget.style.color = BB.dim;
                }}
              >
                {copied ? (
                  <>
                    <Check size={11} /> Copied
                  </>
                ) : (
                  <>
                    <Copy size={11} /> Copy
                  </>
                )}
              </button>
            </div>
            <pre
              className="p-3 text-[11px] overflow-auto max-h-[60vh] leading-relaxed font-mono"
              style={{
                background: BB.surface,
                border: `1px solid ${BB.border}`,
                color: BB.text,
              }}
              dangerouslySetInnerHTML={renderJsonHighlighted(outputRecord)}
            />

            {submittedRecord && (
              <div
                className="mt-3 p-2.5"
                style={{
                  border: `1px solid #a7f3d0`,
                  background: "#ecfdf5",
                }}
              >
                <div
                  className="text-[10px] uppercase tracking-[0.22em] font-mono mb-1"
                  style={{ color: BB.green }}
                >
                  ▮ Booked (preview)
                </div>
                <div className="text-[11px] font-mono break-all" style={{ color: "#065f46" }}>
                  {submittedRecord.deal_ref || submittedRecord.trade_id}
                  {submittedRecord.attachments?.length > 0 && (
                    <>
                      <br />
                      {submittedRecord.attachments.length} file(s) queued for Drive upload
                    </>
                  )}
                </div>
              </div>
            )}

            <div
              className="mt-3 text-[10px] leading-relaxed font-mono p-2.5"
              style={{
                background: BB.surface,
                border: `1px solid ${BB.border}`,
                color: BB.mute,
              }}
            >
              <div
                className="uppercase tracking-[0.22em] mb-1.5"
                style={{ color: BB.amber }}
              >
                ◆ Backend wire-up
              </div>
              On submit → POST multipart FormData to{" "}
              <span style={{ color: BB.cyan }}>/api/bookings</span>. Drive service-account uploads
              each file to a folder per <span style={{ color: BB.cyan }}>trade_id</span>; writes
              back <span style={{ color: BB.cyan }}>drive_file_id</span> &amp;{" "}
              <span style={{ color: BB.cyan }}>drive_url</span>; persists record to Postgres JSONB.
            </div>

            {/* Status footer */}
            <div
              className="mt-3 px-2.5 py-1 text-[9px] uppercase tracking-[0.24em] font-mono flex items-center justify-between"
              style={{
                background: "#0d0d0d",
                border: `1px solid ${BB.border}`,
                color: BB.faint,
              }}
            >
              <span>
                MOD <span style={{ color: BB.dim }}>{new Date(form.last_modified_at).toLocaleTimeString()}</span>
              </span>
              <span>
                ATT <span style={{ color: BB.cyan }}>{form.attachments.length}</span>
              </span>
              <span>
                CAT <span style={{ color: BB.orange }}>{form.category}</span>
              </span>
            </div>
          </div>
        </div>
      </div>
          )}
        </main>
            <ConflictModal
              open={Boolean(conflictModal)}
              dealRef={conflictModal?.dealRef}
              message={conflictModal?.message}
              onClose={() => setConflictModal(null)}
              onReload={async () => {
                if (!conflictModal?.dealRef) return setConflictModal(null);
                await loadIntoForm(conflictModal.dealRef);
                setConflictModal(null);
              }}
            />
      </div>
    </div>
    </TokensContext.Provider>
  );
}
