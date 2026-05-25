import React, { useState, useMemo, useEffect, useLayoutEffect, useCallback, useRef, useContext, createContext } from "react";
import { createPortal } from "react-dom";
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
  Calendar,
  History,
  Loader2,
} from "lucide-react";
import tokkaLogo from "./assets/tokka-labs-logo.png";
import { NETWORKS } from "./data/networks.js";
import { TOKENS, ASSET_SYMBOLS } from "./data/tokens.js";
import { useAuth } from "./auth/AuthContext.jsx";
import { api } from "./auth/api.js";
import UserAdmin from "./admin/UserAdmin.jsx";
import ApiTokens from "./settings/ApiTokens.jsx";

// Live token list — initialized from the bundled snapshot, replaced after
// fetch('/tokens.json') resolves (refreshed hourly by server.js). AssetPicker
// reads this context so the 12 call sites don't need any prop changes.
const TokensContext = createContext(TOKENS);

// ═════════════════════════════════════════════════════════════
// Module-scope refdata holders. Initialized empty, populated at
// runtime by fetchRefdataOnce() (called on mount + on the refresh
// button click). Mutable on purpose: many helper functions outside
// the React component read these as plain JS lookups. The root
// component bumps `refdataTick` after each load to force a re-render
// so pickers see the new lists.
//
// Refresh in browser     : "↻ Refresh refdata" button in the header
// Refresh on the server  : POST /api/refdata/refresh   (t2x-ro-mysql → JSON)
// Auto-refresh           : hourly HH:15 UTC tick in server.js
// ═════════════════════════════════════════════════════════════
let PORTFOLIOS = [];
let COUNTERPARTIES = [];
let COUNTERPARTY_IDS = {};
let SUPERADMIN_USERS = [];
let USER_PROFILES = {};
let ACCOUNTS_EXCHANGE = [];
let ACCOUNTS_WALLET = [];
let ACCOUNTS_BROKER = [];

// Static UI labels for the Account Type select. The data behind each
// key (EXCHANGE/WALLET/BROKER) is fetched at runtime — see fetchRefdataOnce.
const ACCOUNT_VENUE_TYPES = [
  { key: "EXCHANGE", label: "Exchange" },
  { key: "WALLET", label: "Wallet" },
  { key: "BROKER", label: "Brokerage" },
];

async function fetchRefdataOnce() {
  // Same-origin fetch: Vite proxies in dev, ingress routes in UAT/prod.
  const fetchJson = async (path) => {
    try {
      const r = await fetch(path, { cache: "no-cache" });
      if (!r.ok) return null;
      return await r.json();
    } catch { return null; }
  };

  const [counterparties, portfolios, users, accounts] = await Promise.all([
    fetchJson("/refdata/counterparties.json"),
    fetchJson("/refdata/portfolios.json"),
    fetchJson("/refdata/users.json"),
    fetchJson("/refdata/accounts.json"),
  ]);

  if (Array.isArray(counterparties)) {
    COUNTERPARTIES = counterparties;
    COUNTERPARTY_IDS = Object.fromEntries(counterparties.map((c) => [c.name, c.id]));
  }
  if (Array.isArray(portfolios)) {
    // Form expects {number, name, entity}. The synced JSON carries
    // those plus a few extras; we just pass it through (extra fields
    // are harmless to downstream consumers).
    PORTFOLIOS = portfolios;
  }
  if (Array.isArray(users)) {
    SUPERADMIN_USERS = users.map((u) => u.username);
    USER_PROFILES = Object.fromEntries(
      users.map((u) => [u.username, { name: u.displayName, role: "Admin" }])
    );
  }
  if (accounts && typeof accounts === "object") {
    if (Array.isArray(accounts.exchange)) ACCOUNTS_EXCHANGE = accounts.exchange;
    if (Array.isArray(accounts.wallet))   ACCOUNTS_WALLET   = accounts.wallet;
    if (Array.isArray(accounts.broker))   ACCOUNTS_BROKER   = accounts.broker;
  }
  return {
    counterparties: counterparties?.length ?? 0,
    portfolios: portfolios?.length ?? 0,
    users: users?.length ?? 0,
    accounts:
      (Array.isArray(accounts?.exchange) ? accounts.exchange.length : 0) +
      (Array.isArray(accounts?.wallet)   ? accounts.wallet.length   : 0) +
      (Array.isArray(accounts?.broker)   ? accounts.broker.length   : 0),
  };
}

// ═════════════════════════════════════════════════════════════
// Cashflow tx-hash fetch — EVM network set + validation helpers.
// EVM_NETWORKS is duplicated client-side so the Fetch button's
// disabled state is instant (no round-trip). Canonical list lives
// in scripts/cashflow_tx_fetch.py:CHAINS — keep both in sync.
// ═════════════════════════════════════════════════════════════
const EVM_NETWORKS = new Set([
  "ETHEREUM", "BINANCE SMART CHAIN", "POLYGON", "ARBITRUM", "OPTIMISM",
  "BASE", "AVALANCHE", "LINEA", "SCROLL", "MANTLE", "BLAST", "MODE",
  "CELO", "ZKSYNC", "SONIC", "GNOSIS", "BERACHAIN", "HYPEREVM",
  "UNICHAIN", "SONEIUM", "ZETA", "PLASMA", "TEMPO", "SAGAEVM", "XRPLEVM",
]);

const TX_HASH_RE = /^0x[0-9a-fA-F]{64}$/;

function fetchButtonDisabledReason(network, txHash) {
  if (!network) return "Pick a network first";
  if (!EVM_NETWORKS.has(network)) return "Tx fetch only supports EVM chains for now";
  if (!txHash || !TX_HASH_RE.test(txHash.trim())) return "Enter a valid 0x… hash";
  return null;
}

function shortAddr(addr) {
  if (!addr || addr.length < 12) return addr || "";
  return `${addr.slice(0, 6)}…${addr.slice(-4)}`;
}

// ═════════════════════════════════════════════════════════════
// Altas editorial palette — mirrors the nxgen-mo dashboard's
// bone/ink/hair tokens (see dashboard/src/index.css @theme block).
// Same token names as before so downstream usage stays uniform.
// ═════════════════════════════════════════════════════════════
const BB = {
  bg: "#ffffff",           // white (canvas)
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

// Format a numeric counterparty id (e.g. 1) as the wire/storage form
// "CID000001". Returns null for unknown / missing ids so the backend
// stores NULL (e.g. INTER PTF FUNDING where the counterparty field
// holds a portfolio number, not a refdata counterparty).
const formatCID = (id) => (id == null ? null : "CID" + String(id).padStart(6, "0"));

const CATEGORIES = ["SPOT", "FUTURE", "CASHFLOW", "LOAN"];
const VENUE_TYPES = ["CEX", "DEX", "OnChain", "OTC", "Internal", "RWA"];

// FUTURE constants
const FUTURE_CONTRACT_TYPES = ["PERP", "DATED"];
const FUTURE_MARGIN_MODES = ["CROSS", "ISOLATED"];

// CASHFLOW constants — direction-aware subtype menus.
// Captures the original brainstorm's 34 trade-types collapsed into one flow.
const CASHFLOW_DIRECTIONS = ["OUTGOING", "INCOMING"];
// Placeholder cashflow types — backend will swap to MySQL select_category=CASHFLOW TYPE (28 values).
const CASHFLOW_TYPES = [
  "INTER PTF FUNDING",
  "RETAINER FEES",
  "OPEX",
  "OTHER INCOME",
  "OTHER EXPENSE",
  "TRANSFER FEES",
  "INTEREST EXPENSE",
  "INTEREST INCOME",
  "WITHHOLDING TAX",
  "LOAN",
  "LOAN REPAYMENT",
];
// Cashflow types that semantically belong to a loan contract — when
// any of these is selected, the form surfaces the loan-link picker
// and the backend's set_mappings_for_cashflow derives a mapping_type
// from (cashflow_type, direction). Keep in sync with the
// derive_mapping_type() table in scripts/loan_cashflow_map_db.py.
const LOAN_RELATED_CF_TYPES = new Set([
  "LOAN", "LOAN REPAYMENT", "INTEREST EXPENSE", "INTEREST INCOME",
]);
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
  category === "LOAN" ? "LIVE" : "CONFIRMED";
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
// Loan types — mirrors the CHECK constraint on trades_loan.loan_type.
// Keep this list and the DDL (`apply_schema_loan.py`) in sync.
// First value is the default on a fresh booking.
const LOAN_TYPES = [
  "VIP LOAN",
  "INTERNAL",
  "EXTERNAL",
  "DEFI LENDING",
];

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
  if (!dt) return { d: "", t: "00:00", s: "00" };
  const [d, tRaw = "00:00"] = dt.split("T");
  return {
    d,
    t: tRaw.slice(0, 5),
    s: tRaw.length >= 8 ? tRaw.slice(6, 8) : "00",
  };
};
// joinDt always pads to seconds so the canonical form is HH:MM:SS;
// Postgres TIMESTAMPTZ parses both forms but uniform output keeps the
// UI display and DB rows aligned. Pass an explicit `s` to preserve
// non-zero seconds typed by the user.
const joinDt = (d, t, s = "00") =>
  `${d || today00Utc().slice(0, 10)}T${(t || "00:00").slice(0, 5)}:${(s || "00").slice(0, 2)}`;
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
  const { d, t, s: secsFromValue } = splitDt(value);
  const [open, setOpen] = useState(false);
  const [viewYM, setViewYM] = useState(() => {
    const ref = d ? new Date(`${d}T00:00:00Z`) : new Date();
    return { y: ref.getUTCFullYear(), m: ref.getUTCMonth() };
  });
  const [timeDraft, setTimeDraft] = useState(t);
  const [secDraft, setSecDraft] = useState(secsFromValue);
  // Free-form text draft for the trigger input — accepts DD/MM/YYYY
  // HH:MM:SS (and variants). parseErr flips text red until corrected
  // or Escaped.
  const display = displayDateTime(value);
  const [draft, setDraft] = useState(display);
  const [parseErr, setParseErr] = useState(false);
  const popRef = useRef(null);
  const triggerRef = useRef(null);

  useEffect(() => setTimeDraft(t), [t]);
  useEffect(() => setSecDraft(secsFromValue), [secsFromValue]);
  useEffect(() => { setDraft(display); setParseErr(false); }, [display]);

  const commitDraft = () => {
    const raw = (draft || "").trim();
    if (raw === "") { onChange(""); setParseErr(false); return; }
    const parsed = parseDateTimeInput(raw);
    if (parsed === null) { setParseErr(true); return; }
    setParseErr(false);
    if (parsed !== value) onChange(parsed);
    else setDraft(display);
  };

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
      {/* Trigger — editable text input with calendar icon. Type freely
          (YYYY-MM-DD HH:mm and friends) or click the icon for the
          calendar surface. */}
      <div
        ref={triggerRef}
        className="w-full flex items-center gap-1 px-1 text-[12px] font-mono transition-colors"
        style={{
          background: "#f8f6f1",
          border: `1px solid ${open ? BB.orange : (parseErr ? "#b91c1c" : BB.border)}`,
          height: 30,
        }}
        onMouseEnter={(ev) => {
          if (open) return;
          ev.currentTarget.style.background = "#ffffff";
          if (!parseErr) ev.currentTarget.style.borderColor = "#6a665c";
        }}
        onMouseLeave={(ev) => {
          if (open) return;
          ev.currentTarget.style.background = "#f8f6f1";
          if (!parseErr) ev.currentTarget.style.borderColor = BB.border;
        }}
      >
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-label="Open calendar"
          style={{
            background: "transparent",
            border: "none",
            padding: "0 4px",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
          }}
          tabIndex={-1}
        >
          <Calendar size={12} style={{ color: BB.orange }} />
        </button>
        <input
          type="text"
          value={draft}
          placeholder="dd/mm/yyyy hh:mm:ss"
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commitDraft}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              commitDraft();
              setOpen(false);
            } else if (e.key === "Escape") {
              setDraft(display);
              setParseErr(false);
              setOpen(false);
            }
          }}
          className="flex-1 min-w-0 tracking-[0.04em]"
          style={{
            background: "transparent",
            border: "none",
            outline: "none",
            color: parseErr ? "#b91c1c" : "#0d0d0d",
            padding: "0 4px",
            font: "inherit",
            width: "100%",
          }}
          title={parseErr ? "Couldn't parse — try 'DD/MM/YYYY HH:mm:ss'" : undefined}
        />
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-label="Toggle calendar"
          style={{
            background: "transparent",
            border: "none",
            padding: "0 4px",
            cursor: "pointer",
            color: BB.faint,
            fontSize: 10,
            lineHeight: 1,
          }}
          tabIndex={-1}
        >▾</button>
      </div>

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

// Parse a free-form date string into canonical YYYY-MM-DD.
// Accepts: 2025-08-15, 2025/8/15, 15/08/2025, 15-8-2025, 20250815, 2025.08.15.
// Returns null on parse failure, "" on empty input.
function parseDateInput(raw) {
  if (raw == null) return "";
  const s = String(raw).trim();
  if (!s) return "";
  const validate = (y, mo, da) => {
    const yi = parseInt(y, 10), mi = parseInt(mo, 10), di = parseInt(da, 10);
    if (mi < 1 || mi > 12 || di < 1 || di > 31) return null;
    const dt = new Date(Date.UTC(yi, mi - 1, di));
    if (dt.getUTCFullYear() !== yi || dt.getUTCMonth() !== mi - 1 || dt.getUTCDate() !== di) return null;
    return `${yi}-${String(mi).padStart(2, "0")}-${String(di).padStart(2, "0")}`;
  };
  let m;
  if ((m = s.match(/^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$/))) return validate(m[1], m[2], m[3]);
  if ((m = s.match(/^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$/))) return validate(m[3], m[2], m[1]);
  if ((m = s.match(/^(\d{4})(\d{2})(\d{2})$/))) return validate(m[1], m[2], m[3]);
  return null;
}

// Parse free-form date-time → "YYYY-MM-DDTHH:MM:SS". Time portion is
// optional and defaults to 00:00:00; seconds are optional within the
// time portion. Separator between date and time may be space, "T", or
// comma.
function parseDateTimeInput(raw) {
  if (raw == null) return "";
  const s = String(raw).trim();
  if (!s) return "";
  const m = s.match(/^(.+?)[\sT,]+(\d{1,2}:\d{1,2}(?::\d{1,2})?)$/);
  const datePart = m ? m[1] : s;
  const timePart = m ? m[2] : "00:00";
  const d = parseDateInput(datePart);
  if (d === null || d === "") return d;
  const tm = timePart.match(/^(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?$/);
  if (!tm) return null;
  const hh = parseInt(tm[1], 10);
  const mi = parseInt(tm[2], 10);
  const ss = tm[3] != null ? parseInt(tm[3], 10) : 0;
  if (hh < 0 || hh > 23 || mi < 0 || mi > 59 || ss < 0 || ss > 59) return null;
  return `${d}T${String(hh).padStart(2, "0")}:${String(mi).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
}

// Format helpers — convert canonical ISO storage to the DD/MM/YYYY
// display format used inside the date pickers' typed inputs.
function displayDate(canonical) {
  if (!canonical) return "";
  const m = String(canonical).slice(0, 10).match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return "";
  return `${m[3]}/${m[2]}/${m[1]}`;
}
function displayDateTime(canonical) {
  if (!canonical) return "";
  const parts = String(canonical).split("T");
  const dStr = displayDate(parts[0]);
  if (!dStr) return "";
  const tRaw = (parts[1] || "00:00:00").slice(0, 8);
  const tFull = tRaw.length >= 8 ? tRaw : `${tRaw.slice(0, 5)}:00`;
  return `${dStr} ${tFull}`;
}

// Date-only sibling of DateTimePicker24 — same editorial calendar UI
// (Tokka orange accent, monospace, Mon-first week, today highlight)
// but no time column. Value is a plain YYYY-MM-DD string; emits "" when
// cleared. Used everywhere a date without a time component is required
// (loan-form dates, both enquiry filters, Accrual Date, Future Expiry)
// so all calendar surfaces in the app look identical.
//
// Manual typing: the trigger is a text input. Enter or blur parses and
// commits via parseDateInput; invalid drafts stay visible in red until
// corrected (or Escape reverts to the prior valid value).
const DatePicker = ({ value, onChange, placeholder = "dd/mm/yyyy", min, max, allowClear = true }) => {
  const d = (value || "").slice(0, 10);
  const display = displayDate(d);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(display);
  const [parseErr, setParseErr] = useState(false);
  const [viewYM, setViewYM] = useState(() => {
    const ref = d ? new Date(`${d}T00:00:00Z`) : new Date();
    return { y: ref.getUTCFullYear(), m: ref.getUTCMonth() };
  });
  const popRef = useRef(null);
  const triggerRef = useRef(null);

  // Keep the typed draft in sync when the canonical value changes
  // (picker selection, parent reset). Display in DD/MM/YYYY to match
  // the placeholder hint.
  useEffect(() => { setDraft(display); setParseErr(false); }, [display]);

  const commitDraft = () => {
    const s = (draft || "").trim();
    if (s === "") { onChange(""); setParseErr(false); return; }
    const parsed = parseDateInput(s);
    if (parsed === null) { setParseErr(true); return; }
    if (min && parsed < min) { setParseErr(true); return; }
    if (max && parsed > max) { setParseErr(true); return; }
    setParseErr(false);
    if (parsed !== d) onChange(parsed);
    else setDraft(displayDate(parsed));
  };

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

  useEffect(() => {
    if (!open || !d) return;
    const ref = new Date(`${d}T00:00:00Z`);
    setViewYM({ y: ref.getUTCFullYear(), m: ref.getUTCMonth() });
  }, [open, d]);

  const pickDate = (yyyy, mm, dd) => {
    const newD = `${yyyy}-${String(mm + 1).padStart(2, "0")}-${String(dd).padStart(2, "0")}`;
    if (min && newD < min) return;
    if (max && newD > max) return;
    onChange(newD);
    setOpen(false); // snap shut — feels responsive for filter-style UX
  };

  const setToday = () => {
    const now = new Date();
    const yyyy = now.getUTCFullYear();
    const mm = now.getUTCMonth();
    const dd = now.getUTCDate();
    const newD = `${yyyy}-${String(mm + 1).padStart(2, "0")}-${String(dd).padStart(2, "0")}`;
    if (min && newD < min) return;
    if (max && newD > max) return;
    setViewYM({ y: yyyy, m: mm });
    onChange(newD);
    setOpen(false);
  };

  const clear = () => {
    onChange("");
    setOpen(false);
  };

  const { y: vy, m: vm } = viewYM;
  const firstDow = new Date(Date.UTC(vy, vm, 1)).getUTCDay();
  const leadingBlanks = (firstDow + 6) % 7;
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
      <div
        ref={triggerRef}
        className="w-full flex items-center gap-1 px-1 text-[12px] font-mono transition-colors"
        style={{
          background: "#f8f6f1",
          border: `1px solid ${open ? BB.orange : (parseErr ? "#b91c1c" : BB.border)}`,
          height: 30,
        }}
        onMouseEnter={(ev) => {
          if (open) return;
          ev.currentTarget.style.background = "#ffffff";
          if (!parseErr) ev.currentTarget.style.borderColor = "#6a665c";
        }}
        onMouseLeave={(ev) => {
          if (open) return;
          ev.currentTarget.style.background = "#f8f6f1";
          if (!parseErr) ev.currentTarget.style.borderColor = BB.border;
        }}
      >
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-label="Open calendar"
          style={{
            background: "transparent",
            border: "none",
            padding: "0 4px",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
          }}
          tabIndex={-1}
        >
          <Calendar size={12} style={{ color: BB.orange }} />
        </button>
        <input
          type="text"
          value={draft}
          placeholder={placeholder}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commitDraft}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              commitDraft();
              setOpen(false);
            } else if (e.key === "Escape") {
              setDraft(display);
              setParseErr(false);
              setOpen(false);
            }
          }}
          className="flex-1 min-w-0 tracking-[0.04em]"
          style={{
            background: "transparent",
            border: "none",
            outline: "none",
            color: parseErr ? "#b91c1c" : "#0d0d0d",
            padding: "0 4px",
            font: "inherit",
            width: "100%",
          }}
          title={parseErr ? "Couldn't parse this date — try DD/MM/YYYY" : undefined}
        />
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-label="Toggle calendar"
          style={{
            background: "transparent",
            border: "none",
            padding: "0 4px",
            cursor: "pointer",
            color: BB.faint,
            fontSize: 10,
            lineHeight: 1,
          }}
          tabIndex={-1}
        >▾</button>
      </div>

      {open && (
        <div
          ref={popRef}
          className="absolute z-50 mt-1 p-2.5"
          style={{
            background: "#ffffff",
            border: `1px solid ${BB.orange}`,
            boxShadow: "0 12px 32px rgba(13,13,13,0.12)",
            minWidth: 240,
          }}
        >
          <div className="flex items-center justify-between mb-2 font-mono">
            <button type="button" onClick={goPrev} className="p-1" style={{ color: BB.amber }} aria-label="Previous month">
              <ChevronLeft size={14} />
            </button>
            <div className="text-[11px] tracking-[0.24em] uppercase" style={{ color: BB.orange }}>
              {MONTH_NAMES[vm]} {vy}
            </div>
            <button type="button" onClick={goNext} className="p-1" style={{ color: BB.amber }} aria-label="Next month">
              <ChevronRight size={14} />
            </button>
          </div>

          <div className="grid grid-cols-7 gap-0.5 mb-1">
            {WEEKDAY_HEADERS.map((w) => (
              <div key={w} className="text-center text-[9px] tracking-[0.15em] font-mono py-0.5" style={{ color: BB.mute }}>
                {w}
              </div>
            ))}
          </div>

          <div className="grid grid-cols-7 gap-0.5">
            {cells.map((cell, i) => {
              if (cell == null) return <div key={i} />;
              const cellStr = `${vy}-${String(vm + 1).padStart(2, "0")}-${String(cell).padStart(2, "0")}`;
              const isSelected = cellStr === d;
              const isToday = cellStr === todayStr;
              const disabled = (min && cellStr < min) || (max && cellStr > max);
              return (
                <button
                  key={i}
                  type="button"
                  disabled={disabled}
                  onClick={() => pickDate(vy, vm, cell)}
                  className="text-center text-[11px] font-mono py-1.5 transition-colors"
                  style={{
                    background: isSelected ? BB.orange : "transparent",
                    color: disabled ? BB.faint : (isSelected ? "#ffffff" : isToday ? BB.cyan : BB.text),
                    border: isToday && !isSelected ? `1px solid ${BB.cyan}` : "1px solid transparent",
                    cursor: disabled ? "not-allowed" : "pointer",
                    opacity: disabled ? 0.5 : 1,
                  }}
                  onMouseEnter={(ev) => { if (!isSelected && !disabled) ev.currentTarget.style.background = "#ece7dd"; }}
                  onMouseLeave={(ev) => { if (!isSelected && !disabled) ev.currentTarget.style.background = "transparent"; }}
                >{cell}</button>
              );
            })}
          </div>

          <div className="flex gap-1.5 mt-2">
            <button
              type="button"
              onClick={setToday}
              className="flex-1 py-1 text-[10px] uppercase tracking-[0.18em] font-mono transition-colors"
              style={{ background: BB.surface2, color: BB.dim, border: `1px solid ${BB.border}` }}
              onMouseEnter={(ev) => { ev.currentTarget.style.borderColor = BB.cyan; ev.currentTarget.style.color = BB.cyan; }}
              onMouseLeave={(ev) => { ev.currentTarget.style.borderColor = BB.border; ev.currentTarget.style.color = BB.dim; }}
            >Today</button>
            {allowClear && d && (
              <button
                type="button"
                onClick={clear}
                className="flex-1 py-1 text-[10px] uppercase tracking-[0.18em] font-mono transition-colors"
                style={{ background: BB.surface2, color: BB.dim, border: `1px solid ${BB.border}` }}
                onMouseEnter={(ev) => { ev.currentTarget.style.borderColor = BB.red; ev.currentTarget.style.color = BB.red; }}
                onMouseLeave={(ev) => { ev.currentTarget.style.borderColor = BB.border; ev.currentTarget.style.color = BB.dim; }}
              >× Clear</button>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

const Field = ({ label, required, children, span = 1, hint, headerExtra }) => (
  <div style={{ gridColumn: `span ${span}` }}>
    <div className="flex items-baseline justify-between">
      <Label required={required}>{label}</Label>
      {headerExtra ? (
        <div className="mb-1 mr-12">{headerExtra}</div>
      ) : hint ? (
        <span
          className="text-[9px] tracking-[0.2em] uppercase font-mono mb-1"
          style={{ color: BB.orange }}
        >
          {hint}
        </span>
      ) : null}
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
const PortfolioPicker = ({ value, onChange, options, fallbackLabel }) => {
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
          ) : value ? (
            // No refdata match. Prefer the row-side fallback label (the
            // portfolio_name straight off the trades_cashflow row) so we
            // don't depend on the async refdata fetch having completed
            // for an existing deal. Only show "refdata loading…" if we
            // also have no fallback.
            <>
              <span style={{ color: "#1f63ea" }}>{value}</span>
              {fallbackLabel ? (
                <>
                  <span style={{ color: "#9a9488" }}> · </span>
                  <span>{fallbackLabel}</span>
                </>
              ) : options.length === 0 ? (
                <span style={{ color: "#9a9488", fontStyle: "italic" }}> · refdata loading…</span>
              ) : null}
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
const CounterpartyPicker = ({ value, onChange, options, fallbackLabel }) => {
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
          ) : value ? (
            // No refdata match. Prefer the row-side fallback label (the
            // counterparty_id straight off the trades_cashflow row) so
            // we don't depend on the async refdata fetch having
            // completed for an existing deal.
            <>
              <span>{value}</span>
              {fallbackLabel ? (
                <span style={{ color: "#9a9488" }}> · {fallbackLabel}</span>
              ) : options.length === 0 ? (
                <span style={{ color: "#9a9488", fontStyle: "italic" }}> · refdata loading…</span>
              ) : null}
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

// One-line summary used inside the loan dropdown and in Deal Enquiry chips.
// Example: "MLA00000001 · BORROW 100,000 USDT @ 5.25% FIXED · Binance · matures 2026-06-15"
function formatLoanOptionLabel(loan) {
  if (!loan) return "";
  const principal = parseFloat(loan.principal_amount) || 0;
  const fmt = principal.toLocaleString("en-US", { maximumFractionDigits: 5 });
  const matures = loan.maturity_date ? String(loan.maturity_date).slice(0, 10) : "open-term";
  const cp = loan.counterparty ? ` · ${loan.counterparty}` : "";
  return `${loan.deal_ref} · ${loan.direction} ${fmt} ${loan.principal_asset || ""} @ ${loan.interest_rate_pa_pct || 0}% ${loan.interest_type || ""}${cp} · matures ${matures}`;
}

// Multi-select chip picker for linking a cashflow to one or more loans.
// `selected` is a string[] of MLA deal_refs; `options` is the array of
// live trades_loan rows already filtered to the relevant portfolio.
const LoanPicker = ({ selected, onChange, options }) => {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (!wrapRef.current?.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const byRef = new Map(options.map((o) => [o.deal_ref, o]));
  const remaining = options.filter((o) => !selected.includes(o.deal_ref));

  const addRef = (ref) => {
    if (!ref || selected.includes(ref)) return;
    onChange([...selected, ref]);
    setOpen(false);
  };
  const removeRef = (ref) => onChange(selected.filter((r) => r !== ref));

  return (
    <div ref={wrapRef} className="relative w-full">
      <div
        className="w-full flex flex-wrap gap-1 px-1.5 py-1 text-[12px] font-mono"
        style={{ background: "#f8f6f1", border: "1px solid #d9d4c7", minHeight: 32 }}
      >
        {selected.length === 0 && (
          <span className="px-1 py-0.5" style={{ color: "#9a9488" }}>
            — no loan tagged —
          </span>
        )}
        {selected.map((ref) => {
          const loan = byRef.get(ref);
          return (
            <span
              key={ref}
              className="inline-flex items-center gap-1 px-2 py-0.5"
              title={loan ? formatLoanOptionLabel(loan) : ref}
              style={{ background: "#eef0f6", border: "1px solid #c8cde0", color: "#1f63ea" }}
            >
              <span>{ref}</span>
              <button
                type="button"
                aria-label={`Remove ${ref}`}
                onClick={() => removeRef(ref)}
                style={{ background: "transparent", border: "none", color: "#1f63ea", cursor: "pointer", padding: 0, fontSize: 12, lineHeight: 1 }}
              >×</button>
            </span>
          );
        })}
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="px-2 py-0.5 ml-auto"
          style={{
            background: open ? "#1f63ea" : "transparent",
            color: open ? "#ffffff" : "#1f63ea",
            border: `1px dashed ${open ? "#1f63ea" : "#1f63ea"}`,
            cursor: remaining.length === 0 ? "not-allowed" : "pointer",
            opacity: remaining.length === 0 ? 0.4 : 1,
          }}
          disabled={remaining.length === 0}
        >
          + Add loan
        </button>
      </div>
      {open && remaining.length > 0 && (
        <div
          className="absolute z-50 mt-1 left-0"
          style={{
            background: "#ffffff",
            border: "1px solid #1f63ea",
            boxShadow: "0 12px 32px rgba(13,13,13,0.12)",
            minWidth: "100%",
            width: 540,
            maxHeight: 360,
            overflowY: "auto",
          }}
        >
          {remaining.map((loan) => (
            <button
              key={loan.deal_ref}
              type="button"
              onClick={() => addRef(loan.deal_ref)}
              className="block w-full text-left px-3 py-2 text-[12px] font-mono"
              style={{
                background: "transparent",
                border: "none",
                borderBottom: "1px solid #efece4",
                cursor: "pointer",
                color: "#0d0d0d",
              }}
              onMouseEnter={(ev) => { ev.currentTarget.style.background = "#f3f1ea"; }}
              onMouseLeave={(ev) => { ev.currentTarget.style.background = "transparent"; }}
            >
              <span style={{ color: "#1f63ea" }}>{loan.deal_ref}</span>
              <span style={{ color: "#9a9488" }}> · </span>
              <span>{loan.direction} {parseFloat(loan.principal_amount || 0).toLocaleString("en-US", { maximumFractionDigits: 5 })} {loan.principal_asset}</span>
              <span style={{ color: "#9a9488" }}> · </span>
              <span>{loan.interest_rate_pa_pct || 0}% {loan.interest_type}</span>
              {loan.counterparty && <>
                <span style={{ color: "#9a9488" }}> · </span>
                <span>{loan.counterparty}</span>
              </>}
              <div className="text-[10px] mt-0.5" style={{ color: "#6a665c" }}>
                matures {loan.maturity_date ? String(loan.maturity_date).slice(0, 10) : "open-term"}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

// Searchable asset combobox — value is the token SYMBOL (string).
// Options come from TOKENS (snapshot of reference_data.instrument_token_grouped).
// Filter matches symbol or long name (e.g. typing "apple" finds AAPLON/AAPLX).
const AssetPicker = ({ value, onChange, options, placeholder = "— select asset —", disabled = false }) => {
  const ctxTokens = useContext(TokensContext);
  const list = options || ctxTokens;
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const wrapRef = useRef(null);
  const inputRef = useRef(null);

  // If the parent locks us mid-open, slam shut so the dropdown doesn't
  // linger after the disabled state kicks in.
  useEffect(() => {
    if (disabled && open) setOpen(false);
  }, [disabled, open]);

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
        disabled={disabled}
        onClick={() => {
          if (disabled) return;
          setOpen((o) => !o);
          setSearch("");
        }}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 text-[12px] text-[#0d0d0d] font-mono text-left transition-colors"
        style={{
          background: disabled ? "#efece4" : "#f8f6f1",
          border: `1px solid ${open ? "#1f63ea" : "#d9d4c7"}`,
          cursor: disabled ? "not-allowed" : "pointer",
          opacity: disabled ? 0.85 : 1,
        }}
        onMouseEnter={(ev) => {
          if (open || disabled) return;
          ev.currentTarget.style.background = "#ffffff";
          ev.currentTarget.style.borderColor = "#6a665c";
        }}
        onMouseLeave={(ev) => {
          if (open || disabled) return;
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

// Horizontal product tab strip rendered at the top of the Create Deal modal.
// Active tab: ink text + 2px ink underline. Inactive: muted. Coming-soon
// products render as disabled tabs with the same "soon" chip used in the
// sidebar today.
const ProductTabs = ({ active, onChange, locked = false }) => (
  <div
    className="flex items-end gap-6 px-5 pt-5 pb-0"
    style={{ borderBottom: `1px solid #d9d4c7` }}
  >
    {SIDEBAR_CATEGORIES.map((c) => {
      const isActive = c.key === active;
      // In amend mode (`locked`) we only render the active tab so the
      // user can't accidentally switch product mid-amendment. The
      // amend operates on a specific deal_ref of a specific product
      // — switching tabs would silently wipe the in-flight form.
      if (locked && !isActive) return null;
      const disabled = c.comingSoon || locked;
      return (
        <button
          key={c.key}
          type="button"
          disabled={disabled}
          onClick={() => !disabled && onChange(c.key)}
          className="pb-2 text-[13px] transition-colors"
          style={{
            color: disabled
              ? "#a5a097"
              : isActive
              ? "#0d0d0d"
              : "#6a665c",
            fontWeight: isActive ? 500 : 400,
            borderBottom: isActive
              ? "2px solid #0d0d0d"
              : "2px solid transparent",
            marginBottom: -1,
            cursor: disabled ? "not-allowed" : "pointer",
            background: "transparent",
          }}
          onMouseEnter={(e) => {
            if (!disabled && !isActive) e.currentTarget.style.color = "#0d0d0d";
          }}
          onMouseLeave={(e) => {
            if (!disabled && !isActive) e.currentTarget.style.color = "#6a665c";
          }}
        >
          <span className="inline-flex items-center gap-2">
            {c.label}
            {/* "soon" is a product-status marker — only show it for
                comingSoon tabs, not when the tab is merely disabled
                because we're in amend-locked mode. */}
            {c.comingSoon && (
              <span
                className="text-[8px] tracking-[0.2em] uppercase font-mono px-1.5 py-0.5"
                style={{
                  color: "#a5a097",
                  border: `1px solid #d9d4c7`,
                  background: "#efeae0",
                }}
              >
                soon
              </span>
            )}
          </span>
        </button>
      );
    })}
  </div>
);

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

// Fixed-position overlay wrapper for the Create Deal / amend form.
function ModalShell({ open, onClose, children }) {
  // Two-frame mount → triggers the CSS transition (opacity + slight
  // scale on the inner panel). Without this, the element renders at
  // its final state and the transition has nothing to animate from.
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    if (!open) {
      setMounted(false);
      return;
    }
    const id = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(id);
  }, [open]);

  // ESC closes the modal. Listener only attached while open so it
  // doesn't intercept Escape when the form isn't on screen.
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-40 p-4 overflow-auto"
      style={{
        background: mounted ? "rgba(0,0,0,0.5)" : "rgba(0,0,0,0)",
        transition: "background 160ms ease-out",
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        className="relative mx-auto"
        style={{
          width: "min(95vw, 1600px)",
          background: "#f6f3ec",
          border: "1px solid #d9d4c7",
          boxShadow: "0 16px 48px rgba(0,0,0,0.3)",
          opacity: mounted ? 1 : 0,
          transform: mounted ? "translateY(0)" : "translateY(-8px)",
          transition: "opacity 160ms ease-out, transform 160ms ease-out",
        }}
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="absolute z-10"
          style={{
            top: 10,
            right: 10,
            width: 32,
            height: 32,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: "#1f1f1f",
            color: "#f2efe8",
            fontSize: 20,
            lineHeight: 1,
            borderRadius: 16,
            boxShadow: "0 2px 6px rgba(0,0,0,0.2)",
            cursor: "pointer",
          }}
        >×</button>
        {children}
      </div>
    </div>
  );
}

// Audit-trail modal: fetches every SCD2 version of a deal_ref and
// renders a timeline (oldest at the bottom, newest on top). For each
// version after the first, highlights the fields that changed compared
// to the prior version.
const AUDIT_DIFF_FIELDS_CASHFLOW = [
  "cashflow_type", "direction", "counterparty", "account",
  "account_type", "asset", "amount", "fee_asset", "fee_amount",
  "trade_date", "value_date", "network", "txid_reference",
  "status", "user_id", "comment", "external_trade_id",
  // Loan links (`mappings`) deliberately omitted — the map table isn't
  // bitemporal, so every version of a cashflow row carries the *same*
  // current-mappings snapshot from the LEFT JOIN. A diff would always
  // be empty. The current state is shown on the initial-booking line.
];
const AUDIT_DIFF_FIELDS_LOAN = [
  "direction", "loan_type", "counterparty",
  "principal_asset", "principal_amount",
  "interest_asset", "interest_rate_pa_pct", "interest_type", "day_count_basis", "floating_benchmark",
  "collateral_asset", "collateral_amount",
  "is_hedged", "hedged_asset", "hedged_qty", "hedged_price",
  "hedge_proceeds_asset", "hedge_proceeds_amount",
  "trade_date", "maturity_date",
  "status", "user_id", "comment", "order_id",
];
const AUDIT_DIFF_FIELDS_SPOT = [
  "direction", "counterparty", "account", "account_type",
  "base_asset", "base_amount", "quote_asset", "quote_amount", "price",
  "fee_asset", "fee_amount",
  "trade_date", "value_date", "txid_reference",
  "status", "user_id", "comment", "external_trade_id",
];
const AUDIT_FIELD_LABELS = {
  // shared
  direction: "Direction", counterparty: "Counterparty", account: "Account",
  account_type: "Account Type", trade_date: "Trade Date",
  status: "Status", user_id: "User", comment: "Comment",
  // cashflow
  cashflow_type: "Cashflow Type", asset: "Asset", amount: "Amount",
  fee_asset: "Fee Asset", fee_amount: "Fee Amount",
  value_date: "Value Date", network: "Network", txid_reference: "Tx Hash",
  external_trade_id: "External ID",
  // loan
  loan_type: "Loan Type",
  principal_asset: "Principal Asset", principal_amount: "Principal Amount",
  interest_asset: "Interest Asset", interest_rate_pa_pct: "Interest Rate (% p.a.)",
  interest_type: "Interest Type", day_count_basis: "Day Basis", floating_benchmark: "Floating Benchmark",
  collateral_asset: "Collateral Asset", collateral_amount: "Collateral Amount",
  is_hedged: "Hedged", hedged_asset: "Hedged Asset", hedged_qty: "Hedged Qty",
  hedged_price: "Hedged Price", hedge_proceeds_asset: "Hedge Proceeds Asset",
  hedge_proceeds_amount: "Hedge Proceeds Amount",
  maturity_date: "Maturity Date", order_id: "Order ID",
  // spot
  base_asset: "Base Asset", base_amount: "Base Amount",
  quote_asset: "Quote Asset", quote_amount: "Quote Amount",
  price: "Price",
  // Map-table links
  mappings: "Linked Loans",
};

function HistoryModal({ open, dealRef, state, onClose }) {
  // Two-frame mount → fade in
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    if (!open) { setMounted(false); return; }
    const id = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(id);
  }, [open]);

  // ESC closes the modal.
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const rows = state?.rows || [];
  // Pick diff fields per product. Each product has its own set of
  // audited columns (loan principal/interest, spot base/quote/price,
  // cashflow amount/asset).
  const product =
    rows[0]?.txn_type === "LOAN" ? "LOAN"
    : rows[0]?.txn_type === "SPOT" ? "SPOT"
    : "CASHFLOW";
  const diffFields =
    product === "LOAN" ? AUDIT_DIFF_FIELDS_LOAN
    : product === "SPOT" ? AUDIT_DIFF_FIELDS_SPOT
    : AUDIT_DIFF_FIELDS_CASHFLOW;
  // Build per-version diff: for each row (except the first), compute which
  // diffFields changed vs the prior row.
  const diffs = rows.map((row, i) => {
    if (i === 0) return { initial: true, changed: [] };
    const prev = rows[i - 1];
    const changed = diffFields.filter((f) => {
      const a = row[f] ?? null, b = prev[f] ?? null;
      return String(a) !== String(b);
    }).map((f) => ({ field: f, from: prev[f], to: row[f] }));
    return { initial: false, changed };
  });

  return (
    <div
      className="fixed inset-0 z-50 p-4 overflow-auto"
      style={{
        background: mounted ? "rgba(0,0,0,0.5)" : "rgba(0,0,0,0)",
        transition: "background 160ms ease-out",
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        className="relative max-w-3xl mx-auto"
        style={{
          background: "#f6f3ec",
          border: "1px solid #d9d4c7",
          boxShadow: "0 16px 48px rgba(0,0,0,0.3)",
          opacity: mounted ? 1 : 0,
          transform: mounted ? "translateY(0)" : "translateY(-8px)",
          transition: "opacity 160ms ease-out, transform 160ms ease-out",
          fontFamily: "'IBM Plex Mono', ui-monospace, monospace",
        }}
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="absolute z-10"
          style={{
            top: 10, right: 10, width: 32, height: 32,
            display: "flex", alignItems: "center", justifyContent: "center",
            background: "#1f1f1f", color: "#f2efe8",
            fontSize: 20, lineHeight: 1, borderRadius: 16,
            boxShadow: "0 2px 6px rgba(0,0,0,0.2)", cursor: "pointer",
          }}
        >×</button>

        <div className="px-6 py-5" style={{ borderBottom: "1px solid #d9d4c7" }}>
          <div className="text-[11px] tracking-[0.25em] uppercase opacity-60">Audit Trail</div>
          <div className="text-[22px] mt-1" style={{ fontFamily: "'Cormorant Garamond', 'EB Garamond', Georgia, serif" }}>
            {dealRef}
          </div>
          <div className="text-[11px] opacity-60 mt-1">
            {state?.loading ? "Loading…" : `${rows.length} version${rows.length === 1 ? "" : "s"} on record`}
          </div>
        </div>

        <div className="px-6 py-4 max-h-[70vh] overflow-y-auto">
          {state?.loading && <div className="text-[12px] opacity-70">Loading audit trail…</div>}
          {state?.error && (
            <div className="text-[12px]" style={{ color: "#7a1f00" }}>
              Error: {state.error}
            </div>
          )}
          {!state?.loading && !state?.error && rows.length === 0 && (
            <div className="text-[12px] opacity-70">No history found for this deal_ref.</div>
          )}
          {!state?.loading && !state?.error && rows.length > 0 && (
            <ol className="space-y-3">
              {rows.map((row, i) => {
                const d = diffs[i];
                const version = i + 1;
                const isLive = row.effective_end == null;
                return (
                  <li
                    key={i}
                    className="px-3 py-3"
                    style={{
                      background: isLive ? "#eef5e9" : "#ffffff",
                      border: `1px solid ${isLive ? "#7ea66a" : "#d9d4c7"}`,
                    }}
                  >
                    <div className="flex items-baseline justify-between text-[11px]">
                      <span>
                        <strong>v{version}</strong>
                        {isLive && <span className="ml-2 px-1.5 py-0.5 text-[10px]" style={{background: "#1f4a1f", color: "#e8f5e2"}}>LIVE</span>}
                        {!isLive && d.initial && <span className="ml-2 opacity-60">initial</span>}
                      </span>
                      <span className="opacity-70">by {row.user_id || "—"}</span>
                    </div>
                    <div className="text-[10px] opacity-60 mt-1">
                      effective {String(row.effective_start).replace("T", " ").slice(0, 19)} UTC
                      {row.effective_end && (
                        <> → {String(row.effective_end).replace("T", " ").slice(0, 19)} UTC</>
                      )}
                    </div>

                    {d.initial ? (
                      <div className="mt-2 text-[11px]">
                        Initial booking:{" "}
                        {row.txn_type === "LOAN" ? (
                          <>
                            <code>{row.loan_type}</code>{" · "}
                            <code>{row.direction}</code>{" · "}
                            <code>{row.principal_amount} {row.principal_asset}</code>{" @ "}
                            <code>{row.interest_rate_pa_pct}% {row.interest_type}</code>{" · status "}
                            <code>{row.status}</code>
                            {row.counterparty && <> · cp <code>{row.counterparty}</code></>}
                          </>
                        ) : row.txn_type === "SPOT" ? (
                          <>
                            <code>{row.direction}</code>{" · "}
                            <code>{row.base_amount} {row.base_asset}</code>{" @ "}
                            <code>{row.price}</code>{" · "}
                            <code>{row.quote_amount} {row.quote_asset}</code>{" · status "}
                            <code>{row.status}</code>
                            {row.counterparty && <> · cp <code>{row.counterparty}</code></>}
                          </>
                        ) : (
                          <>
                            <code>{row.cashflow_type}</code>{" · "}
                            <code>{row.direction}</code>{" · "}
                            <code>{row.amount} {row.asset}</code>{" · status "}
                            <code>{row.status}</code>
                            {row.counterparty && <> · cp <code>{row.counterparty}</code></>}
                            {/* Currently-linked loans — pulled from the map
                                table snapshot. Same for every version row
                                (the map table is not bitemporal). */}
                            {Array.isArray(row.mappings) && row.mappings.length > 0 && (
                              <> · linked to <code>{row.mappings.map((m) => m.counterpart_deal_ref).join(", ")}</code></>
                            )}
                          </>
                        )}
                      </div>
                    ) : d.changed.length === 0 ? (
                      <div className="mt-2 text-[11px] opacity-70">
                        (no changes to audited fields)
                      </div>
                    ) : (
                      <ul className="mt-2 space-y-1 text-[11px]">
                        {d.changed.map((c) => (
                          <li key={c.field}>
                            <strong>{AUDIT_FIELD_LABELS[c.field] || c.field}:</strong>{" "}
                            <span style={{ color: "#7a1f00", textDecoration: "line-through" }}>
                              {c.from === null || c.from === "" ? "∅" : String(c.from)}
                            </span>
                            {"  →  "}
                            <span style={{ color: "#1f4a1f" }}>
                              {c.to === null || c.to === "" ? "∅" : String(c.to)}
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </li>
                );
              }).reverse()}
            </ol>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── LoanScheduleModal — drill-down for one loan ──────────────────────
// Fetches /api/loan/:deal_ref on open, renders the loan contract
// summary + computed running balances + chronological table of mapped
// cashflows. Buttons inline let the user jump to amend or audit history.
// Parse a stored trade_date as a UTC date-only timestamp. Trade dates are
// "YYYY-MM-DDTHH:MM:SS" with no zone; naive Date.parse treats them as local
// time which shifts fmtScheduleDate one day earlier in zones east of UTC.
// Slicing the date portion and appending T00:00:00Z forces UTC midnight.
const _LOAN_MS_PER_DAY = 86400000;
function _parseLoanTradeDateMs(s) {
  if (!s) return NaN;
  return Date.parse(String(s).slice(0, 10) + "T00:00:00Z");
}

// Compute the amortization-by-event schedule rows for one loan.
//
// Inputs:
//   loan         — loan row (with `.mappings` already attached)
//   accrualDate  — YYYY-MM-DD cutoff for the LIVE (still-open) period's
//                  accrual, or null/undefined to skip LIVE accrual
//
// Returns: array of period objects { startMs, endMs, notional, calcEndMs,
//   days, accrued, netPaid, triggerDealRef }. Same shape the LoanScheduleModal
//   has used since the schedule view was introduced.
//
// Pure: no React, no I/O, no DOM. Safe to call from the export pipeline.
function buildLoanScheduleRows(loan, accrualDate) {
  if (!loan) return [];
  const mappings = [...(loan.mappings || [])].sort((a, b) => {
    const ta = String(a.trade_date || "");
    const tb = String(b.trade_date || "");
    return ta.localeCompare(tb);
  });
  const dayBasis = parseInt(loan.day_count_basis, 10) || 365;
  const rate = (parseFloat(loan.interest_rate_pa_pct) || 0) / 100;
  const principalAmount = parseFloat(loan.principal_amount) || 0;
  const accrualEndMs = accrualDate ? Date.parse(accrualDate + "T23:59:59Z") : null;
  const tradeStartMs = loan.trade_date ? _parseLoanTradeDateMs(loan.trade_date) : null;

  const events = [];
  for (const m of mappings) {
    if (!m.trade_date) continue;
    const ms = _parseLoanTradeDateMs(m.trade_date);
    if (Number.isNaN(ms)) continue;
    if (m.mapping_type === "PRINCIPAL_DISBURSE") {
      events.push({ ms, type: "DISBURSE", amount: Math.abs(parseFloat(m.amount) || 0), dealRef: m.counterpart_deal_ref });
    } else if (m.mapping_type === "PRINCIPAL_REPAY") {
      events.push({ ms, type: "REPAY", amount: Math.abs(parseFloat(m.amount) || 0), dealRef: m.counterpart_deal_ref });
    } else if (m.mapping_type === "INTEREST") {
      events.push({ ms, type: "INTEREST", amount: Math.abs(parseFloat(m.amount) || 0), dealRef: m.counterpart_deal_ref });
    }
  }
  // Fallback: no disburse cashflow linked → synthesise from the loan row itself.
  if (!events.some((e) => e.type === "DISBURSE") && tradeStartMs != null) {
    events.push({ ms: tradeStartMs, type: "DISBURSE", amount: principalAmount, dealRef: null });
  }
  events.sort((a, b) => a.ms - b.ms);
  if (events.length === 0) return [];

  // Collapse same-day same-type events.
  const eventsByDayType = new Map();
  for (const ev of events) {
    const key = `${ev.ms}|${ev.type}`;
    const prior = eventsByDayType.get(key);
    if (prior) {
      prior.amount += ev.amount;
      if (ev.dealRef && (!prior.dealRef || ev.dealRef < prior.dealRef)) {
        prior.dealRef = ev.dealRef;
      }
    } else {
      eventsByDayType.set(key, { ...ev });
    }
  }
  const collapsedEvents = Array.from(eventsByDayType.values()).sort((a, b) => {
    if (a.ms !== b.ms) return a.ms - b.ms;
    const order = { DISBURSE: 0, REPAY: 1, INTEREST: 2 };
    return (order[a.type] ?? 99) - (order[b.type] ?? 99);
  });

  const periods = [];
  let notional = 0;
  for (let i = 0; i < collapsedEvents.length; i++) {
    const ev = collapsedEvents[i];
    if (ev.type === "DISBURSE") notional += ev.amount;
    else if (ev.type === "REPAY") notional -= ev.amount;
    const startMs = i === 0 ? ev.ms : ev.ms + _LOAN_MS_PER_DAY;
    const next = collapsedEvents[i + 1];
    const endMs = next ? next.ms : null;
    if (notional <= 0) continue;

    const cutoffMs = endMs != null ? endMs : accrualEndMs;
    let days = 0;
    let calcEndMs = null;
    if (cutoffMs != null && cutoffMs >= startMs) {
      days = Math.floor((cutoffMs - startMs) / _LOAN_MS_PER_DAY) + 1;
      calcEndMs = cutoffMs;
    }
    const accrued = notional * rate * days / dayBasis;
    const netPaid = next && next.type === "INTEREST" ? next.amount : 0;

    periods.push({ startMs, endMs, notional, calcEndMs, days, accrued, netPaid, triggerDealRef: ev.dealRef });
  }
  return periods;
}

function LoanScheduleModal({ open, dealRef, state, currentUser, onClose, onAmend, onHistory, onCashflowSelect, onBookCashflow }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    if (!open) { setMounted(false); return; }
    const id = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(id);
  }, [open]);

  // Accrual Date — as-of date for the interest computation. Defaults
  // to UTC today minus 1 (T-1 EOD convention — avoids the intraday
  // ambiguity of running an accrual on the same day the trade lands).
  // User can edit; the displayed numbers reactively recompute.
  const defaultAccrualDate = useMemo(() => {
    const d = new Date();
    d.setUTCDate(d.getUTCDate() - 1);
    return d.toISOString().slice(0, 10); // YYYY-MM-DD
  }, []);
  const [accrualDate, setAccrualDate] = useState(defaultAccrualDate);
  // Active tab — three views: "details" (contract / principal / hedge),
  // "schedule" (amortization-by-event), "cashflows" (mapped rows).
  const [activeTab, setActiveTab] = useState("details");
  // Per-row editable Comment cells in the Loan Schedule. Keyed by the
  // row's startMs (stable across re-renders since collapsedEvents are
  // deterministic from the mappings). Seeded from loan.schedule_comments
  // when the loan loads; saved back via onBlur → /api/loan/schedule-comment.
  const [rowComments, setRowComments] = useState({});
  // Per-row save-error state — set when /api/loan/schedule-comment fails,
  // cleared on next successful save. Drives the red-border indicator.
  const [rowSaveErrors, setRowSaveErrors] = useState({});
  // Snapshot of the last-saved value per row, used to skip POSTs when
  // a blur fires with no actual change.
  const savedCommentsRef = useRef({});
  // Reset to T-1 + Details tab + empty comments whenever the modal
  // re-opens with a different loan, so stale state doesn't leak.
  useEffect(() => {
    if (open) {
      setAccrualDate(defaultAccrualDate);
      setActiveTab("details");
      setRowComments({});
      setRowSaveErrors({});
      savedCommentsRef.current = {};
    }
  }, [open, dealRef, defaultAccrualDate]);

  // Seed rowComments from loan.schedule_comments once the loan loads.
  // Keys by trigger_cashflow_deal_ref (stable across cashflow trade_date
  // amends). Each schedule row also carries its triggerDealRef, so the
  // input cell can look up its comment by that same key regardless of
  // where the row currently sits on the schedule.
  const scheduleCommentsFromLoan = state?.loan?.schedule_comments;
  useEffect(() => {
    if (!Array.isArray(scheduleCommentsFromLoan)) return;
    const seeded = {};
    for (const c of scheduleCommentsFromLoan) {
      const ref = c.trigger_cashflow_deal_ref;
      if (ref) seeded[ref] = c.comment || "";
    }
    setRowComments(seeded);
    savedCommentsRef.current = { ...seeded };
  }, [scheduleCommentsFromLoan]);

  // POST one comment to the upsert endpoint. Called on blur; no-op when
  // the value hasn't changed since last save. Keyed by triggerDealRef
  // (stable across cashflow trade_date amends). period_start_date is
  // still sent for informational refresh of the DB column.
  const saveRowComment = useCallback(async (triggerDealRef, startMs, comment) => {
    if (!dealRef || !triggerDealRef) return;
    if (savedCommentsRef.current[triggerDealRef] === comment) return;
    const dateStr =
      startMs != null ? new Date(startMs).toISOString().slice(0, 10) : "";
    const payload = {
      deal_ref: dealRef,
      trigger_cashflow_deal_ref: triggerDealRef,
      period_start_date: dateStr,
      comment,
      user_id: currentUser || "unknown",
    };
    let lastErr = "";
    try {
      const r = await api("/api/loan/schedule-comment", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (r.ok) {
        savedCommentsRef.current[triggerDealRef] = comment;
        setRowSaveErrors((prev) => {
          if (!(triggerDealRef in prev)) return prev;
          const next = { ...prev };
          delete next[triggerDealRef];
          return next;
        });
        return;
      }
      const text = await r.text().catch(() => "");
      lastErr = `HTTP ${r.status}${text ? `: ${text.slice(0, 200)}` : ""}`;
    } catch (e) {
      lastErr = String(e);
    }
    console.error(`[schedule-comment] save failed for ${dealRef}/${triggerDealRef}: ${lastErr}`);
    setRowSaveErrors((prev) => ({ ...prev, [triggerDealRef]: lastErr || "save failed" }));
  }, [dealRef, currentUser]);

  if (!open) return null;

  const loan = state?.loan;
  // Sort mappings chronologically. Backend already does this, but we
  // re-sort defensively in case trade_date is null on some rows.
  const mappings = [...(loan?.mappings || [])].sort((a, b) => {
    const ta = String(a.trade_date || "");
    const tb = String(b.trade_date || "");
    return ta.localeCompare(tb);
  });

  // Running balances. Disbursed - Repaid = outstanding principal.
  // Interest is tracked separately. Sign convention: amounts on the
  // cashflow row are already signed (OUTGOING=-, INCOMING=+), so the
  // magnitude is what we want.
  let disbursed = 0, repaid = 0, interest = 0, fees = 0;
  for (const m of mappings) {
    const mag = Math.abs(parseFloat(m.amount) || 0);
    if (m.mapping_type === "PRINCIPAL_DISBURSE") disbursed += mag;
    else if (m.mapping_type === "PRINCIPAL_REPAY") repaid += mag;
    else if (m.mapping_type === "INTEREST") interest += mag;
    else if (m.mapping_type === "FEE") fees += mag;
  }
  const outstanding = disbursed - repaid;
  const principalAsset = loan?.principal_asset || "";
  const interestAsset = loan?.interest_asset || "";
  // All loan figures capped at 5 decimal places.
  const fmt = (n) => Number(n || 0).toLocaleString("en-US", { maximumFractionDigits: 5 });
  const fmt5 = fmt;

  // ─── Per-row interest accrual ────────────────────────────────────
  // For each PRINCIPAL_DISBURSE cashflow row, simple interest accrues
  // from THAT ROW's trade_date until the user-picked Accrual Date:
  //
  //   accrued_row = abs(cashflow.amount) × (rate/100) × (days / day_basis)
  //
  // Rate and day_basis still come from the MLA loan row; the principal
  // slice is the disbursement cashflow's own amount (so multiple
  // disbursements on different dates each accrue on their own date).
  // Other mapping types render no figure (column shows —).
  const dayBasis = parseInt(loan?.day_count_basis, 10) || 365;
  const rate = (parseFloat(loan?.interest_rate_pa_pct) || 0) / 100;
  const principalAmount = parseFloat(loan?.principal_amount) || 0;
  const MS_PER_DAY = 86400000;
  // Parse a stored trade_date as a UTC date-only timestamp. Trade dates
  // are stored as "YYYY-MM-DDTHH:MM:SS" without a timezone suffix; the
  // naive Date.parse treats them as local time, which makes
  // fmtScheduleDate (UTC components) shift one day earlier in zones
  // east of UTC. Slicing to the date portion and appending "T00:00:00Z"
  // forces UTC midnight on the booked day.
  const parseTradeDateMs = (s) => {
    if (!s) return NaN;
    return Date.parse(String(s).slice(0, 10) + "T00:00:00Z");
  };
  const accrualEndMs = accrualDate ? Date.parse(accrualDate + "T23:59:59Z") : null;
  const tradeStartMs = loan?.trade_date ? parseTradeDateMs(loan.trade_date) : null;

  // Per-row accrual aligned 1:1 with `mappings` indices; null when n/a.
  const perRowAccrued = mappings.map((m) => {
    if (m.mapping_type !== "PRINCIPAL_DISBURSE" || !m.trade_date) return null;
    const rowMs = parseTradeDateMs(m.trade_date);
    if (Number.isNaN(rowMs) || accrualEndMs == null) return null;
    const days = Math.max(0, (accrualEndMs - rowMs) / MS_PER_DAY);
    const amt = Math.abs(parseFloat(m.amount) || 0);
    return amt * rate * (days / dayBasis);
  });
  const accruedGross = perRowAccrued.reduce((s, v) => s + (v || 0), 0);

  // ─── Loan Schedule (amortization-style by principal event) ───────
  // Delegates to the shared `buildLoanScheduleRows` helper above so the
  // export modal can call the same logic. Returns one row per principal
  // segment with notional, days, accrued, netPaid, etc.
  const scheduleRows = buildLoanScheduleRows(loan, accrualDate);

  // Date formatter matching the user's "D/M/YYYY" convention for the
  // schedule table. Uses UTC components so the date doesn't shift
  // across timezones for midnight-stamped trade_dates.
  const fmtScheduleDate = (ms) => {
    if (ms == null) return "—";
    const d = new Date(ms);
    return `${d.getUTCDate()}/${d.getUTCMonth() + 1}/${d.getUTCFullYear()}`;
  };

  // ─── Hedge coverage projection (forward-looking from trade_date) ──
  // When the loan is hedged with hedged_asset == interest_asset (the
  // typical case — e.g. ETH loan hedged with ETH), the hedged_qty is
  // a buffer of interest-asset units that can cover X days of accrual.
  // Coverage span = hedged_qty / (daily accrual in interest_asset).
  // We use the booked principal as the projection baseline (max draw —
  // conservative). If outstanding changes, the date shifts.
  const isHedged = !!loan?.is_hedged;
  const hedgedQty = parseFloat(loan?.hedged_qty) || 0;
  const hedgedPrice = parseFloat(loan?.hedged_price) || 0;
  const hedgeProceedsAsset = loan?.hedge_proceeds_asset || "";
  const hedgeProceedsAmount = parseFloat(loan?.hedge_proceeds_amount) || 0;
  const hedgeMatchesInterestAsset = isHedged && loan?.hedged_asset === loan?.interest_asset;

  const dailyAccrualInterest = (() => {
    if (rate <= 0 || principalAmount <= 0) return 0;
    return principalAmount * rate / dayBasis; // interest_asset per day @ full draw
  })();

  // coverageDays: days the hedge buffer will cover, accounting for
  // interest already accrued on matured tranches and projecting the
  // remaining balance against the LIVE tranche's outstanding notional.
  //
  //   remainingHedge = hedgedQty − Σ(matured-tranche accrued)
  //   liveDaily      = liveNotional × rate / dayBasis
  //   coverageDays   = remainingHedge / liveDaily   (from live-tranche start)
  //
  // Null when we can't compute (asset mismatch or no live tranche).
  // Infinity when rate is 0 (no accrual → buffer never depletes).
  let coverageDays = null;
  let coverageEndDate = null;
  let maturedAccrued = 0;
  let coverageNotional = principalAmount;
  let remainingHedge = hedgedQty;
  if (isHedged && hedgeMatchesInterestAsset) {
    const lastRow = scheduleRows[scheduleRows.length - 1];
    const hasLiveTranche = !!lastRow && lastRow.endMs == null;
    if (hasLiveTranche) {
      maturedAccrued = scheduleRows
        .slice(0, -1)
        .reduce((s, p) => s + (p.accrued || 0), 0);
      coverageNotional = lastRow.notional;
      remainingHedge = hedgedQty - maturedAccrued;
      const liveDaily = coverageNotional * rate / dayBasis;
      if (liveDaily <= 0) {
        coverageDays = Infinity;
      } else if (remainingHedge <= 0) {
        coverageDays = 0;
      } else {
        coverageDays = remainingHedge / liveDaily;
        if (lastRow.startMs != null && Number.isFinite(coverageDays)) {
          coverageEndDate = new Date(lastRow.startMs + coverageDays * MS_PER_DAY);
        }
      }
    } else if (dailyAccrualInterest > 0) {
      // No live tranche (no schedule yet, or fully repaid). Fall back to
      // the booked-principal projection from the loan's trade_date.
      coverageDays = hedgedQty / dailyAccrualInterest;
      if (tradeStartMs != null && Number.isFinite(coverageDays)) {
        coverageEndDate = new Date(tradeStartMs + coverageDays * MS_PER_DAY);
      }
    } else {
      coverageDays = Infinity;
    }
  }

  // Accrued interest converted into the hedge_proceeds_asset using the
  // locked-in hedged_price. Useful when interest accrues in (say) ETH
  // but the operator wants the USD equivalent because that's what the
  // hedge proceeds are denominated in.
  let accruedInHedgeAsset = null;
  let accruedInHedgeProceedsAsset = null;
  if (isHedged) {
    if (hedgeMatchesInterestAsset) {
      // Same asset — hedge buffer is directly the interest currency.
      accruedInHedgeAsset = { amount: accruedGross, asset: loan.hedged_asset };
    }
    if (hedgeProceedsAsset && hedgedPrice > 0 && hedgeMatchesInterestAsset) {
      // Convert accrued (in interest_asset) to proceeds_asset by the
      // hedge price (proceeds per 1 unit of interest_asset).
      accruedInHedgeProceedsAsset = {
        amount: accruedGross * hedgedPrice,
        asset: hedgeProceedsAsset,
      };
    }
  }

  // Status pill styling reused from LoanEnquiry.
  const statusStyle = (s) => ({
    background: s === "LIVE" ? "#eef5e9" : s === "MATURED" ? "#eef0f6" : s === "CANCELLED" ? "#fff0eb" : "#f6f3ec",
    border: `1px solid ${s === "LIVE" ? "#7ea66a" : s === "MATURED" ? "#c8cde0" : s === "CANCELLED" ? "#e08a6a" : "#d9d4c7"}`,
    color: s === "LIVE" ? "#1f4a1f" : s === "MATURED" ? "#1f63ea" : s === "CANCELLED" ? "#7a1f00" : "#1f1f1f",
  });

  // Per-row mapping_type label + colour band.
  const typeBadge = (mt) => {
    const map = {
      PRINCIPAL_DISBURSE: { label: "Disburse", colour: "#1f4a1f", bg: "#eef5e9", border: "#7ea66a" },
      PRINCIPAL_REPAY:    { label: "Repay",    colour: "#7a1f00", bg: "#fff0eb", border: "#e08a6a" },
      INTEREST:           { label: "Interest", colour: "#1f63ea", bg: "#eef0f6", border: "#c8cde0" },
      COLLATERAL_POST:    { label: "Coll. Post", colour: "#5a3a1f", bg: "#f6efe4", border: "#c9b58e" },
      COLLATERAL_RELEASE: { label: "Coll. Rel.", colour: "#5a3a1f", bg: "#f6efe4", border: "#c9b58e" },
      FEE:                { label: "Fee",      colour: "#5a3a1f", bg: "#f6efe4", border: "#c9b58e" },
    };
    const e = map[mt] || { label: mt || "—", colour: "#1f1f1f", bg: "#f6f3ec", border: "#d9d4c7" };
    return (
      <span
        className="px-1.5 py-0.5 text-[10px]"
        style={{ background: e.bg, border: `1px solid ${e.border}`, color: e.colour }}
      >{e.label}</span>
    );
  };

  return (
    <div
      className="fixed inset-0 z-50 p-4 overflow-auto"
      style={{
        background: mounted ? "rgba(0,0,0,0.5)" : "rgba(0,0,0,0)",
        transition: "background 160ms ease-out",
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        className="relative max-w-7xl mx-auto"
        style={{
          background: "#f6f3ec",
          border: "1px solid #d9d4c7",
          boxShadow: "0 16px 48px rgba(0,0,0,0.3)",
          opacity: mounted ? 1 : 0,
          transform: mounted ? "translateY(0)" : "translateY(-8px)",
          transition: "opacity 160ms ease-out, transform 160ms ease-out",
          fontFamily: "'IBM Plex Mono', ui-monospace, monospace",
        }}
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="absolute z-10"
          style={{
            top: 10, right: 10, width: 32, height: 32,
            display: "flex", alignItems: "center", justifyContent: "center",
            background: "#1f1f1f", color: "#f2efe8",
            fontSize: 20, lineHeight: 1, borderRadius: 16,
            boxShadow: "0 2px 6px rgba(0,0,0,0.2)", cursor: "pointer",
          }}
        >×</button>

        {/* ─── Header ─── */}
        <div className="px-6 py-5" style={{ borderBottom: "1px solid #d9d4c7" }}>
          <div className="text-[11px] tracking-[0.25em] uppercase opacity-60">Loan Details</div>
          {/* Headline reads "MLA00000003 — 3,300 ETH LOAN FROM ECHOCREEK".
              Direction-aware: LEND → "LOAN TO X", BORROW → "LOAN FROM X". */}
          <div
            className="text-[22px] mt-1 leading-tight"
            style={{ fontFamily: "'Cormorant Garamond', 'EB Garamond', Georgia, serif" }}
          >
            {dealRef}
            {loan && (
              <>
                <span style={{ opacity: 0.5 }}>{" — "}</span>
                {/* Number rendered in IBM Plex Mono with tabular-nums so
                    digits stay vertically aligned and don't jitter as the
                    principal value changes. The serif headline keeps its
                    editorial feel for the surrounding text. */}
                <span
                  style={{
                    fontFamily: "'IBM Plex Mono', ui-monospace, monospace",
                    fontVariantNumeric: "tabular-nums",
                    fontFeatureSettings: '"tnum"',
                    fontSize: "0.92em",
                    letterSpacing: "0.005em",
                  }}
                >{fmt(loan.principal_amount)}</span>
                <span>{" "}{loan.principal_asset}</span>
                <span>{loan.direction === "LEND" ? " LOAN TO " : " LOAN FROM "}</span>
                {loan.counterparty
                  ? <span>{String(loan.counterparty).toUpperCase()}</span>
                  : <span style={{ opacity: 0.5 }}>—</span>}
              </>
            )}
          </div>
          {state?.loading && <div className="text-[11px] mt-2 opacity-60">Loading…</div>}
          {state?.error && (
            <div className="text-[12px] mt-2" style={{ color: "#7a1f00" }}>
              Error: {state.error}
            </div>
          )}
          {loan && (
            <div className="flex items-center gap-3 flex-wrap mt-3 text-[11px]" style={{ color: "#6a665c" }}>
              <span style={statusStyle(loan.status)} className="px-1.5 py-0.5 text-[10px] tracking-[0.18em] uppercase">
                {loan.status}
              </span>
              <span>{loan.loan_type}</span>
              <span style={{ opacity: 0.4 }}>·</span>
              <span>PTF {loan.portfolio_id}{loan.portfolio_name ? ` · ${loan.portfolio_name}` : ""}</span>
              <span style={{ opacity: 0.4 }}>·</span>
              <span>booked by {loan.user_id || "—"}</span>
              {loan.order_id && <>
                <span style={{ opacity: 0.4 }}>·</span>
                <span>order id <code style={{ color: "#1f1f1f" }}>{loan.order_id}</code></span>
              </>}
            </div>
          )}
        </div>

        {/* ─── Tab bar ─── */}
        <div style={{ background: "#fcfbf6", borderBottom: "1px solid #d9d4c7" }}>
          <div className="px-6 flex gap-0" role="tablist">
            {[
              { id: "details",   label: "Loan Summary",     count: null },
              { id: "schedule",  label: "Loan Schedule",    count: scheduleRows.length },
              { id: "cashflows", label: "Linked Cashflows", count: mappings.length },
            ].map((t) => {
              const isActive = activeTab === t.id;
              return (
                <button
                  key={t.id}
                  type="button"
                  role="tab"
                  aria-selected={isActive}
                  onClick={() => setActiveTab(t.id)}
                  className="px-4 py-3 text-[10px] uppercase tracking-[0.22em]"
                  style={{
                    background: "transparent",
                    border: "none",
                    borderBottom: isActive ? "2px solid #1f1f1f" : "2px solid transparent",
                    color: isActive ? "#1f1f1f" : "#6a665c",
                    cursor: "pointer",
                    marginBottom: -1,
                    fontFamily: "inherit",
                  }}
                >
                  {t.label}
                  {t.count != null && (
                    <span style={{ marginLeft: 6, opacity: 0.6 }}>· {t.count}</span>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        {/* ─── Tab: Loan Details (Contract + Principal + Hedge) ─── */}
        {activeTab === "details" && (<>
        {/* ─── Contract block — static loan terms in a key/value grid ─── */}
        {loan && (
          <div
            className="px-6 py-4"
            style={{ background: "#fcfbf6", borderBottom: "1px solid #d9d4c7" }}
          >
            <div className="text-[9px] uppercase tracking-[0.22em] mb-3" style={{ color: "#6a665c" }}>
              Contract
            </div>
            <dl className="grid grid-cols-2 sm:grid-cols-4 gap-x-6 gap-y-3 text-[12px]">
              {[
                ["Direction", loan.direction],
                ["Loan Type", loan.loan_type],
                ["Counterparty", loan.counterparty || "—"],
                ["Counterparty ID", loan.counterparty_id || "—"],
                ["Principal", `${fmt(loan.principal_amount)} ${loan.principal_asset}`],
                ["Interest Rate", `${loan.interest_rate_pa_pct || 0}% ${loan.interest_type || ""}`],
                ["WHT", loan.wht_pct == null || loan.wht_pct === "" ? "—" : `${loan.wht_pct}%`],
                ["Day Basis", `Actual/${loan.day_count_basis || 365}`],
                ["Floating Benchmark", loan.interest_type === "FLOATING" ? (loan.floating_benchmark || "—") : "—"],
                ["Collateral", loan.collateral_asset
                  ? `${fmt(loan.collateral_amount)} ${loan.collateral_asset}`
                  : "unsecured"],
                ["Hedge", loan.is_hedged
                  ? `${fmt(loan.hedged_qty)} ${loan.hedged_asset} @ ${fmt(loan.hedged_price)}`
                  : "—"],
                ["Start Date", fmtTs(loan.trade_date)],
                ["Maturity Date", loan.maturity_date ? fmtTs(loan.maturity_date) : "open-term"],
              ].map(([k, v]) => (
                <div key={k}>
                  <dt
                    className="text-[9px] uppercase tracking-[0.22em]"
                    style={{ color: "#6a665c" }}
                  >{k}</dt>
                  <dd className="text-[12px] mt-0.5 font-mono">{v}</dd>
                </div>
              ))}
            </dl>
          </div>
        )}

        {/* ─── Principal balances: Disbursed / Repaid → Outstanding ─── */}
        {loan && (
          <div className="px-6 py-4" style={{ borderBottom: "1px solid #d9d4c7" }}>
            <div className="text-[9px] uppercase tracking-[0.22em] mb-3" style={{ color: "#6a665c" }}>
              Principal · {principalAsset || "—"}
            </div>
            <div className="space-y-1.5">
              <div className="flex items-baseline justify-between text-[12px] font-mono">
                <span style={{ color: "#6a665c" }}>Disbursed</span>
                <span>{fmt(disbursed)}</span>
              </div>
              <div className="flex items-baseline justify-between text-[12px] font-mono">
                <span style={{ color: "#6a665c" }}>Repaid</span>
                <span>{fmt(repaid)}</span>
              </div>
              <div
                className="flex items-baseline justify-between text-[13px] font-mono pt-1.5 mt-1"
                style={{ borderTop: "1px solid #efece4", fontWeight: 600 }}
              >
                <span>Outstanding</span>
                <span>{fmt(outstanding)}</span>
              </div>
            </div>
          </div>
        )}

        {/* ─── Hedge panel — only when loan.is_hedged ─── */}
        {loan && isHedged && (
          <div
            className="px-6 py-4"
            style={{ background: "#fafaf6", borderBottom: "1px solid #d9d4c7" }}
          >
            <div className="flex items-baseline gap-3 mb-3">
              <div className="text-[9px] uppercase tracking-[0.22em]" style={{ color: "#6a665c" }}>
                Hedge
              </div>
            </div>
            <dl className="grid grid-cols-2 sm:grid-cols-4 gap-x-6 gap-y-3 text-[12px]">
              <div>
                <dt className="text-[9px] uppercase tracking-[0.22em]" style={{ color: "#6a665c" }}>
                  Hedged Position
                </dt>
                <dd className="text-[12px] mt-0.5 font-mono">
                  {fmt(hedgedQty)} {loan.hedged_asset} @ {fmt(hedgedPrice)}
                </dd>
              </div>
              <div>
                <dt className="text-[9px] uppercase tracking-[0.22em]" style={{ color: "#6a665c" }}>
                  Proceeds Locked
                </dt>
                <dd className="text-[12px] mt-0.5 font-mono">
                  {hedgeProceedsAmount > 0
                    ? `${fmt(hedgeProceedsAmount)} ${hedgeProceedsAsset}`
                    : "—"}
                </dd>
              </div>
              <div>
                <dt className="text-[9px] uppercase tracking-[0.22em]" style={{ color: "#6a665c" }}>
                  Accrued (hedge value)
                </dt>
                <dd className="text-[12px] mt-0.5 font-mono">
                  {accruedInHedgeProceedsAsset
                    ? `${fmt5(accruedInHedgeProceedsAsset.amount)} ${accruedInHedgeProceedsAsset.asset}`
                    : accruedInHedgeAsset
                    ? `${fmt5(accruedInHedgeAsset.amount)} ${accruedInHedgeAsset.asset}`
                    : "—"}
                </dd>
              </div>
              <div>
                <dt className="text-[9px] uppercase tracking-[0.22em]" style={{ color: "#6a665c" }}>
                  Hedge Coverage Until
                </dt>
                <dd className="text-[12px] mt-0.5 font-mono">
                  {coverageEndDate ? (
                    <>
                      <span style={{ fontWeight: 600 }}>{coverageEndDate.toISOString().slice(0, 10)}</span>
                      <span style={{ opacity: 0.65 }}> · {Math.round(coverageDays)} days</span>
                    </>
                  ) : coverageDays === Infinity ? (
                    <span style={{ opacity: 0.65 }}>indefinite (0% rate)</span>
                  ) : (
                    <span style={{ opacity: 0.65 }}>—</span>
                  )}
                </dd>
              </div>
            </dl>
            <div className="text-[10px] mt-3" style={{ color: "#6a665c" }}>
              Remaining buffer <strong>{fmt(remainingHedge)} {loan.hedged_asset}</strong>
              {" "}( initial {fmt(hedgedQty)} − {fmt(maturedAccrued)} accrued on matured tranches )
              depletes against the live tranche of
              {" "}<strong>{fmt(coverageNotional)} {principalAsset}</strong> @ {loan.interest_rate_pa_pct || 0}%.
              Further draws shorten the date; further repayments extend it.
            </div>
          </div>
        )}
        </>)}

        {/* ─── Tab: Loan Schedule (amortization-by-event) ─── */}
        {activeTab === "schedule" && (
          loan && scheduleRows.length > 0 ? (
          <div className="px-6 py-4" style={{ borderBottom: "1px solid #d9d4c7" }}>
            <div className="flex items-baseline justify-between mb-2 gap-3 flex-wrap">
              <div className="text-[10px] tracking-[0.22em] uppercase" style={{ color: "#6a665c" }}>
                Loan Schedule · {scheduleRows.length}
              </div>
              <div className="text-[10px]" style={{ color: "#9a9488", fontStyle: "italic" }}>
                One row per principal-balance segment · accrued = notional × rate × days / {dayBasis}
              </div>
            </div>
            <div className="overflow-x-auto" style={{ border: "1px solid #efece4" }}>
              <table className="w-full text-[11px]" style={{ fontFamily: "'IBM Plex Mono', ui-monospace, monospace" }}>
                <thead>
                  <tr style={{ background: "#efece4", color: "#6a665c" }}>
                    <th className="px-2 py-2 text-left whitespace-nowrap">Start Date</th>
                    <th className="px-2 py-2 text-left whitespace-nowrap">Maturity Date</th>
                    <th className="px-2 py-2 text-left whitespace-nowrap">Portfolio</th>
                    <th className="px-2 py-2 text-left whitespace-nowrap">Portfolio Name</th>
                    <th className="px-2 py-2 text-left whitespace-nowrap">Asset</th>
                    <th className="px-2 py-2 text-right whitespace-nowrap">Amount</th>
                    <th className="px-2 py-2 text-right whitespace-nowrap">Rate (USD)</th>
                    <th className="px-2 py-2 text-right whitespace-nowrap">Amount (USD)</th>
                    <th className="px-2 py-2 text-left whitespace-nowrap">Interest Calc Date</th>
                    <th className="px-2 py-2 text-right whitespace-nowrap">Interest Rate (% p.a.)</th>
                    <th className="px-2 py-2 text-left whitespace-nowrap">Interest Asset</th>
                    <th className="px-2 py-2 text-right whitespace-nowrap">Accrued Interest</th>
                    <th className="px-2 py-2 text-right whitespace-nowrap">WHT</th>
                    <th className="px-2 py-2 text-right whitespace-nowrap">Net Paid Interest</th>
                    <th className="px-2 py-2 text-left whitespace-nowrap">Loan Type</th>
                    <th className="px-2 py-2 text-left whitespace-nowrap">Counterparty</th>
                    <th className="px-2 py-2 text-left whitespace-nowrap">Comment</th>
                    <th className="px-2 py-2 text-right whitespace-nowrap">Hedged Interest</th>
                    <th className="px-2 py-2 text-right whitespace-nowrap">Hedged Price</th>
                    <th className="px-2 py-2 text-right whitespace-nowrap">Hedge USDT</th>
                    <th className="px-2 py-2 text-right whitespace-nowrap">Accrued Interest to Date</th>
                  </tr>
                </thead>
                <tbody>
                  {(() => {
                    // Running cumulative accrued interest across the schedule.
                    // Reset per-render — scheduleRows is already chronological.
                    let cumAcc = 0;
                    // Hedge buffer drain: each tranche's accrued ETH consumes
                    // the buffer in chronological order. Once depleted,
                    // subsequent tranches' Hedged Interest = 0.
                    let hedgeRemaining =
                      isHedged && hedgeMatchesInterestAsset ? hedgedQty : 0;
                    // Footer aggregates — built up during the map below.
                    let totalHedgedInterest = 0;
                    let totalHedgeUSDT = 0;
                    const dash = <span style={{ opacity: 0.4 }}>—</span>;
                    const rowEls = scheduleRows.map((p, i) => {
                      cumAcc += (p.accrued || 0);
                      // coveredEth = hedge buffer allocated to THIS row.
                      //   Matured rows: min(remaining, accrued) — buffer
                      //     drains by the period's actual accrual.
                      //   LIVE row    : entire remaining buffer — it's all
                      //     reserved for the in-flight tranche (accrued
                      //     already + future accrual until depletion).
                      // Displayed in interest_asset units so the column
                      // lines up with Accrued Interest 1:1.
                      const isLiveRow = p.endMs == null;
                      let coveredEth = 0;
                      const hedgeOn = isHedged && hedgeMatchesInterestAsset;
                      if (hedgeOn && hedgeRemaining > 0) {
                        if (isLiveRow) {
                          coveredEth = hedgeRemaining;
                          hedgeRemaining = 0;
                        } else if (p.days > 0 && (p.accrued || 0) > 0) {
                          coveredEth = Math.min(hedgeRemaining, p.accrued);
                          hedgeRemaining -= coveredEth;
                        }
                      }
                      // hedgedInterest is null only when the hedge concept
                      // doesn't apply at all; explicit 0 (e.g. exhausted)
                      // is rendered as "0" so the row stays meaningful.
                      const hedgedInterest = hedgeOn ? coveredEth : null;
                      // hedgeRemaining is the buffer left AFTER this row —
                      // surfaced in the tooltip so the user can see how
                      // much is still available.
                      const hedgeRemainingAfter = hedgeRemaining;
                      // Live tranche's "future buffer" = what's left of the
                      // covered amount once current accrued is subtracted.
                      const futureBuffer = isLiveRow
                        ? Math.max(0, coveredEth - (p.accrued || 0))
                        : 0;
                      // Footer accumulators.
                      if (hedgedInterest != null) {
                        totalHedgedInterest += hedgedInterest;
                        if (hedgedPrice > 0) {
                          totalHedgeUSDT += hedgedInterest * hedgedPrice;
                        }
                      }
                      return (
                        <tr key={i} style={{ borderTop: "1px solid #efece4" }}>
                          {/* Start Date */}
                          <td className="px-2 py-2 whitespace-nowrap" style={{ color: "#0d0d0d" }}>
                            {fmtScheduleDate(p.startMs)}
                          </td>
                          {/* Maturity Date */}
                          <td className="px-2 py-2 whitespace-nowrap">
                            {p.endMs != null ? (
                              <span style={{ color: "#0d0d0d" }}>{fmtScheduleDate(p.endMs)}</span>
                            ) : (
                              <span
                                className="px-1.5 py-0.5 text-[10px]"
                                style={{ background: "#eef5e9", border: "1px solid #7ea66a", color: "#1f4a1f" }}
                              >LIVE</span>
                            )}
                          </td>
                          {/* Portfolio */}
                          <td className="px-2 py-2 whitespace-nowrap">{loan.portfolio_id ?? "—"}</td>
                          {/* Portfolio Name */}
                          <td className="px-2 py-2 whitespace-nowrap">{loan.portfolio_name || "—"}</td>
                          {/* Asset */}
                          <td className="px-2 py-2 whitespace-nowrap">{principalAsset || "—"}</td>
                          {/* Amount */}
                          <td className="px-2 py-2 text-right whitespace-nowrap" style={{ color: "#0d0d0d" }}>
                            {fmt(p.notional)}
                          </td>
                          {/* Rate (USD) — FX placeholder */}
                          <td className="px-2 py-2 text-right whitespace-nowrap">{dash}</td>
                          {/* Amount (USD) — notional × USD rate, placeholder */}
                          <td className="px-2 py-2 text-right whitespace-nowrap">{dash}</td>
                          {/* Interest Calc Date */}
                          <td className="px-2 py-2 whitespace-nowrap" style={{ color: "#0d0d0d" }}>
                            {p.calcEndMs != null ? fmtScheduleDate(p.calcEndMs) : dash}
                          </td>
                          {/* Interest Rate P.A. (%) */}
                          <td className="px-2 py-2 text-right whitespace-nowrap" style={{ color: "#0d0d0d" }}>
                            {loan.interest_rate_pa_pct ?? 0}
                          </td>
                          {/* Interest Asset */}
                          <td className="px-2 py-2 whitespace-nowrap">{interestAsset || "—"}</td>
                          {/* Accrued Interest */}
                          <td className="px-2 py-2 text-right whitespace-nowrap" style={{ color: "#0d0d0d" }}>
                            {p.days > 0 ? (
                              <HoverTip text={`${fmt(p.notional)} × ${loan.interest_rate_pa_pct || 0}% × ${p.days}d / ${dayBasis}`}>
                                {fmt(p.accrued)}
                              </HoverTip>
                            ) : dash}
                          </td>
                          {/* WHT — accrued × wht_pct / 100. Dash when
                              wht_pct is unset on the loan. */}
                          <td className="px-2 py-2 text-right whitespace-nowrap">
                            {(() => {
                              const whtPct = parseFloat(loan?.wht_pct);
                              if (!isFinite(whtPct) || whtPct <= 0) return dash;
                              if (!(p.days > 0) || !(p.accrued > 0)) return dash;
                              const whtAmt = p.accrued * whtPct / 100;
                              return (
                                <HoverTip text={`${fmt(p.accrued)} ${interestAsset} × ${whtPct}%`}>
                                  {fmt(whtAmt)}
                                </HoverTip>
                              );
                            })()}
                          </td>
                          {/* Net Paid Interest */}
                          <td className="px-2 py-2 text-right whitespace-nowrap" style={{ color: "#0d0d0d" }}>
                            {p.netPaid > 0 ? fmt(p.netPaid) : dash}
                          </td>
                          {/* Loan Type */}
                          <td className="px-2 py-2 whitespace-nowrap">{loan.loan_type || "—"}</td>
                          {/* Counterparty */}
                          <td className="px-2 py-2 whitespace-nowrap">{loan.counterparty || "—"}</td>
                          {/* Comment — editable, auto-saved onBlur. Keyed
                              by trigger cashflow deal_ref (stable across
                              cashflow trade_date amends). If a row has no
                              triggering cashflow (synthetic-disburse
                              fallback when no PRINCIPAL_DISBURSE mapping
                              exists), the cell is disabled with a tooltip
                              prompting the user to link a cashflow first. */}
                          <td className="px-2 py-2 whitespace-nowrap">
                            {(() => {
                              const trigRef = p.triggerDealRef;
                              const noTrigger = !trigRef;
                              const saveErr = trigRef ? rowSaveErrors[trigRef] : null;
                              const restBorder = saveErr ? "#b91c1c" : "#d9d4c7";
                              const value = trigRef ? (rowComments[trigRef] ?? "") : "";
                              const tip = noTrigger
                                ? "Link a PRINCIPAL_DISBURSE cashflow to enable comments on this row"
                                : (saveErr
                                  ? `Save failed: ${saveErr}`
                                  : (value || ""));
                              return (
                                <HoverTip text={tip}>
                                  <input
                                    type="text"
                                    disabled={noTrigger}
                                    value={value}
                                    onChange={(e) => {
                                      if (!trigRef) return;
                                      setRowComments((prev) => ({
                                        ...prev,
                                        [trigRef]: e.target.value,
                                      }));
                                    }}
                                    onBlur={(e) => {
                                      e.currentTarget.style.background = "#f8f6f1";
                                      e.currentTarget.style.borderColor = restBorder;
                                      if (trigRef) saveRowComment(trigRef, p.startMs, e.target.value);
                                    }}
                                    onFocus={(e) => {
                                      e.currentTarget.style.background = "#ffffff";
                                      e.currentTarget.style.borderColor = saveErr ? "#b91c1c" : "#0d0d0d";
                                    }}
                                    placeholder={noTrigger ? "(no cashflow linked)" : "—"}
                                    className="font-mono"
                                    style={{
                                      background: noTrigger ? "#ece7dd" : "#f8f6f1",
                                      border: `1px solid ${restBorder}`,
                                      color: "#0d0d0d",
                                      fontSize: 11,
                                      padding: "2px 6px",
                                      width: 180,
                                      outline: "none",
                                      cursor: noTrigger ? "not-allowed" : "text",
                                      opacity: noTrigger ? 0.6 : 1,
                                    }}
                                  />
                                </HoverTip>
                              );
                            })()}
                          </td>
                          {/* Hedged Interest (in interest_asset).
                              Matured rows: covered = min(remaining, accrued).
                              LIVE row:     covered = entire remaining buffer
                                            (accrued so far + future reserve). */}
                          <td className="px-2 py-2 text-right whitespace-nowrap" style={{ color: "#0d0d0d" }}>
                            {hedgedInterest != null ? (
                              <HoverTip
                                text={
                                  isLiveRow
                                    ? `live tranche · entire remaining hedge buffer = ${fmt(p.accrued)} accrued + ${fmt(futureBuffer)} reserved = ${fmt(coveredEth)} ${interestAsset}`
                                    : `covered ${fmt(coveredEth)} of ${fmt(p.accrued)} ${interestAsset} accrued · buffer remaining ${fmt(hedgeRemainingAfter)} ${interestAsset}${coveredEth < p.accrued ? " — hedge exhausted on this row" : ""}`
                                }
                              >
                                {fmt(hedgedInterest)}
                              </HoverTip>
                            ) : dash}
                          </td>
                          {/* Hedged Price */}
                          <td className="px-2 py-2 text-right whitespace-nowrap" style={{ color: "#0d0d0d" }}>
                            {isHedged && hedgedPrice > 0 ? fmt(hedgedPrice) : dash}
                          </td>
                          {/* Hedge USDT = Hedged Interest × Hedged Price.
                              Per-row proceeds-asset value of the portion of
                              this tranche's interest covered by the hedge. */}
                          <td className="px-2 py-2 text-right whitespace-nowrap" style={{ color: "#0d0d0d" }}>
                            {hedgedInterest != null && hedgedPrice > 0 ? (
                              <HoverTip
                                text={`${fmt(coveredEth)} ${interestAsset} × ${fmt(hedgedPrice)} = ${fmt(coveredEth * hedgedPrice)} ${hedgeProceedsAsset || "USDT"}`}
                              >
                                {fmt(coveredEth * hedgedPrice)}
                              </HoverTip>
                            ) : dash}
                          </td>
                          {/* Acc Interest To Date = Accrued Interest ×
                              Hedged Price for this row (proceeds-asset
                              value of this period's accrual). */}
                          <td className="px-2 py-2 text-right whitespace-nowrap" style={{ color: "#0d0d0d" }}>
                            {(p.accrued || 0) > 0 && hedgedPrice > 0 ? (
                              <HoverTip text={`${fmt(p.accrued)} ${interestAsset} × ${fmt(hedgedPrice)} = ${fmt(p.accrued * hedgedPrice)} ${hedgeProceedsAsset || "USDT"}`}>
                                {fmt(p.accrued * hedgedPrice)}
                              </HoverTip>
                            ) : dash}
                          </td>
                        </tr>
                      );
                    });
                    // Final totals row — sums for Hedged Interest, Hedge USDT,
                    // and Acc Interest To Date (Σ accrued × hedged_price).
                    // 17 leading columns are blank/labelled "TOTAL".
                    const totalAccInterestToDateUSD =
                      hedgedPrice > 0 ? cumAcc * hedgedPrice : 0;
                    const totalsRow = (
                      <tr
                        key="__totals__"
                        style={{
                          borderTop: "2px solid #d9d4c7",
                          background: "#efece4",
                          fontWeight: 600,
                        }}
                      >
                        <td
                          colSpan={17}
                          className="px-2 py-2 text-right whitespace-nowrap"
                          style={{
                            color: "#6a665c",
                            letterSpacing: "0.22em",
                            fontSize: 10,
                            textTransform: "uppercase",
                          }}
                        >
                          Total
                        </td>
                        {/* 18: Hedged Interest */}
                        <td className="px-2 py-2 text-right whitespace-nowrap" style={{ color: "#0d0d0d" }}>
                          {totalHedgedInterest > 0 ? fmt(totalHedgedInterest) : dash}
                        </td>
                        {/* 19: Hedged Price — doesn't sum meaningfully */}
                        <td className="px-2 py-2 text-right whitespace-nowrap">{dash}</td>
                        {/* 20: Hedge USDT */}
                        <td className="px-2 py-2 text-right whitespace-nowrap" style={{ color: "#0d0d0d" }}>
                          {totalHedgeUSDT > 0 ? fmt(totalHedgeUSDT) : dash}
                        </td>
                        {/* 21: Acc Interest To Date */}
                        <td className="px-2 py-2 text-right whitespace-nowrap" style={{ color: "#0d0d0d" }}>
                          {totalAccInterestToDateUSD > 0 ? fmt(totalAccInterestToDateUSD) : dash}
                        </td>
                      </tr>
                    );
                    return [...rowEls, totalsRow];
                  })()}
                </tbody>
              </table>
            </div>
          </div>
          ) : (
            <div className="px-6 py-6 text-[12px]" style={{ color: "#6a665c", borderBottom: "1px solid #d9d4c7" }}>
              No schedule yet — link a PRINCIPAL_DISBURSE cashflow to this loan first.
            </div>
          )
        )}

        {/* ─── Tab: Linked Cashflows ─── */}
        {activeTab === "cashflows" && (
        <div className="px-6 py-4 max-h-[55vh] overflow-y-auto">
          <div className="flex items-center justify-between mb-2 gap-3 flex-wrap">
            <div className="text-[10px] tracking-[0.22em] uppercase" style={{ color: "#6a665c" }}>
              Linked Cashflows · {mappings.length}
            </div>
            {loan && (
              <div className="flex items-center gap-2" style={{ minWidth: 220 }}>
                <span className="text-[9px] uppercase tracking-[0.22em]" style={{ color: "#6a665c" }}>
                  Accrual Date
                </span>
                <div style={{ width: 170 }}>
                  <DatePicker
                    value={accrualDate}
                    min={loan.trade_date ? String(loan.trade_date).slice(0, 10) : undefined}
                    onChange={(v) => setAccrualDate(v || defaultAccrualDate)}
                    allowClear={false}
                  />
                </div>
              </div>
            )}
          </div>
          {!state?.loading && mappings.length === 0 && (
            <div className="text-[12px] py-4" style={{ color: "#6a665c" }}>
              No cashflows linked yet — tag a cashflow to this loan via the Cashflow form.
            </div>
          )}
          {mappings.length > 0 && (
            <table className="w-full text-[12px]">
              <thead>
                <tr style={{ background: "#efece4", color: "#6a665c" }}>
                  <th className="px-2 py-2 text-left whitespace-nowrap">Trade Date</th>
                  <th className="px-2 py-2 text-left whitespace-nowrap">Cashflow Ref</th>
                  <th className="px-2 py-2 text-left whitespace-nowrap">Type</th>
                  <th className="px-2 py-2 text-left whitespace-nowrap">Direction</th>
                  <th className="px-2 py-2 text-right whitespace-nowrap">Amount</th>
                  <th className="px-2 py-2 text-left whitespace-nowrap">Asset</th>
                  <th className="px-2 py-2 text-right whitespace-nowrap">Interest Accrued</th>
                  <th className="px-2 py-2 text-right whitespace-nowrap">Hedged Interest Accrued</th>
                  <th className="px-2 py-2 text-left whitespace-nowrap">CF Type</th>
                </tr>
              </thead>
              <tbody>
                {mappings.map((m, i) => {
                  // amount in trades_cashflow is always positive magnitude;
                  // sign comes from direction (OUTGOING → −, INCOMING → +).
                  const mag = Math.abs(parseFloat(m.amount) || 0);
                  const isOutgoing = m.direction === "OUTGOING";
                  const signed = isOutgoing ? `−${fmt(mag)}` : `+${fmt(mag)}`;
                  const acc = perRowAccrued[i];
                  return (
                    <tr key={m.counterpart_deal_ref + "/" + i} style={{ borderTop: "1px solid #efece4" }}>
                      <td className="px-2 py-2 whitespace-nowrap">
                        <HoverTip text={m.trade_date}>{fmtTs(m.trade_date)}</HoverTip>
                      </td>
                      <td className="px-2 py-2 whitespace-nowrap">
                        <button
                          type="button"
                          title="Open cashflow in form"
                          onClick={() => onCashflowSelect && onCashflowSelect(m.counterpart_deal_ref)}
                          style={{
                            background: "transparent", border: "none", padding: 0,
                            color: "#1f63ea", cursor: "pointer", font: "inherit",
                          }}
                        >{m.counterpart_deal_ref}</button>
                      </td>
                      <td className="px-2 py-2 whitespace-nowrap">{typeBadge(m.mapping_type)}</td>
                      <td className="px-2 py-2 whitespace-nowrap">{m.direction || "—"}</td>
                      <td
                        className="px-2 py-2 text-right whitespace-nowrap font-mono"
                        style={{ color: isOutgoing ? "#b91c1c" : "#047857" }}
                      >
                        {signed}
                      </td>
                      <td className="px-2 py-2 whitespace-nowrap">{m.asset || "—"}</td>
                      <td className="px-2 py-2 text-right whitespace-nowrap font-mono" style={{ color: "#0d0d0d" }}>
                        {acc != null ? (
                          <HoverTip
                            text={`${fmt(Math.abs(parseFloat(m.amount) || 0))} × ${loan?.interest_rate_pa_pct || 0}% × days(${accrualDate || "—"} − ${String(m.trade_date || "").slice(0, 10)}) / ${dayBasis}`}
                          >
                            {fmt(acc)} {interestAsset}
                          </HoverTip>
                        ) : (
                          <span style={{ opacity: 0.4 }}>—</span>
                        )}
                      </td>
                      <td className="px-2 py-2 text-right whitespace-nowrap font-mono" style={{ color: "#0d0d0d" }}>
                        {acc != null && isHedged && hedgedPrice > 0 ? (
                          <HoverTip
                            text={`${fmt(acc)} ${interestAsset} × hedged_price ${fmt(hedgedPrice)}`}
                          >
                            {fmt(acc * hedgedPrice)} {hedgeProceedsAsset}
                          </HoverTip>
                        ) : (
                          <span style={{ opacity: 0.4 }}>—</span>
                        )}
                      </td>
                      <td className="px-2 py-2 whitespace-nowrap" style={{ color: "#6a665c" }}>
                        {m.cashflow_type || "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
        )}

        {/* ─── Action footer ─── */}
        {loan && (
          <div
            className="px-6 py-3 flex items-center gap-2 justify-end"
            style={{ borderTop: "1px solid #d9d4c7", background: "#efece4" }}
          >
            <button
              type="button"
              onClick={() => onHistory && onHistory(dealRef)}
              className="px-3 py-1 text-[11px] inline-flex items-center gap-1.5"
              style={{
                background: "transparent",
                border: "1px solid #d9d4c7",
                color: "#1f1f1f",
                cursor: "pointer",
              }}
            ><History size={12} strokeWidth={1.75} /> Audit History</button>
            <button
              type="button"
              onClick={() => onBookCashflow && onBookCashflow(loan)}
              className="px-3 py-1 text-[11px]"
              style={{
                background: "transparent",
                border: "1px solid #1f63ea",
                color: "#1f63ea",
                cursor: "pointer",
              }}
              title="Open the Cashflow form pre-tagged to this loan"
            >+ Book Cashflow</button>
            <button
              type="button"
              onClick={() => onAmend && onAmend(loan)}
              className="px-3 py-1 text-[11px]"
              style={{
                background: "#1f63ea",
                border: "1px solid #1f63ea",
                color: "#ffffff",
                cursor: "pointer",
              }}
            >✎ Amend Loan</button>
          </div>
        )}
      </div>
    </div>
  );
}

// Floating bottom-right toast for success messages. Lives at the page
// root so it survives the amend modal closing (which would unmount any
// in-form feedback). Manual dismiss via × or auto-clears after 4s
// from the caller.
// Instant hover tooltip — opens on mouseenter (no native title= delay),
// uses a portal-free fixed-position bubble that follows the trigger.
// Used in the Deal Enquiry table to surface the full ISO timestamp on
// the truncated date columns and the CID on counterparty.
function HoverTip({ text, children, placement = "top" }) {
  const [pos, setPos] = useState(null); // { x, y } in viewport coords, null = hidden
  const bubbleRef = useRef(null);
  const [clampedLeft, setClampedLeft] = useState(null);
  // After the bubble mounts, measure its width and shift left if it would
  // overflow the viewport's right edge. Stays clamped to a small margin so
  // long tooltips (e.g. accrual formulas) never escape the visible area.
  useLayoutEffect(() => {
    if (!pos || !bubbleRef.current) {
      setClampedLeft(null);
      return;
    }
    const w = bubbleRef.current.offsetWidth;
    const vw = window.innerWidth;
    const MARGIN = 8;
    let x = pos.x;
    if (x + w > vw - MARGIN) x = Math.max(MARGIN, vw - w - MARGIN);
    setClampedLeft(x);
  }, [pos, text]);
  if (!text) return children;
  const isBottom = placement === "bottom";
  // Portal the bubble into document.body so it escapes any transformed
  // ancestor (modals slide-in via translateY would otherwise become the
  // containing block for a fixed-positioned descendant, collapsing the
  // bubble to a sliver). Anchored to the viewport directly.
  const bubble = pos
    ? createPortal(
        <span
          ref={bubbleRef}
          style={{
            position: "fixed",
            left: clampedLeft != null ? clampedLeft : pos.x,
            top: isBottom ? pos.y + 4 : pos.y - 4,
            transform: isBottom ? "none" : "translateY(-100%)",
            background: "#1f1f1f",
            color: "#f2efe8",
            fontSize: 11,
            lineHeight: 1.35,
            padding: "4px 8px",
            maxWidth: "min(420px, calc(100vw - 16px))",
            whiteSpace: "normal",
            wordBreak: "break-word",
            borderRadius: 3,
            boxShadow: "0 4px 12px rgba(0,0,0,0.25)",
            pointerEvents: "none",
            zIndex: 1000,
            fontFamily: "'IBM Plex Mono', ui-monospace, monospace",
            // Pre-measurement: render invisible to avoid a one-frame flash
            // at the unclamped position before useLayoutEffect runs.
            visibility: clampedLeft != null ? "visible" : "hidden",
          }}
        >{text}</span>,
        document.body
      )
    : null;
  return (
    <span
      style={{ display: "inline-block" }}
      onMouseEnter={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        setPos({ x: r.left, y: isBottom ? r.bottom : r.top });
      }}
      onMouseLeave={() => { setPos(null); setClampedLeft(null); }}
    >
      {children}
      {bubble}
    </span>
  );
}

function FloatingToast({ toast, onDismiss }) {
  // Fade-in on mount via two-frame mount flag.
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    if (!toast) {
      setMounted(false);
      return;
    }
    const id = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(id);
  }, [toast]);

  if (!toast) return null;
  return (
    <div
      className="fixed bottom-6 right-6 z-50 px-4 py-3 flex items-center gap-3 text-[12px]"
      style={{
        background: "#1f3a1f",
        color: "#e8f5e2",
        border: "1px solid #2e5a2e",
        boxShadow: "0 8px 24px rgba(0,0,0,0.25)",
        fontFamily: "'IBM Plex Mono', ui-monospace, monospace",
        opacity: mounted ? 1 : 0,
        transform: mounted ? "translateY(0)" : "translateY(8px)",
        transition: "opacity 160ms ease-out, transform 160ms ease-out",
        maxWidth: 360,
      }}
    >
      <span>✓ {toast.message}</span>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss"
        className="opacity-70 hover:opacity-100"
        style={{ fontSize: 16, lineHeight: 1, background: "transparent", color: "inherit" }}
      >×</button>
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

// Walk back one calendar day at a time, skipping Sat (6) and Sun (0).
// Returns the previous business day relative to `d`.
function prevBusinessDay(d) {
  const x = new Date(d);
  do {
    x.setDate(x.getDate() - 1);
  } while (x.getDay() === 0 || x.getDay() === 6);
  return x;
}

function fmtDateInput(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// ─── TradeBookingsExportModal — date + portfolio filter popup ─────────
// Triggered from the Deal Enquiry "↓ TRADE BOOKINGS" button. Opens with
// from = previous business day, to = today, all portfolios pre-selected.
// Hits GET /api/exports/blotter.csv with the chosen filters; downloads
// via transient <a download> click. Errors surface to the parent's
// banner via `onError`.
function TradeBookingsExportModal({ open, onClose, onError }) {
  const computeDefaults = () => {
    // T = yesterday's calendar date (i.e. the most recent day whose
    // trades are fully booked). T-1 = previous business day before T,
    // skipping weekends. So on Mon 25 May 2026: To = Sun 24 May,
    // From = Fri 22 May.
    const t = new Date();
    t.setDate(t.getDate() - 1);
    return {
      from: fmtDateInput(prevBusinessDay(t)),
      to: fmtDateInput(t),
      portfolios: PORTFOLIOS.map((p) => String(p.number)),
    };
  };

  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [portfolios, setPortfolios] = useState([]);
  const [portfoliosExpanded, setPortfoliosExpanded] = useState(false);
  const [downloading, setDownloading] = useState(false);

  // Re-init defaults each time the modal opens so a closed-then-reopened
  // modal doesn't carry over the user's last edit. Recomputes today/T-1
  // so the date band tracks the calendar as time passes.
  useEffect(() => {
    if (!open) return;
    const d = computeDefaults();
    setFrom(d.from);
    setTo(d.to);
    setPortfolios(d.portfolios);
    setPortfoliosExpanded(false);
  }, [open]);

  const doDownload = useCallback(async () => {
    if (downloading) return;
    setDownloading(true);
    try {
      const qs = new URLSearchParams();
      qs.set("type", "all");
      if (from) qs.set("from", from);
      if (to) qs.set("to", to);
      portfolios.forEach((p) => qs.append("portfolio", p));
      const probe = await api(`/api/exports/blotter.csv?${qs.toString()}`,
        { method: "HEAD" });
      if (!probe.ok) {
        throw new Error(`HTTP ${probe.status}`);
      }
      const a = document.createElement("a");
      a.href = `/api/exports/blotter.csv?${qs.toString()}`;
      a.rel = "noopener";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      onClose();
    } catch (e) {
      onError(`Trade Bookings download failed: ${String(e.message || e)}`);
    } finally {
      setDownloading(false);
    }
  }, [from, to, portfolios, downloading, onClose, onError]);

  const dateInputStyle = {
    fontFamily: "'IBM Plex Mono', ui-monospace, monospace",
    fontSize: 12,
    padding: "6px 8px",
    border: "1px solid #d9d4c7",
    background: "#ffffff",
    color: "#0d0d0d",
  };

  return (
    <ModalShell open={open} onClose={onClose}>
      <div style={{ padding: "28px 32px", maxWidth: 720 }}>
        <div
          className="text-[22px]"
          style={{
            fontFamily: "'Cormorant Garamond', 'EB Garamond', Georgia, serif",
            marginBottom: 18,
          }}
        >Download Trade Bookings</div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            columnGap: 16,
            marginBottom: 18,
          }}
        >
          <label
            className="flex flex-col gap-1 text-[10px] tracking-[0.18em] uppercase"
            style={{ color: "#6a665c" }}
          >
            <span>Trade Date From</span>
            <input
              type="date"
              value={from}
              onChange={(e) => setFrom(e.target.value)}
              style={dateInputStyle}
            />
          </label>
          <label
            className="flex flex-col gap-1 text-[10px] tracking-[0.18em] uppercase"
            style={{ color: "#6a665c" }}
          >
            <span>Trade Date To</span>
            <input
              type="date"
              value={to}
              onChange={(e) => setTo(e.target.value)}
              style={dateInputStyle}
            />
          </label>
        </div>

        <div
          className="flex flex-col gap-1 text-[10px] tracking-[0.18em] uppercase"
          style={{ color: "#6a665c", marginBottom: 18 }}
        >
          <div className="flex items-center justify-between" style={{ minHeight: 18 }}>
            <span>Portfolios</span>
            {portfolios.length > 0 && (
              <button
                type="button"
                onClick={() => setPortfoliosExpanded((v) => !v)}
                className="text-[10px] tracking-[0.18em] uppercase"
                style={{
                  background: "transparent",
                  border: "none",
                  color: "#6a665c",
                  cursor: "pointer",
                  padding: 0,
                }}
              >
                {portfoliosExpanded
                  ? `▾ Hide selected (${portfolios.length})`
                  : `▸ Show selected (${portfolios.length})`}
              </button>
            )}
          </div>
          <Select
            value=""
            onChange={(e) => {
              const v = e.target.value;
              if (!v) return;
              if (portfolios.includes(v)) return;
              setPortfolios([...portfolios, v]);
            }}
          >
            <option value="">
              {portfolios.length === 0
                ? "— Add portfolio —"
                : `+ Add another (${portfolios.length} selected)`}
            </option>
            {PORTFOLIOS.filter((p) => !portfolios.includes(String(p.number))).map((p) => (
              <option key={p.number} value={String(p.number)}>
                {p.number} — {p.name}
              </option>
            ))}
          </Select>
          {portfolios.length > 0 && portfoliosExpanded && (
            <div className="flex flex-wrap gap-1 mt-1.5">
              {portfolios.map((num) => {
                const p = PORTFOLIOS.find((pp) => String(pp.number) === num);
                const label = p ? `${p.number} — ${p.name.split(" - ").pop()}` : num;
                return (
                  <span
                    key={num}
                    className="inline-flex items-center gap-1 text-[10px] tracking-[0.12em] px-2 py-0.5"
                    style={{
                      background: "#ffffff",
                      color: "#0d0d0d",
                      border: "1px solid #d4cfc2",
                      textTransform: "none",
                    }}
                    title={label}
                  >
                    {label}
                    <button
                      type="button"
                      aria-label={`Remove ${num}`}
                      onClick={() =>
                        setPortfolios(portfolios.filter((x) => x !== num))
                      }
                      style={{
                        background: "transparent",
                        border: "none",
                        cursor: "pointer",
                        color: "#a39e90",
                        fontSize: 12,
                        lineHeight: 1,
                        padding: 0,
                      }}
                    >×</button>
                  </span>
                );
              })}
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2" style={{ marginTop: 24 }}>
          <button
            type="button"
            onClick={onClose}
            disabled={downloading}
            className="px-3 py-1.5 text-[10px] tracking-[0.22em] uppercase"
            style={{
              background: "transparent",
              color: downloading ? "#cdc8bb" : "#1f1f1f",
              border: "1px solid #d9d4c7",
              cursor: downloading ? "not-allowed" : "pointer",
            }}
          >Cancel</button>
          <button
            type="button"
            onClick={doDownload}
            disabled={downloading}
            className="px-3 py-1.5 text-[10px] tracking-[0.22em] uppercase"
            style={{
              background: downloading ? "#cdc8bb" : "#1f1f1f",
              color: "#f2efe8",
              border: "1px solid #1f1f1f",
              cursor: downloading ? "wait" : "pointer",
            }}
          >{downloading ? "Preparing…" : "Download"}</button>
        </div>
      </div>
    </ModalShell>
  );
}

// One-line human summary of a cashflow row for the Deal Enquiry "Details"
// column. All caps; thousands-separators on the amount. Examples:
//   IPF:     "PTF 8888 TREASURY FUNDS PTF 8041 CENTRAL RISK BOOK 1,000 USDC"
//   non-IPF: "PTF 8888 RECEIVED 10 1INCH INTEREST INCOME"
// The counterparty portfolio name isn't stored on the row (only `counterparty`
// = the CP portfolio number under IPF), so we look it up in PORTFOLIOS.
// Compact timestamp formatter for table cells. ISO "2026-05-16T06:10:00+00:00"
// → "2026-05-16 06:10". Falls back to em-dash on null/empty.
function fmtTs(iso, len = 16) {
  return iso ? String(iso).replace("T", " ").slice(0, len) : "—";
}

// Forward-looking projection of the interest-hedge coverage end date.
// Same formula as the LoanScheduleModal hedge panel — shared so the modal
// and the LoanEnquiry grid can't drift.
//
// Inputs are read off a trades_loan row (snake_case fields straight from the
// API). Returns one of:
//   { status: "NONE"     }   – not hedged / no data / asset mismatch
//   { status: "INFINITE" }   – hedged but rate is 0 (buffer never depletes)
//   { status: "PROJECTED", endDate: Date } – endDate computed
function projectHedgeCoverage(row) {
  if (!row?.is_hedged) return { status: "NONE" };
  if (row.hedged_asset && row.interest_asset && row.hedged_asset !== row.interest_asset) {
    return { status: "NONE" }; // legacy mismatch — can't project
  }
  const principal = parseFloat(row.principal_amount) || 0;
  const ratePct = parseFloat(row.interest_rate_pa_pct);
  const rate = (isFinite(ratePct) ? ratePct : 0) / 100;
  const dayBasis = parseInt(row.day_count_basis, 10) || 365;
  const qty = parseFloat(row.hedged_qty) || 0;
  const startMs = row.trade_date ? Date.parse(row.trade_date) : NaN;
  if (!Number.isFinite(startMs) || qty <= 0 || principal <= 0) {
    return { status: "NONE" };
  }
  if (rate <= 0) return { status: "INFINITE" };
  const dailyAccrual = (principal * rate) / dayBasis;
  if (dailyAccrual <= 0) return { status: "INFINITE" };
  const days = qty / dailyAccrual;
  return { status: "PROJECTED", endDate: new Date(startMs + days * 86400000) };
}

// Per-row summary of mapped counterparts (the other side of the join).
// Loan rows expose how many cashflows linked + an aggregate; cashflow
// rows expose the linked loan ref(s). Returns "" when no mappings.
function summarizeMappings(r) {
  const m = r?.mappings;
  if (!Array.isArray(m) || m.length === 0) return "";
  if (r.txn_type === "LOAN") {
    // Sum signed cashflow amounts grouped by mapping_type. Direction
    // sign on cashflows is already on amount, so simple sum works.
    const total = m.reduce((s, x) => s + (parseFloat(x.amount) || 0), 0);
    const sign = total >= 0 ? "+" : "";
    return `↗ ${m.length} cashflow${m.length === 1 ? "" : "s"} · ${sign}${total.toLocaleString("en-US", { maximumFractionDigits: 5 })}`;
  }
  // Cashflow side — just list the loan refs.
  if (m.length === 1) return `↗ ${m[0].counterpart_deal_ref}`;
  return `↗ ${m[0].counterpart_deal_ref} + ${m.length - 1} more`;
}

function summarizeDeal(r) {
  if (!r) return "";
  if (r.txn_type === "LOAN") {
    const verb = r.direction === "BORROW" ? "BORROWED" : "LENT";
    const principal = Math.abs(parseFloat(r.principal_amount) || 0);
    const fmtAmt = principal.toLocaleString("en-US", { maximumFractionDigits: 5 });
    const join = (parts) => parts.filter((p) => p && String(p).trim()).join(" ");
    return join([
      "PTF", r.portfolio_id, verb,
      fmtAmt, (r.principal_asset || "").toUpperCase(),
      "@", `${r.interest_rate_pa_pct || 0}%`, (r.interest_type || "").toLowerCase(),
      r.counterparty ? `from ${String(r.counterparty).toUpperCase()}` : "",
    ]);
  }
  if (r.txn_type === "SPOT") {
    const baseAmt = Math.abs(parseFloat(r.base_amount) || 0);
    const fmtBase = baseAmt.toLocaleString("en-US", { maximumFractionDigits: 18 });
    const baseAsset = (r.base_asset || "").toUpperCase();
    const priceNum = Math.abs(parseFloat(r.price) || 0);
    const fmtPrice = priceNum.toLocaleString("en-US", { maximumFractionDigits: 18 });
    const quoteAsset = (r.quote_asset || "").toUpperCase();
    const join = (parts) => parts.filter((p) => p && String(p).trim()).join(" ");
    const head = join([
      "PTF", r.portfolio_id, r.direction,
      fmtBase, baseAsset,
      "@", fmtPrice, quoteAsset,
    ]);
    const feeAmt = parseFloat(r.fee_amount) || 0;
    const feeAsset = (r.fee_asset || "").toUpperCase();
    if (feeAmt === 0 || !feeAsset) return head;
    const fmtFee = Math.abs(feeAmt).toLocaleString("en-US", { maximumFractionDigits: 18 });
    return `${head}, fee ${fmtFee} ${feeAsset}`;
  }
  if (r.txn_type !== "CASHFLOW") return r?.deal_ref || "";
  const shortPtfName = (n) => (n ? String(n).split(" - ").pop().trim().toUpperCase() : "");
  const lookupPtfName = (num) =>
    PORTFOLIOS.find((p) => String(p.number) === String(num))?.name || "";
  const amount = Math.abs(parseFloat(r.amount) || 0);
  // Up to 18 decimals (table is NUMERIC(36,18)); trailing zeros collapsed by
  // maximumFractionDigits. Locale "en-US" pins the thousands separator to ",".
  const fmtAmt = amount.toLocaleString("en-US", { maximumFractionDigits: 18 });
  const asset = (r.asset || "").toUpperCase();
  const join = (parts) => parts.filter((p) => p && String(p).trim()).join(" ");

  if (r.cashflow_type === "INTER PTF FUNDING") {
    let senderId, senderShort, receiverId, receiverShort;
    if (r.direction === "OUTGOING") {
      senderId = r.portfolio_id;
      senderShort = shortPtfName(r.portfolio_name);
      receiverId = r.counterparty;
      receiverShort = shortPtfName(lookupPtfName(r.counterparty));
    } else {
      senderId = r.counterparty;
      senderShort = shortPtfName(lookupPtfName(r.counterparty));
      receiverId = r.portfolio_id;
      receiverShort = shortPtfName(r.portfolio_name);
    }
    return join([
      "PTF", senderId, senderShort,
      "FUNDS",
      "PTF", receiverId, receiverShort,
      fmtAmt, asset,
    ]);
  }

  const verb = r.direction === "INCOMING" ? "RECEIVED" : "PAID";
  return join([
    "PTF", r.portfolio_id,
    verb,
    fmtAmt, asset,
    (r.cashflow_type || "").toUpperCase(),
  ]);
}

// Status styles reused from the row pills below. TRADE_STATUSES /
// LOAN_STATUSES are already declared at the top of the file alongside
// the form-level lifecycle definitions; we just attach palettes here.
const CASHFLOW_STATUS_STYLES = {
  PENDING:   { bg: "#fcf6e8", border: "#d6c694", color: "#7a5a00" },
  CONFIRMED: { bg: "#eef0f6", border: "#c8cde0", color: "#1f63ea" },
  PROCESSED: { bg: "#eaf2ee", border: "#a3c4ad", color: "#22593c" },
  SETTLED:   { bg: "#eef5e9", border: "#7ea66a", color: "#1f4a1f" },
  CANCELLED: { bg: "#fff0eb", border: "#e08a6a", color: "#7a1f00" },
};
const LOAN_STATUS_STYLES = {
  LIVE:      { bg: "#eef5e9", border: "#7ea66a", color: "#1f4a1f" },
  MATURED:   { bg: "#eef0f6", border: "#c8cde0", color: "#1f63ea" },
  CANCELLED: { bg: "#fff0eb", border: "#e08a6a", color: "#7a1f00" },
};

// ─── CSV export helpers ───────────────────────────────────────────────
// columns: [{ header, key } | { header, get(row) }]. `get` lets us derive
// values (e.g. Month Year from trade_date). RFC4180 quoting. UTF-8 BOM so
// Excel renders non-ASCII correctly.
function csvEscape(v) {
  if (v == null) return "";
  let s = String(v);
  if (/[",\n\r]/.test(s)) s = `"${s.replace(/"/g, '""')}"`;
  return s;
}
function rowsToCsv(rows, columns) {
  const head = columns.map((c) => csvEscape(c.header)).join(",");
  const body = rows.map((r) =>
    columns
      .map((c) => csvEscape(typeof c.get === "function" ? c.get(r) : r[c.key]))
      .join(",")
  );
  return [head, ...body].join("\n");
}
function downloadCsv(filename, csv) {
  const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
const _CSV_MONTH_NAMES = ["January","February","March","April","May","June","July","August","September","October","November","December"];
function fmtMonthYearUtc(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${_CSV_MONTH_NAMES[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}
// Today as YYYY-MM-DD in local time — used in CSV filenames.
function todayStampLocal() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

// Explicit column sets so CSV layout stays stable. Audit-schema columns
// (asset/amount/fee_asset/fee_amount, Month Year) are emitted even if the
// table doesn't render them inline.
const DEAL_CSV_COLUMNS = [
  { header: "Updated Date",       key: "effective_start" },
  { header: "Deal Reference",     key: "deal_ref" },
  { header: "Deal Type",          key: "txn_type" },
  { header: "Portfolio ID",       key: "portfolio_id" },
  { header: "Portfolio Name",     key: "portfolio_name" },
  { header: "Counterparty",       key: "counterparty" },
  { header: "Counterparty ID",    key: "counterparty_id" },
  { header: "Direction",          key: "direction" },
  { header: "Cashflow Type",      key: "cashflow_type" },
  { header: "Loan Type",          key: "loan_type" },
  { header: "Asset",              key: "asset" },
  { header: "Amount",             key: "amount" },
  { header: "Fee Asset",          key: "fee_asset" },
  { header: "Fee Amount",         key: "fee_amount" },
  { header: "Base Asset",         key: "base_asset" },
  { header: "Quote Asset",        key: "quote_asset" },
  { header: "Trade Date",         key: "trade_date" },
  { header: "Value Date",         key: "value_date" },
  { header: "Maturity Date",      key: "maturity_date" },
  { header: "Account",            key: "account" },
  { header: "Status",             key: "status" },
  { header: "Month Year",         get: (r) => fmtMonthYearUtc(r.trade_date) },
  { header: "Linked Deal Refs",   get: (r) => (r.mappings || []).map((m) => m.counterpart_deal_ref).filter(Boolean).join("; ") },
];
const LOAN_CSV_COLUMNS = [
  { header: "Input Date",         get: (r) => r.first_effective_start || r.effective_start || "" },
  { header: "Deal Reference",     key: "deal_ref" },
  { header: "Direction",          key: "direction" },
  { header: "Loan Type",          key: "loan_type" },
  { header: "Portfolio ID",       key: "portfolio_id" },
  { header: "Portfolio Name",     key: "portfolio_name" },
  { header: "Counterparty",       key: "counterparty" },
  { header: "Counterparty ID",    key: "counterparty_id" },
  { header: "Principal Asset",    key: "principal_asset" },
  { header: "Principal Amount",   key: "principal_amount" },
  { header: "Interest Rate %pa",  key: "interest_rate_pa_pct" },
  { header: "Interest Type",      key: "interest_type" },
  { header: "Interest Asset",     key: "interest_asset" },
  { header: "Trade Date",         key: "trade_date" },
  { header: "Maturity Date",      key: "maturity_date" },
  { header: "Is Hedged",          get: (r) => (r.is_hedged ? "Y" : "N") },
  { header: "Hedged Qty",         key: "hedged_qty" },
  { header: "Hedged Asset",       key: "hedged_asset" },
  { header: "Status",             key: "status" },
];

// Page-size options for the enquiry tables — used by both DealEnquiry and
// LoanEnquiry. 50 is the default; bump higher for power-users scanning a
// large window without paging.
const ENQUIRY_PAGE_SIZES = [25, 50, 100, 200];

// Shared pagination footer for the enquiry tables. Renders row range +
// page-size picker on the left, Prev/Next + page indicator on the right.
function EnquiryPaginationBar({
  page, totalPages, pageSize, setPage, setPageSize,
  pageStart, pageEnd, totalRows, BB,
}) {
  const canPrev = page > 1;
  const canNext = page < totalPages;
  return (
    <div
      className="flex items-center justify-between flex-wrap gap-2"
      style={{
        marginTop: 8,
        padding: "8px 12px",
        border: `1px solid ${BB?.border || "#d9d4c7"}`,
        background: "#ffffff",
        fontFamily: "'IBM Plex Mono', ui-monospace, monospace",
        fontSize: 11,
        color: "#6a665c",
      }}
    >
      <div className="flex items-center gap-3">
        <span>
          {totalRows === 0 ? "No rows" : `${pageStart}–${pageEnd} of ${totalRows}`}
        </span>
        <span style={{ color: "#a39e90" }}>·</span>
        <label className="flex items-center gap-1.5 text-[10px] tracking-[0.18em] uppercase">
          <span>Page size</span>
          <select
            value={pageSize}
            onChange={(e) => setPageSize(Number(e.target.value))}
            style={{
              fontFamily: "inherit",
              fontSize: 11,
              padding: "2px 4px",
              border: "1px solid #d9d4c7",
              background: "#ffffff",
              color: "#1f1f1f",
            }}
          >
            {ENQUIRY_PAGE_SIZES.map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </label>
      </div>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setPage((p) => Math.max(1, p - 1))}
          disabled={!canPrev}
          className="text-[10px] tracking-[0.22em] uppercase px-2 py-1 transition-colors"
          style={{
            background: "transparent",
            border: `1px solid ${canPrev ? "#d9d4c7" : "#ece7dd"}`,
            color: canPrev ? "#1f1f1f" : "#cdc8bb",
            cursor: canPrev ? "pointer" : "not-allowed",
          }}
        >← Prev</button>
        <span
          className="text-[10px] tracking-[0.18em] uppercase"
          style={{ color: "#6a665c", minWidth: 80, textAlign: "center" }}
        >
          Page {page} / {totalPages}
        </span>
        <button
          type="button"
          onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
          disabled={!canNext}
          className="text-[10px] tracking-[0.22em] uppercase px-2 py-1 transition-colors"
          style={{
            background: "transparent",
            border: `1px solid ${canNext ? "#d9d4c7" : "#ece7dd"}`,
            color: canNext ? "#1f1f1f" : "#cdc8bb",
            cursor: canNext ? "pointer" : "not-allowed",
          }}
        >Next →</button>
      </div>
    </div>
  );
}

const DEAL_ENQUIRY_INITIAL_FILTERS = {
  trade_date_from: "",
  trade_date_to: "",
  value_date_from: "",
  value_date_to: "",
  portfolios: [],
  base_asset: "",
  quote_asset: "",
  deal_ref: "",
  // Default = all-except-CANCELLED (lifecycle-active rows).
  statuses: TRADE_STATUSES.filter((s) => s !== "CANCELLED"),
};

// Deep-equal compare for INITIAL_FILTERS vs current filters — drives
// the "Clear" button's enabled state. Array fields use sorted equality
// so reordered status toggles don't falsely register as a deviation.
function filtersDifferFromDefault(filters, initial) {
  for (const k of Object.keys(initial)) {
    const a = filters[k], b = initial[k];
    if (Array.isArray(a) && Array.isArray(b)) {
      if (a.length !== b.length) return true;
      const sa = [...a].sort(), sb = [...b].sort();
      for (let i = 0; i < sa.length; i++) if (sa[i] !== sb[i]) return true;
    } else if (a !== b) {
      return true;
    }
  }
  return false;
}

function DealEnquiry({ onSelect, onHistory, onMappingClick, BB, refreshSignal }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [lastFetchedAt, setLastFetchedAt] = useState(null);
  const [filters, setFilters] = useState(DEAL_ENQUIRY_INITIAL_FILTERS);
  const setFilter = (k, v) => setFilters((f) => ({ ...f, [k]: v }));
  const clearFilters = () => setFilters(DEAL_ENQUIRY_INITIAL_FILTERS);
  const filtersActive = filtersDifferFromDefault(filters, DEAL_ENQUIRY_INITIAL_FILTERS);
  const hasDateFilter = !!(filters.trade_date_from || filters.trade_date_to || filters.value_date_from || filters.value_date_to);
  const [showDates, setShowDates] = useState(false);
  // Pagination — page is 1-indexed; resets to 1 whenever filters change.
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  useEffect(() => { setPage(1); }, [filters, pageSize]);

  // Cashflow rows expose `asset` / `fee_asset`; once SPOT rows ship they'll
  // expose `base_asset` / `quote_asset`. Filter on whichever the row has.
  // Text filters accept comma-separated tokens — any token match passes (OR).
  const filteredRows = useMemo(() => {
    const tokens = (s) =>
      String(s || "")
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);
    const baseTokens = tokens(filters.base_asset).map((t) => t.toUpperCase());
    const quoteTokens = tokens(filters.quote_asset).map((t) => t.toUpperCase());
    const refTokens = tokens(filters.deal_ref).map((t) => t.toLowerCase());
    const filtered = rows.filter((r) => {
      if (refTokens.length > 0) {
        const cand = String(r.deal_ref || "").toLowerCase();
        if (!refTokens.some((t) => cand.includes(t))) return false;
      }
      if (filters.portfolios.length > 0 && !filters.portfolios.includes(String(r.portfolio_id || ""))) {
        return false;
      }
      if (filters.statuses.length > 0 && !filters.statuses.includes(String(r.status || ""))) {
        return false;
      }
      if (baseTokens.length > 0) {
        const cand = String(r.asset || r.base_asset || "").toUpperCase();
        if (!baseTokens.includes(cand)) return false;
      }
      if (quoteTokens.length > 0) {
        const cand = String(r.quote_asset || r.fee_asset || "").toUpperCase();
        if (!quoteTokens.includes(cand)) return false;
      }
      // Compare on full timestamp ("YYYY-MM-DDTHH:MM:SS") since the
      // Deal Enquiry filter is datetime. Row's stored trade_date is an
      // ISO string with TZ suffix — slice to 19 chars to strip the TZ
      // so the lexicographic compare is over the same shape on both
      // sides. Filter values come from DateTimePicker24 already in the
      // 19-char canonical form.
      const td = String(r.trade_date || "").slice(0, 19);
      if (filters.trade_date_from && td && td < filters.trade_date_from) return false;
      if (filters.trade_date_to && td && td > filters.trade_date_to) return false;
      // Loan rows store the maturity in `maturity_date`; cashflow uses
      // `value_date`. Treat them symmetrically for the Value-Date filter.
      const vd = String(r.value_date || r.maturity_date || "").slice(0, 19);
      if (filters.value_date_from && vd && vd < filters.value_date_from) return false;
      if (filters.value_date_to && vd && vd > filters.value_date_to) return false;
      return true;
    });
    // Sort by Updated Date (effective_start) latest → earliest. The DB
    // already orders by trade_date DESC, but the table now leads with
    // Updated Date so we re-sort here to match what the user sees.
    return [...filtered].sort((a, b) => {
      const ax = String(a.effective_start || "");
      const bx = String(b.effective_start || "");
      // String compare works on ISO 8601 timestamps; descending.
      if (ax < bx) return 1;
      if (ax > bx) return -1;
      return 0;
    });
  }, [rows, filters]);

  const totalRows = filteredRows.length;
  const totalPages = Math.max(1, Math.ceil(totalRows / pageSize));
  // Clamp page if filteredRows shrinks below current page window.
  useEffect(() => { if (page > totalPages) setPage(totalPages); }, [page, totalPages]);
  const pagedRows = useMemo(
    () => filteredRows.slice((page - 1) * pageSize, page * pageSize),
    [filteredRows, page, pageSize]
  );
  const pageStart = totalRows === 0 ? 0 : (page - 1) * pageSize + 1;
  const pageEnd = Math.min(page * pageSize, totalRows);

  const exportCsv = useCallback(() => {
    const csv = rowsToCsv(filteredRows, DEAL_CSV_COLUMNS);
    downloadCsv(`deal-enquiry-${todayStampLocal()}.csv`, csv);
  }, [filteredRows]);

  const [showTradeBookingsModal, setShowTradeBookingsModal] = useState(false);

  const fetchRecent = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Loans live in their own LoanEnquiry view; Deal Enquiry merges
      // cashflow + spot rows (re-sorted by effective_start desc in
      // filteredRows). The `mappings` array on each cashflow still
      // shows linked loans inline (chip in the Details column).
      const [cfRes, spotRes] = await Promise.all([
        api("/api/cashflow/recent?limit=20").then((r) => r.json()),
        api("/api/spot/recent?limit=20").then((r) => r.json()),
      ]);
      if (!cfRes.ok) throw new Error(cfRes.error || "cashflow fetch failed");
      if (!spotRes.ok) throw new Error(spotRes.error || "spot fetch failed");
      setRows([...(cfRes.rows || []), ...(spotRes.rows || [])]);
      setLastFetchedAt(new Date());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  // Refetch on mount and any time the parent bumps refreshSignal (e.g.
  // after a successful insert/amend) so the table reflects the latest data.
  useEffect(() => { fetchRecent(); }, [fetchRecent, refreshSignal]);

  return (
    <div className="px-5 pt-4 pb-8">
      <div className="mb-3">
        <div
          className="text-[22px]"
          style={{ fontFamily: "'Cormorant Garamond', 'EB Garamond', Georgia, serif" }}
        >Deal Enquiry</div>
      </div>

      {error && (
        <div
          className="px-3 py-2 mb-3 text-[12px]"
          style={{ background: "#fff0eb", border: "1px solid #e08a6a", color: "#7a1f00" }}
        >Error: {error}</div>
      )}

      {/* ─── Filters — compact white card. Portfolio/Status/Search live
          inline; date pickers tuck behind a "Date filters" toggle so the
          card stays small when dates aren't being filtered. ─── */}
      <div
        className="mb-3"
        style={{
          background: "#ffffff",
          border: "1px solid #e9e7e2",
          fontFamily: "'IBM Plex Mono', ui-monospace, monospace",
        }}
      >
        {/* Header strip — label, date toggle, clear all */}
        <div
          className="flex items-center justify-between"
          style={{ padding: "8px 16px", borderBottom: "1px solid #f3f1ec" }}
        >
          <div className="flex items-baseline gap-2.5">
            <span
              className="text-[10px] tracking-[0.28em] uppercase"
              style={{ color: "#8a857a", fontWeight: 500 }}
            >Filters</span>
            {filtersActive && (
              <span
                className="text-[9px] tracking-[0.22em] uppercase"
                style={{ color: "#b45309" }}
              >· Active</span>
            )}
          </div>
          <div className="flex items-center gap-5">
            <button
              type="button"
              onClick={() => setShowDates((s) => !s)}
              className="text-[10px] tracking-[0.22em] uppercase transition-colors"
              style={{
                background: "transparent",
                color: "#1f1f1f",
                border: "none",
                padding: "4px 0",
                cursor: "pointer",
              }}
            >
              {showDates ? "− Hide dates" : "+ Date filters"}
              {!showDates && hasDateFilter && (
                <span style={{ color: "#b45309", marginLeft: 4 }}>· Active</span>
              )}
            </button>
            <button
              type="button"
              onClick={clearFilters}
              disabled={!filtersActive}
              className="text-[10px] tracking-[0.22em] uppercase transition-colors"
              style={{
                background: "transparent",
                color: filtersActive ? "#1f1f1f" : "#cdc8bb",
                border: "none",
                padding: "4px 0",
                cursor: filtersActive ? "pointer" : "not-allowed",
              }}
            >× Clear all</button>
            <button
              type="button"
              onClick={exportCsv}
              disabled={totalRows === 0}
              title={totalRows === 0 ? "No rows to export" : `Download ${totalRows} row${totalRows === 1 ? "" : "s"} as CSV`}
              className="text-[10px] tracking-[0.22em] uppercase transition-colors"
              style={{
                background: "transparent",
                color: totalRows === 0 ? "#cdc8bb" : "#1f1f1f",
                border: "none",
                padding: "4px 0",
                cursor: totalRows === 0 ? "not-allowed" : "pointer",
              }}
            >↓ CSV</button>
            <button
              type="button"
              onClick={() => setShowTradeBookingsModal(true)}
              title="Pick a date range and portfolios, then download a CSV of trade bookings"
              className="text-[10px] tracking-[0.22em] uppercase transition-colors"
              style={{
                background: "transparent",
                color: "#1f1f1f",
                border: "none",
                padding: "4px 0",
                cursor: "pointer",
              }}
            >↓ TRADE BOOKINGS</button>
          </div>
        </div>

        {/* Body — Portfolio + Status row, then Search row */}
        <div style={{ padding: "10px 16px 12px" }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              columnGap: 24,
              rowGap: 10,
              alignItems: "start",
              marginBottom: 10,
            }}
          >
            {/* Portfolio — picker + refined white chip stack */}
            <div className="flex flex-col gap-1 text-[10px] tracking-[0.18em] uppercase" style={{ color: "#6a665c" }}>
              <span>Portfolio</span>
              <Select
                value=""
                onChange={(e) => {
                  const v = e.target.value;
                  if (!v) return;
                  if (filters.portfolios.includes(v)) return;
                  setFilter("portfolios", [...filters.portfolios, v]);
                }}
              >
                <option value="">
                  {filters.portfolios.length === 0 ? "— Add portfolio —" : `+ Add another (${filters.portfolios.length} selected)`}
                </option>
                {PORTFOLIOS.filter((p) => !filters.portfolios.includes(String(p.number))).map((p) => (
                  <option key={p.number} value={String(p.number)}>
                    {p.number} — {p.name}
                  </option>
                ))}
              </Select>
              {filters.portfolios.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1.5">
                  {filters.portfolios.map((num) => {
                    const p = PORTFOLIOS.find((pp) => String(pp.number) === num);
                    const label = p ? `${p.number} — ${p.name.split(" - ").pop()}` : num;
                    return (
                      <span
                        key={num}
                        className="inline-flex items-center gap-1 text-[10px] tracking-[0.12em] px-2 py-0.5"
                        style={{
                          background: "#ffffff",
                          color: "#0d0d0d",
                          border: "1px solid #d4cfc2",
                          textTransform: "none",
                        }}
                        title={label}
                      >
                        {label}
                        <button
                          type="button"
                          aria-label={`Remove ${num}`}
                          onClick={() =>
                            setFilter("portfolios", filters.portfolios.filter((x) => x !== num))
                          }
                          style={{
                            background: "transparent",
                            border: "none",
                            cursor: "pointer",
                            color: "#a39e90",
                            fontSize: 12,
                            lineHeight: 1,
                            padding: 0,
                          }}
                        >×</button>
                      </span>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Status — chip toggles. Default = all except CANCELLED. */}
            <div className="flex flex-col gap-1 text-[10px] tracking-[0.18em] uppercase" style={{ color: "#6a665c" }}>
              <span>Status</span>
              <div className="flex flex-wrap gap-1" style={{ minHeight: 32, alignItems: "center" }}>
                {TRADE_STATUSES.map((s) => {
                  const on = filters.statuses.includes(s);
                  const sty = CASHFLOW_STATUS_STYLES[s];
                  return (
                    <button
                      key={s}
                      type="button"
                      onClick={() =>
                        setFilter(
                          "statuses",
                          on
                            ? filters.statuses.filter((x) => x !== s)
                            : [...filters.statuses, s]
                        )
                      }
                      className="px-1.5 py-0.5 text-[10px] tracking-[0.18em] uppercase"
                      style={{
                        background: on ? sty.bg : "#ffffff",
                        border: `1px solid ${on ? sty.border : "#e0dbd0"}`,
                        color: on ? sty.color : "#a39e90",
                        cursor: "pointer",
                        transition: "all 120ms ease",
                      }}
                      title={on ? `Hide ${s}` : `Show ${s}`}
                    >{s}</button>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Search row */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr 1fr",
              columnGap: 16,
            }}
          >
            {[
              { key: "base_asset", label: "Base Asset" },
              { key: "quote_asset", label: "Quote Asset" },
              { key: "deal_ref", label: "Deal Reference" },
            ].map((f) => (
              <label
                key={f.key}
                className="flex flex-col gap-1 text-[10px] tracking-[0.18em] uppercase"
                style={{ color: "#6a665c" }}
              >
                <span>{f.label}</span>
                <Input
                  type="text"
                  placeholder="—"
                  value={filters[f.key]}
                  onChange={(e) => setFilter(f.key, e.target.value)}
                />
              </label>
            ))}
          </div>
        </div>

        {/* Collapsible date range */}
        {showDates && (
          <div style={{ padding: "10px 16px 12px", borderTop: "1px solid #f3f1ec" }}>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                columnGap: 24,
                rowGap: 10,
              }}
            >
              {[
                { label: "Trade Date · From → To", fromKey: "trade_date_from", toKey: "trade_date_to" },
                { label: "Value Date · From → To", fromKey: "value_date_from", toKey: "value_date_to" },
              ].map((f) => (
                <div
                  key={f.fromKey}
                  className="flex flex-col gap-1 text-[10px] tracking-[0.18em] uppercase"
                  style={{ color: "#6a665c" }}
                >
                  <span>{f.label}</span>
                  <div className="flex items-center gap-2">
                    <DateTimePicker24 value={filters[f.fromKey]} onChange={(v) => setFilter(f.fromKey, v)} />
                    <span style={{ color: "#a39e90" }}>→</span>
                    <DateTimePicker24 value={filters[f.toKey]} onChange={(v) => setFilter(f.toKey, v)} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="overflow-x-auto" style={{ border: `1px solid ${BB?.border || "#d9d4c7"}` }}>
        <table className="w-full text-[12px]" style={{ fontFamily: "'IBM Plex Mono', ui-monospace, monospace", borderCollapse: "collapse", minWidth: "100%" }}>
          <thead>
            <tr style={{ background: BB?.surface || "#f6f3ec", color: BB?.mute || "#666" }}>
              <th className="px-2 py-2 whitespace-nowrap text-center" aria-label="Refresh">
                <button
                  type="button"
                  onClick={fetchRecent}
                  disabled={loading}
                  title={
                    loading
                      ? "Refreshing…"
                      : lastFetchedAt
                      ? `Refresh table · last updated ${lastFetchedAt.toLocaleTimeString()}`
                      : "Refresh table"
                  }
                  className="inline-flex items-center justify-center align-middle transition-colors"
                  style={{
                    width: 22, height: 22, borderRadius: 0,
                    border: `1px solid ${BB?.border || "#d9d4c7"}`,
                    background: "transparent",
                    color: BB?.dim || "#6a665c",
                    cursor: loading ? "wait" : "pointer", lineHeight: 1,
                    opacity: loading ? 0.5 : 1,
                  }}
                  onMouseEnter={(ev) => {
                    if (loading) return;
                    ev.currentTarget.style.background = "#ece7dd";
                    ev.currentTarget.style.color = BB?.text || "#0d0d0d";
                    ev.currentTarget.style.borderColor = BB?.text || "#0d0d0d";
                  }}
                  onMouseLeave={(ev) => {
                    ev.currentTarget.style.background = "transparent";
                    ev.currentTarget.style.color = BB?.dim || "#6a665c";
                    ev.currentTarget.style.borderColor = BB?.border || "#d9d4c7";
                  }}
                >
                  <span
                    aria-hidden
                    className={loading ? "animate-spin" : ""}
                    style={{ fontSize: 12, lineHeight: 1 }}
                  >↻</span>
                </button>
              </th>
              <th className="px-3 py-2 text-left whitespace-nowrap">Updated Date</th>
              <th className="px-3 py-2 text-left whitespace-nowrap">Deal Reference</th>
              <th className="px-3 py-2 text-left whitespace-nowrap">Deal Type</th>
              <th className="px-3 py-2 text-left whitespace-nowrap">Portfolio</th>
              <th className="px-3 py-2 text-left whitespace-nowrap">Portfolio Name</th>
              <th className="px-3 py-2 text-left whitespace-nowrap">Counterparty</th>
              <th className="px-3 py-2 text-left whitespace-nowrap">Details</th>
              <th className="px-3 py-2 text-left whitespace-nowrap">Trade Type</th>
              <th className="px-3 py-2 text-right whitespace-nowrap">Fees</th>
              <th className="px-3 py-2 text-left whitespace-nowrap">Trade Date</th>
              <th className="px-3 py-2 text-left whitespace-nowrap">Value Date</th>
              <th className="px-3 py-2 text-left whitespace-nowrap">Account</th>
              <th className="px-3 py-2 text-left whitespace-nowrap">Status</th>
            </tr>
          </thead>
          <tbody>
            {loading && rows.length === 0 && (
              <tr>
                <td colSpan={14} className="px-3 py-8 text-center opacity-70">
                  <span className="inline-flex items-center gap-2">
                    <span
                      aria-hidden
                      className="inline-block animate-spin"
                      style={{
                        width: 14,
                        height: 14,
                        border: "2px solid rgba(0,0,0,0.12)",
                        borderTopColor: "rgba(0,0,0,0.6)",
                        borderRadius: "50%",
                      }}
                    />
                    <span>Loading recent bookings…</span>
                  </span>
                </td>
              </tr>
            )}
            {!loading && filteredRows.length === 0 && (
              <tr>
                <td colSpan={14} className="px-3 py-6 text-center opacity-60">
                  {rows.length === 0
                    ? "No live cashflow or spot bookings yet."
                    : filtersActive
                    ? "No rows match the current filters."
                    : "No rows."}
                </td>
              </tr>
            )}
            {pagedRows.map((r) => {
              // Month Year is intentionally NOT rendered in the GUI but is
              // still part of the audit schema — when CSV export is added,
              // include it derived from trade_date as Month YYYY (UTC).
              return (
                <tr
                  key={r.deal_ref}
                  style={{ background: BB?.bg || "#ffffff", borderTop: `1px solid ${BB?.border || "#d9d4c7"}` }}
                  onMouseEnter={(e) => e.currentTarget.style.background = "rgba(0,0,0,0.03)"}
                  onMouseLeave={(e) => e.currentTarget.style.background = BB?.bg || "#ffffff"}
                >
                  <td className="px-2 py-2 whitespace-nowrap">
                    <button
                      type="button"
                      title="View audit trail"
                      onClick={() => onHistory(r.deal_ref)}
                      className="inline-flex items-center justify-center align-middle transition-colors"
                      style={{
                        width: 22, height: 22, borderRadius: 0,
                        border: `1px solid ${BB?.border || "#d9d4c7"}`,
                        background: "transparent",
                        color: BB?.dim || "#6a665c",
                        cursor: "pointer", lineHeight: 1,
                      }}
                      onMouseEnter={(ev) => {
                        ev.currentTarget.style.background = "#ece7dd";
                        ev.currentTarget.style.color = BB?.text || "#0d0d0d";
                        ev.currentTarget.style.borderColor = BB?.text || "#0d0d0d";
                      }}
                      onMouseLeave={(ev) => {
                        ev.currentTarget.style.background = "transparent";
                        ev.currentTarget.style.color = BB?.dim || "#6a665c";
                        ev.currentTarget.style.borderColor = BB?.border || "#d9d4c7";
                      }}
                    ><History size={12} strokeWidth={1.75} /></button>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    <HoverTip text={r.effective_start}>{fmtTs(r.effective_start)}</HoverTip>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    <button
                      type="button"
                      title="Open in form to amend"
                      onClick={() => onSelect(r)}
                      className="align-middle"
                      style={{
                        background: "transparent", border: "none", padding: 0,
                        color: "#1f63ea", cursor: "pointer", font: "inherit",
                      }}
                    >{r.deal_ref}</button>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">{r.txn_type}</td>
                  <td className="px-3 py-2 whitespace-nowrap">{r.portfolio_id}</td>
                  <td className="px-3 py-2 whitespace-nowrap">{r.portfolio_name || "—"}</td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    <HoverTip text={r.counterparty_id || (r.counterparty ? "(no refdata id)" : "")}>
                      {r.counterparty || "—"}
                    </HoverTip>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    {summarizeDeal(r)}
                    {(() => {
                      const mapSummary = summarizeMappings(r);
                      if (!mapSummary) return null;
                      // Tooltip text lists every mapped counterpart so a user
                      // can hover to confirm what they're linked to without
                      // opening the row.
                      const tipText = (r.mappings || [])
                        .map((m) => m.counterpart_deal_ref)
                        .join(", ");
                      // Inline link-style mapping reference — subtle
                      // dotted underline, no box. Click opens the FIRST
                      // mapped loan in the Loan Schedule modal. Multi-
                      // mapping cashflows still surface every ref in the
                      // hover tooltip (and "+ N more" in the label).
                      const firstRef = (r.mappings || [])[0]?.counterpart_deal_ref;
                      const clickable =
                        typeof onMappingClick === "function" && !!firstRef;
                      return (
                        <HoverTip text={tipText}>
                          <button
                            type="button"
                            onClick={() => clickable && onMappingClick(firstRef)}
                            disabled={!clickable}
                            className="ml-1.5 text-[11px]"
                            style={{
                              background: "transparent",
                              border: "none",
                              padding: 0,
                              font: "inherit",
                              color: "#1f63ea",
                              textDecoration: "underline dotted",
                              textUnderlineOffset: 3,
                              textDecorationColor: "rgba(31,99,234,0.5)",
                              cursor: clickable ? "pointer" : "default",
                            }}
                            onMouseEnter={(e) => {
                              if (clickable) {
                                e.currentTarget.style.textDecorationColor = "#1f63ea";
                              }
                            }}
                            onMouseLeave={(e) => {
                              e.currentTarget.style.textDecorationColor = "rgba(31,99,234,0.5)";
                            }}
                            title={clickable ? `Open ${firstRef} in Loan Schedule` : undefined}
                          >{mapSummary}</button>
                        </HoverTip>
                      );
                    })()}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">{r.cashflow_type || r.loan_type || (r.txn_type === "SPOT" ? r.direction : "") || "—"}</td>
                  {/* CSV export should still emit asset/amount/fee_asset/fee_amount
                      as four separate columns per the audit schema, even though
                      the table only renders the fee pair. Loan rows have no
                      fee column (interest accrues via separate cashflow rows). */}
                  <td className="px-3 py-2 text-right whitespace-nowrap">
                    {r.fee_amount && parseFloat(r.fee_amount) !== 0
                      ? <>{r.fee_amount} <span style={{ opacity: 0.7 }}>{r.fee_asset || ""}</span></>
                      : "—"}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    <HoverTip text={r.trade_date}>{fmtTs(r.trade_date)}</HoverTip>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    {/* Loan rows label the column "Value Date" but the
                        underlying field is maturity_date (NULL = open-term). */}
                    {r.value_date || r.maturity_date ? (
                      <HoverTip text={r.value_date || r.maturity_date}>
                        {fmtTs(r.value_date || r.maturity_date)}
                      </HoverTip>
                    ) : (
                      <span style={{ opacity: 0.55 }}>open-term</span>
                    )}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">{r.account || "—"}</td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    {/* Status pill — colour-coded to match the cashflow
                        lifecycle: pending → confirmed → processed →
                        settled (terminal-OK), or cancelled (terminal-NOK). */}
                    {(() => {
                      const s = r.status || "";
                      const styles = {
                        PENDING:   { bg: "#fcf6e8", border: "#d6c694", color: "#7a5a00" },
                        CONFIRMED: { bg: "#eef0f6", border: "#c8cde0", color: "#1f63ea" },
                        PROCESSED: { bg: "#eaf2ee", border: "#a3c4ad", color: "#22593c" },
                        SETTLED:   { bg: "#eef5e9", border: "#7ea66a", color: "#1f4a1f" },
                        CANCELLED: { bg: "#fff0eb", border: "#e08a6a", color: "#7a1f00" },
                      };
                      const e = styles[s] || { bg: "#f6f3ec", border: "#d9d4c7", color: "#1f1f1f" };
                      return (
                        <span
                          className="px-1.5 py-0.5 text-[10px] tracking-[0.18em] uppercase"
                          style={{ background: e.bg, border: `1px solid ${e.border}`, color: e.color }}
                        >{s || "—"}</span>
                      );
                    })()}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <EnquiryPaginationBar
        page={page}
        totalPages={totalPages}
        pageSize={pageSize}
        setPage={setPage}
        setPageSize={setPageSize}
        pageStart={pageStart}
        pageEnd={pageEnd}
        totalRows={totalRows}
        BB={BB}
      />

      <TradeBookingsExportModal
        open={showTradeBookingsModal}
        onClose={() => setShowTradeBookingsModal(false)}
        onError={setError}
      />
    </div>
  );
}

// ─── LoanScheduleExportModal — date + portfolio + accrual filters ────
// Triggered from the Loan Enquiry "↓ LOAN SCHEDULE" button. Opens with
// from = T-1 prev biz day, to = T-1 (yesterday), all portfolios selected,
// accrual date = yesterday UTC. Fetches /api/loan/export, runs each loan
// through buildLoanScheduleRows, flattens to 20-column CSV, downloads.
const LOAN_SCHEDULE_COLUMNS = [
  "START DATE",
  "MATURITY DATE",
  "PORTFOLIO",
  "PORTFOLIO NAME",
  "ASSET",
  "AMOUNT",
  "RATE (USD)",
  "AMOUNT (USD)",
  "INTEREST CALCULATION DATE",
  "INTEREST RATE P.A. (%)",
  "INTEREST ASSET",
  "ACCRUED INTEREST",
  "WHT",
  "NET PAID INTEREST",
  "LOAN TYPE",
  "COUNTERPARTY",
  "COMMENT",
  "Hedged Interest",
  "Hedged Price",
  "Hedge USDT",
];

function _fmtScheduleDateForCsv(ms) {
  if (ms == null) return "";
  const d = new Date(ms);
  // YYYY-MM-DD in UTC components to match how trade_date is stored.
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")}`;
}

function _fmtNumberForCsv(v, decimals = 8) {
  if (v == null || v === "" || Number.isNaN(v)) return "";
  const n = Number(v);
  if (Number.isNaN(n)) return "";
  // Strip trailing zeros after decimal; keep up to `decimals` precision.
  return n
    .toFixed(decimals)
    .replace(/\.?0+$/, "");
}

// Lookup map for comment by trigger_cashflow_deal_ref. Loan rows arrive
// with `.schedule_comments` already attached when present.
function _scheduleCommentsByTrigger(loan) {
  const out = {};
  const list = Array.isArray(loan?.schedule_comments) ? loan.schedule_comments : [];
  for (const c of list) {
    const ref = c.trigger_cashflow_deal_ref;
    if (ref) out[ref] = c.comment || "";
  }
  return out;
}

// Build the per-period schedule CSV rows for one loan. Returns an array
// of objects keyed by LOAN_SCHEDULE_COLUMNS headers.
function loanToScheduleCsvRows(loan, accrualDate) {
  const periods = buildLoanScheduleRows(loan, accrualDate);
  if (periods.length === 0) return [];
  const principal = loan.principal_amount;
  const rateUsd = loan.hedged_price;
  const amountUsd =
    principal != null && rateUsd != null && rateUsd !== ""
      ? Number(principal) * Number(rateUsd)
      : "";
  const whtPct = (parseFloat(loan.wht_pct) || 0) / 100;
  const commentsByTrigger = _scheduleCommentsByTrigger(loan);
  return periods.map((p) => {
    const accrued = p.accrued || 0;
    const wht = accrued * whtPct;
    const hedgeUsdt =
      rateUsd != null && rateUsd !== "" ? accrued * Number(rateUsd) : "";
    const comment = (p.triggerDealRef && commentsByTrigger[p.triggerDealRef]) || "";
    return {
      "START DATE": _fmtScheduleDateForCsv(p.startMs),
      "MATURITY DATE": loan.maturity_date ? String(loan.maturity_date).slice(0, 10) : "",
      "PORTFOLIO": loan.portfolio_id || "",
      "PORTFOLIO NAME": loan.portfolio_name || "",
      "ASSET": loan.principal_asset || "",
      "AMOUNT": _fmtNumberForCsv(principal),
      "RATE (USD)": _fmtNumberForCsv(rateUsd),
      "AMOUNT (USD)": _fmtNumberForCsv(amountUsd),
      "INTEREST CALCULATION DATE": _fmtScheduleDateForCsv(p.calcEndMs),
      "INTEREST RATE P.A. (%)": _fmtNumberForCsv(loan.interest_rate_pa_pct, 6),
      "INTEREST ASSET": loan.interest_asset || "",
      "ACCRUED INTEREST": _fmtNumberForCsv(accrued),
      "WHT": _fmtNumberForCsv(wht),
      "NET PAID INTEREST": _fmtNumberForCsv(p.netPaid),
      "LOAN TYPE": loan.loan_type || "",
      "COUNTERPARTY": loan.counterparty || "",
      "COMMENT": comment,
      "Hedged Interest": _fmtNumberForCsv(accrued),
      "Hedged Price": _fmtNumberForCsv(rateUsd),
      "Hedge USDT": _fmtNumberForCsv(hedgeUsdt),
    };
  });
}

function LoanScheduleExportModal({ open, onClose, onError }) {
  const computeDefaults = () => {
    // Loan trade_date filter defaults to empty — include every active
    // loan regardless of when it was booked (most loans run for months,
    // so a narrow recency window would exclude almost all of them).
    // Accrual Date defaults to yesterday UTC (the LIVE period cutoff).
    const t = new Date();
    t.setDate(t.getDate() - 1);
    return {
      from: "",
      to: "",
      accrual: fmtDateInput(t),
      portfolios: PORTFOLIOS.map((p) => String(p.number)),
    };
  };

  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [accrual, setAccrual] = useState("");
  const [portfolios, setPortfolios] = useState([]);
  const [portfoliosExpanded, setPortfoliosExpanded] = useState(false);
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    if (!open) return;
    const d = computeDefaults();
    setFrom(d.from);
    setTo(d.to);
    setAccrual(d.accrual);
    setPortfolios(d.portfolios);
    setPortfoliosExpanded(false);
  }, [open]);

  const doDownload = useCallback(async () => {
    if (downloading) return;
    setDownloading(true);
    try {
      const qs = new URLSearchParams();
      if (from) qs.set("from", from);
      if (to) qs.set("to", to);
      portfolios.forEach((p) => qs.append("portfolio", p));
      const r = await api(`/api/loan/export?${qs.toString()}`);
      if (!r.ok) {
        throw new Error(`HTTP ${r.status}`);
      }
      const body = await r.json();
      if (!body.ok) {
        throw new Error(body.error || "loan export failed");
      }
      const loans = body.rows || [];
      const csvRows = [];
      for (const loan of loans) {
        csvRows.push(...loanToScheduleCsvRows(loan, accrual || null));
      }
      const csv = rowsToCsv(
        csvRows,
        LOAN_SCHEDULE_COLUMNS.map((h) => ({ header: h, key: h })),
      );
      downloadCsv(`loan-schedule-${todayStampLocal()}.csv`, csv);
      onClose();
    } catch (e) {
      onError(`Loan Schedule download failed: ${String(e.message || e)}`);
    } finally {
      setDownloading(false);
    }
  }, [from, to, accrual, portfolios, downloading, onClose, onError]);

  const dateInputStyle = {
    fontFamily: "'IBM Plex Mono', ui-monospace, monospace",
    fontSize: 12,
    padding: "6px 8px",
    border: "1px solid #d9d4c7",
    background: "#ffffff",
    color: "#0d0d0d",
  };

  return (
    <ModalShell open={open} onClose={onClose}>
      <div style={{ padding: "28px 32px", maxWidth: 720 }}>
        <div
          className="text-[22px]"
          style={{
            fontFamily: "'Cormorant Garamond', 'EB Garamond', Georgia, serif",
            marginBottom: 18,
          }}
        >Download Loan Schedule</div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr 1fr",
            columnGap: 16,
            marginBottom: 18,
          }}
        >
          <label
            className="flex flex-col gap-1 text-[10px] tracking-[0.18em] uppercase"
            style={{ color: "#6a665c" }}
            title="Loan booked on or after this date. Empty = no lower bound."
          >
            <span>Loan Booked From</span>
            <input
              type="date"
              value={from}
              onChange={(e) => setFrom(e.target.value)}
              style={dateInputStyle}
            />
          </label>
          <label
            className="flex flex-col gap-1 text-[10px] tracking-[0.18em] uppercase"
            style={{ color: "#6a665c" }}
            title="Loan booked on or before this date. Empty = no upper bound."
          >
            <span>Loan Booked To</span>
            <input
              type="date"
              value={to}
              onChange={(e) => setTo(e.target.value)}
              style={dateInputStyle}
            />
          </label>
          <label
            className="flex flex-col gap-1 text-[10px] tracking-[0.18em] uppercase"
            style={{ color: "#6a665c" }}
            title="As-of date for LIVE (still-open) period accrual"
          >
            <span>Accrual Date</span>
            <input
              type="date"
              value={accrual}
              onChange={(e) => setAccrual(e.target.value)}
              style={dateInputStyle}
            />
          </label>
        </div>

        <div
          className="flex flex-col gap-1 text-[10px] tracking-[0.18em] uppercase"
          style={{ color: "#6a665c", marginBottom: 18 }}
        >
          <div className="flex items-center justify-between" style={{ minHeight: 18 }}>
            <span>Portfolios</span>
            {portfolios.length > 0 && (
              <button
                type="button"
                onClick={() => setPortfoliosExpanded((v) => !v)}
                className="text-[10px] tracking-[0.18em] uppercase"
                style={{
                  background: "transparent",
                  border: "none",
                  color: "#6a665c",
                  cursor: "pointer",
                  padding: 0,
                }}
              >
                {portfoliosExpanded
                  ? `▾ Hide selected (${portfolios.length})`
                  : `▸ Show selected (${portfolios.length})`}
              </button>
            )}
          </div>
          <Select
            value=""
            onChange={(e) => {
              const v = e.target.value;
              if (!v) return;
              if (portfolios.includes(v)) return;
              setPortfolios([...portfolios, v]);
            }}
          >
            <option value="">
              {portfolios.length === 0
                ? "— Add portfolio —"
                : `+ Add another (${portfolios.length} selected)`}
            </option>
            {PORTFOLIOS.filter((p) => !portfolios.includes(String(p.number))).map((p) => (
              <option key={p.number} value={String(p.number)}>
                {p.number} — {p.name}
              </option>
            ))}
          </Select>
          {portfolios.length > 0 && portfoliosExpanded && (
            <div className="flex flex-wrap gap-1 mt-1.5">
              {portfolios.map((num) => {
                const p = PORTFOLIOS.find((pp) => String(pp.number) === num);
                const label = p ? `${p.number} — ${p.name.split(" - ").pop()}` : num;
                return (
                  <span
                    key={num}
                    className="inline-flex items-center gap-1 text-[10px] tracking-[0.12em] px-2 py-0.5"
                    style={{
                      background: "#ffffff",
                      color: "#0d0d0d",
                      border: "1px solid #d4cfc2",
                      textTransform: "none",
                    }}
                    title={label}
                  >
                    {label}
                    <button
                      type="button"
                      aria-label={`Remove ${num}`}
                      onClick={() =>
                        setPortfolios(portfolios.filter((x) => x !== num))
                      }
                      style={{
                        background: "transparent",
                        border: "none",
                        cursor: "pointer",
                        color: "#a39e90",
                        fontSize: 12,
                        lineHeight: 1,
                        padding: 0,
                      }}
                    >×</button>
                  </span>
                );
              })}
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2" style={{ marginTop: 24 }}>
          <button
            type="button"
            onClick={onClose}
            disabled={downloading}
            className="px-3 py-1.5 text-[10px] tracking-[0.22em] uppercase"
            style={{
              background: "transparent",
              color: downloading ? "#cdc8bb" : "#1f1f1f",
              border: "1px solid #d9d4c7",
              cursor: downloading ? "not-allowed" : "pointer",
            }}
          >Cancel</button>
          <button
            type="button"
            onClick={doDownload}
            disabled={downloading}
            className="px-3 py-1.5 text-[10px] tracking-[0.22em] uppercase"
            style={{
              background: downloading ? "#cdc8bb" : "#1f1f1f",
              color: "#f2efe8",
              border: "1px solid #1f1f1f",
              cursor: downloading ? "wait" : "pointer",
            }}
          >{downloading ? "Preparing…" : "Download"}</button>
        </div>
      </div>
    </ModalShell>
  );
}

// ─── LoanEnquiry — separate view for trades_loan rows ────────────────
// Parallel to DealEnquiry but with loan-specific columns. Click the
// deal_ref to amend; click 📜 to see SCD2 history.
const LOAN_ENQUIRY_INITIAL_FILTERS = {
  trade_date_from: "",
  trade_date_to: "",
  maturity_date_from: "",
  maturity_date_to: "",
  portfolios: [],
  principal_asset: "",
  statuses: LOAN_STATUSES.filter((s) => s !== "CANCELLED"),
  deal_ref: "",
};

function LoanEnquiry({ onSelect, onHistory, BB, refreshSignal }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [lastFetchedAt, setLastFetchedAt] = useState(null);
  const [filters, setFilters] = useState(LOAN_ENQUIRY_INITIAL_FILTERS);
  const setFilter = (k, v) => setFilters((f) => ({ ...f, [k]: v }));
  const clearFilters = () => setFilters(LOAN_ENQUIRY_INITIAL_FILTERS);
  const filtersActive = filtersDifferFromDefault(filters, LOAN_ENQUIRY_INITIAL_FILTERS);
  const hasDateFilter = !!(filters.trade_date_from || filters.trade_date_to || filters.maturity_date_from || filters.maturity_date_to);
  const [showDates, setShowDates] = useState(false);
  // Pagination — page is 1-indexed; resets to 1 whenever filters change.
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  useEffect(() => { setPage(1); }, [filters, pageSize]);

  const filteredRows = useMemo(() => {
    const tokens = (s) =>
      String(s || "")
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);
    const assetTokens = tokens(filters.principal_asset).map((t) => t.toUpperCase());
    const refTokens = tokens(filters.deal_ref).map((t) => t.toLowerCase());
    return rows.filter((r) => {
      if (refTokens.length > 0) {
        const cand = String(r.deal_ref || "").toLowerCase();
        if (!refTokens.some((t) => cand.includes(t))) return false;
      }
      if (filters.portfolios.length > 0 && !filters.portfolios.includes(String(r.portfolio_id || ""))) {
        return false;
      }
      if (assetTokens.length > 0 && !assetTokens.includes(String(r.principal_asset || "").toUpperCase())) {
        return false;
      }
      if (filters.statuses.length > 0 && !filters.statuses.includes(String(r.status || ""))) {
        return false;
      }
      const td = String(r.trade_date || "").slice(0, 10);
      if (filters.trade_date_from && td && td < filters.trade_date_from) return false;
      if (filters.trade_date_to && td && td > filters.trade_date_to) return false;
      const md = String(r.maturity_date || "").slice(0, 10);
      if (filters.maturity_date_from && md && md < filters.maturity_date_from) return false;
      if (filters.maturity_date_to && md && md > filters.maturity_date_to) return false;
      return true;
    });
  }, [rows, filters]);

  const totalRows = filteredRows.length;
  const totalPages = Math.max(1, Math.ceil(totalRows / pageSize));
  useEffect(() => { if (page > totalPages) setPage(totalPages); }, [page, totalPages]);
  const pagedRows = useMemo(
    () => filteredRows.slice((page - 1) * pageSize, page * pageSize),
    [filteredRows, page, pageSize]
  );
  const pageStart = totalRows === 0 ? 0 : (page - 1) * pageSize + 1;
  const pageEnd = Math.min(page * pageSize, totalRows);

  const exportCsv = useCallback(() => {
    const csv = rowsToCsv(filteredRows, LOAN_CSV_COLUMNS);
    downloadCsv(`loan-enquiry-${todayStampLocal()}.csv`, csv);
  }, [filteredRows]);

  const [showLoanScheduleModal, setShowLoanScheduleModal] = useState(false);

  const fetchRecent = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await api("/api/loan/recent?limit=200");
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

  useEffect(() => { fetchRecent(); }, [fetchRecent, refreshSignal]);

  return (
    <div className="px-5 pt-4 pb-8">
      <div className="mb-3">
        <div
          className="text-[22px]"
          style={{ fontFamily: "'Cormorant Garamond', 'EB Garamond', Georgia, serif" }}
        >Loan Enquiry</div>
      </div>

      {error && (
        <div
          className="px-3 py-2 mb-3 text-[12px]"
          style={{ background: "#fff0eb", border: "1px solid #e08a6a", color: "#7a1f00" }}
        >Error: {error}</div>
      )}

      {/* ─── Filters — compact white card, parallel to Deal Enquiry. Date
          pickers tuck behind a "Date filters" toggle to keep the card small
          when dates aren't being filtered. ─── */}
      <div
        className="mb-3"
        style={{
          background: "#ffffff",
          border: "1px solid #e9e7e2",
          fontFamily: "'IBM Plex Mono', ui-monospace, monospace",
        }}
      >
        {/* Header strip — label, date toggle, clear all */}
        <div
          className="flex items-center justify-between"
          style={{ padding: "8px 16px", borderBottom: "1px solid #f3f1ec" }}
        >
          <div className="flex items-baseline gap-2.5">
            <span
              className="text-[10px] tracking-[0.28em] uppercase"
              style={{ color: "#8a857a", fontWeight: 500 }}
            >Filters</span>
            {filtersActive && (
              <span
                className="text-[9px] tracking-[0.22em] uppercase"
                style={{ color: "#b45309" }}
              >· Active</span>
            )}
          </div>
          <div className="flex items-center gap-5">
            <button
              type="button"
              onClick={() => setShowDates((s) => !s)}
              className="text-[10px] tracking-[0.22em] uppercase transition-colors"
              style={{
                background: "transparent",
                color: "#1f1f1f",
                border: "none",
                padding: "4px 0",
                cursor: "pointer",
              }}
            >
              {showDates ? "− Hide dates" : "+ Date filters"}
              {!showDates && hasDateFilter && (
                <span style={{ color: "#b45309", marginLeft: 4 }}>· Active</span>
              )}
            </button>
            <button
              type="button"
              onClick={clearFilters}
              disabled={!filtersActive}
              className="text-[10px] tracking-[0.22em] uppercase transition-colors"
              style={{
                background: "transparent",
                color: filtersActive ? "#1f1f1f" : "#cdc8bb",
                border: "none",
                padding: "4px 0",
                cursor: filtersActive ? "pointer" : "not-allowed",
              }}
            >× Clear all</button>
            <button
              type="button"
              onClick={exportCsv}
              disabled={totalRows === 0}
              title={totalRows === 0 ? "No rows to export" : `Download ${totalRows} row${totalRows === 1 ? "" : "s"} as CSV`}
              className="text-[10px] tracking-[0.22em] uppercase transition-colors"
              style={{
                background: "transparent",
                color: totalRows === 0 ? "#cdc8bb" : "#1f1f1f",
                border: "none",
                padding: "4px 0",
                cursor: totalRows === 0 ? "not-allowed" : "pointer",
              }}
            >↓ CSV</button>
            <button
              type="button"
              onClick={() => setShowLoanScheduleModal(true)}
              title="Pick filters and download the per-period loan schedule CSV (one row per accrual segment per loan)"
              className="text-[10px] tracking-[0.22em] uppercase transition-colors"
              style={{
                background: "transparent",
                color: "#1f1f1f",
                border: "none",
                padding: "4px 0",
                cursor: "pointer",
              }}
            >↓ LOAN SCHEDULE</button>
          </div>
        </div>

        {/* Body — Portfolio + Status row, then Search row */}
        <div style={{ padding: "10px 16px 12px" }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              columnGap: 24,
              rowGap: 10,
              alignItems: "start",
              marginBottom: 10,
            }}
          >
            {/* Portfolio — picker + refined white chip stack */}
            <div className="flex flex-col gap-1 text-[10px] tracking-[0.18em] uppercase" style={{ color: "#6a665c" }}>
              <span>Portfolio</span>
              <Select
                value=""
                onChange={(e) => {
                  const v = e.target.value;
                  if (!v) return;
                  if (filters.portfolios.includes(v)) return;
                  setFilter("portfolios", [...filters.portfolios, v]);
                }}
              >
                <option value="">
                  {filters.portfolios.length === 0 ? "— Add portfolio —" : `+ Add another (${filters.portfolios.length} selected)`}
                </option>
                {PORTFOLIOS.filter((p) => !filters.portfolios.includes(String(p.number))).map((p) => (
                  <option key={p.number} value={String(p.number)}>
                    {p.number} — {p.name}
                  </option>
                ))}
              </Select>
              {filters.portfolios.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1.5">
                  {filters.portfolios.map((num) => {
                    const p = PORTFOLIOS.find((pp) => String(pp.number) === num);
                    const label = p ? `${p.number} — ${p.name.split(" - ").pop()}` : num;
                    return (
                      <span
                        key={num}
                        className="inline-flex items-center gap-1 text-[10px] tracking-[0.12em] px-2 py-0.5"
                        style={{
                          background: "#ffffff",
                          color: "#0d0d0d",
                          border: "1px solid #d4cfc2",
                          textTransform: "none",
                        }}
                        title={label}
                      >
                        {label}
                        <button
                          type="button"
                          aria-label={`Remove ${num}`}
                          onClick={() =>
                            setFilter("portfolios", filters.portfolios.filter((x) => x !== num))
                          }
                          style={{
                            background: "transparent",
                            border: "none",
                            cursor: "pointer",
                            color: "#a39e90",
                            fontSize: 12,
                            lineHeight: 1,
                            padding: 0,
                          }}
                        >×</button>
                      </span>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Status — chip toggles */}
            <div className="flex flex-col gap-1 text-[10px] tracking-[0.18em] uppercase" style={{ color: "#6a665c" }}>
              <span>Status</span>
              <div className="flex flex-wrap gap-1" style={{ minHeight: 32, alignItems: "center" }}>
                {LOAN_STATUSES.map((s) => {
                  const on = filters.statuses.includes(s);
                  const sty = LOAN_STATUS_STYLES[s];
                  return (
                    <button
                      key={s}
                      type="button"
                      onClick={() =>
                        setFilter(
                          "statuses",
                          on
                            ? filters.statuses.filter((x) => x !== s)
                            : [...filters.statuses, s]
                        )
                      }
                      className="px-1.5 py-0.5 text-[10px] tracking-[0.18em] uppercase"
                      style={{
                        background: on ? sty.bg : "#ffffff",
                        border: `1px solid ${on ? sty.border : "#e0dbd0"}`,
                        color: on ? sty.color : "#a39e90",
                        cursor: "pointer",
                        transition: "all 120ms ease",
                      }}
                      title={on ? `Hide ${s}` : `Show ${s}`}
                    >{s}</button>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Search row */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              columnGap: 16,
            }}
          >
            <label className="flex flex-col gap-1 text-[10px] tracking-[0.18em] uppercase" style={{ color: "#6a665c" }}>
              <span>Principal Asset</span>
              <Input
                type="text"
                value={filters.principal_asset}
                onChange={(e) => setFilter("principal_asset", e.target.value)}
                placeholder="e.g. ETH, USDT"
              />
            </label>
            <label className="flex flex-col gap-1 text-[10px] tracking-[0.18em] uppercase" style={{ color: "#6a665c" }}>
              <span>Deal Reference</span>
              <Input
                type="text"
                value={filters.deal_ref}
                onChange={(e) => setFilter("deal_ref", e.target.value)}
                placeholder="MLA00000001, MLA00000005…"
              />
            </label>
          </div>
        </div>

        {/* Collapsible date range */}
        {showDates && (
          <div style={{ padding: "10px 16px 12px", borderTop: "1px solid #f3f1ec" }}>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                columnGap: 24,
                rowGap: 10,
              }}
            >
              {[
                { label: "Trade Date · From → To", fromKey: "trade_date_from", toKey: "trade_date_to" },
                { label: "Maturity Date · From → To", fromKey: "maturity_date_from", toKey: "maturity_date_to" },
              ].map((f) => (
                <div
                  key={f.fromKey}
                  className="flex flex-col gap-1 text-[10px] tracking-[0.18em] uppercase"
                  style={{ color: "#6a665c" }}
                >
                  <span>{f.label}</span>
                  <div className="flex items-center gap-2">
                    <DatePicker value={filters[f.fromKey]} onChange={(v) => setFilter(f.fromKey, v)} />
                    <span style={{ color: "#a39e90" }}>→</span>
                    <DatePicker value={filters[f.toKey]} onChange={(v) => setFilter(f.toKey, v)} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* ─── Table ─── */}
      <div className="overflow-x-auto" style={{ border: `1px solid ${BB?.border || "#d9d4c7"}` }}>
        <table className="w-full text-[12px]" style={{ fontFamily: "'IBM Plex Mono', ui-monospace, monospace" }}>
          <thead>
            <tr style={{ background: BB?.surface || "#f6f3ec", color: BB?.mute || "#666" }}>
              <th className="px-2 py-2 whitespace-nowrap text-center" aria-label="Refresh">
                <button
                  type="button"
                  onClick={fetchRecent}
                  disabled={loading}
                  title={
                    loading
                      ? "Refreshing…"
                      : lastFetchedAt
                      ? `Refresh table · last updated ${lastFetchedAt.toLocaleTimeString()}`
                      : "Refresh table"
                  }
                  className="inline-flex items-center justify-center align-middle transition-colors"
                  style={{
                    width: 22, height: 22, borderRadius: 0,
                    border: `1px solid ${BB?.border || "#d9d4c7"}`,
                    background: "transparent",
                    color: BB?.dim || "#6a665c",
                    cursor: loading ? "wait" : "pointer", lineHeight: 1,
                    opacity: loading ? 0.5 : 1,
                  }}
                  onMouseEnter={(ev) => {
                    if (loading) return;
                    ev.currentTarget.style.background = "#ece7dd";
                    ev.currentTarget.style.color = BB?.text || "#0d0d0d";
                    ev.currentTarget.style.borderColor = BB?.text || "#0d0d0d";
                  }}
                  onMouseLeave={(ev) => {
                    ev.currentTarget.style.background = "transparent";
                    ev.currentTarget.style.color = BB?.dim || "#6a665c";
                    ev.currentTarget.style.borderColor = BB?.border || "#d9d4c7";
                  }}
                >
                  <span
                    aria-hidden
                    className={loading ? "animate-spin" : ""}
                    style={{ fontSize: 12, lineHeight: 1 }}
                  >↻</span>
                </button>
              </th>
              <th className="px-3 py-2 text-left whitespace-nowrap">Input Date</th>
              <th className="px-3 py-2 text-left whitespace-nowrap">Deal Reference</th>
              <th className="px-3 py-2 text-left whitespace-nowrap">Direction</th>
              <th className="px-3 py-2 text-left whitespace-nowrap">Type</th>
              <th className="px-3 py-2 text-left whitespace-nowrap">Portfolio</th>
              <th className="px-3 py-2 text-left whitespace-nowrap">Counterparty</th>
              <th className="px-3 py-2 text-right whitespace-nowrap">Principal</th>
              <th className="px-3 py-2 text-right whitespace-nowrap">Rate</th>
              <th className="px-3 py-2 text-left whitespace-nowrap">Start Date</th>
              <th className="px-3 py-2 text-left whitespace-nowrap">Maturity</th>
              <th className="px-3 py-2 text-center whitespace-nowrap">Interest Hedged</th>
              <th className="px-3 py-2 text-left whitespace-nowrap">Hedged Till</th>
              <th className="px-3 py-2 text-left whitespace-nowrap">Status</th>
              <th className="px-3 py-2 text-left whitespace-nowrap">Linked Cashflows</th>
            </tr>
          </thead>
          <tbody>
            {filteredRows.length === 0 && !loading && (
              <tr>
                <td colSpan={15} className="px-3 py-6 text-center" style={{ color: BB?.mute || "#666" }}>
                  {rows.length === 0 ? "No loans booked yet." : "No rows match the current filters."}
                </td>
              </tr>
            )}
            {pagedRows.map((r) => {
              const principalNum = parseFloat(r.principal_amount) || 0;
              const principalFmt = principalNum.toLocaleString("en-US", { maximumFractionDigits: 5 });
              const mapCount = (r.mappings || []).length;
              const mapTotal = (r.mappings || []).reduce((s, x) => s + (parseFloat(x.amount) || 0), 0);
              return (
                <tr
                  key={r.deal_ref}
                  style={{ background: BB?.bg || "#ffffff", borderTop: `1px solid ${BB?.border || "#d9d4c7"}` }}
                >
                  <td className="px-2 py-2 whitespace-nowrap text-center">
                    <button
                      type="button"
                      title="View audit trail"
                      onClick={() => onHistory(r.deal_ref)}
                      className="inline-flex items-center justify-center align-middle transition-colors"
                      style={{
                        width: 22, height: 22, borderRadius: 0,
                        border: `1px solid ${BB?.border || "#d9d4c7"}`,
                        background: "transparent",
                        color: BB?.dim || "#6a665c",
                        cursor: "pointer", lineHeight: 1,
                      }}
                      onMouseEnter={(ev) => {
                        ev.currentTarget.style.background = "#ece7dd";
                        ev.currentTarget.style.color = BB?.text || "#0d0d0d";
                        ev.currentTarget.style.borderColor = BB?.text || "#0d0d0d";
                      }}
                      onMouseLeave={(ev) => {
                        ev.currentTarget.style.background = "transparent";
                        ev.currentTarget.style.color = BB?.dim || "#6a665c";
                        ev.currentTarget.style.borderColor = BB?.border || "#d9d4c7";
                      }}
                    ><History size={12} strokeWidth={1.75} /></button>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    <HoverTip text={r.first_effective_start || r.effective_start}>
                      {fmtTs(r.first_effective_start || r.effective_start)}
                    </HoverTip>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    <button
                      type="button"
                      title="Open in form to amend"
                      onClick={() => onSelect(r)}
                      className="align-middle"
                      style={{
                        background: "transparent", border: "none", padding: 0,
                        color: "#1f63ea", cursor: "pointer", font: "inherit",
                      }}
                    >{r.deal_ref}</button>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">{r.direction}</td>
                  <td className="px-3 py-2 whitespace-nowrap">{r.loan_type}</td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    {r.portfolio_id}{r.portfolio_name ? <span style={{ opacity: 0.65 }}> · {r.portfolio_name}</span> : null}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    <HoverTip text={r.counterparty_id || (r.counterparty ? "(no refdata id)" : "")}>
                      {r.counterparty || "—"}
                    </HoverTip>
                  </td>
                  <td className="px-3 py-2 text-right whitespace-nowrap">
                    {principalFmt} <span style={{ opacity: 0.7 }}>{r.principal_asset || ""}</span>
                  </td>
                  <td className="px-3 py-2 text-right whitespace-nowrap">
                    {r.interest_rate_pa_pct ?? "—"}% <span style={{ opacity: 0.65 }}>{r.interest_type || ""}</span>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    <HoverTip text={r.trade_date}>{fmtTs(r.trade_date)}</HoverTip>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    {r.maturity_date ? (
                      <HoverTip text={r.maturity_date}>{fmtTs(r.maturity_date)}</HoverTip>
                    ) : (
                      <span style={{ opacity: 0.55 }}>open-term</span>
                    )}
                  </td>
                  {(() => {
                    const cov = projectHedgeCoverage(r);
                    const isY = !!r.is_hedged;
                    return (
                      <>
                        <td className="px-3 py-2 whitespace-nowrap text-center">
                          {isY ? (
                            <span style={{ color: "#1f4a1f", fontWeight: 600 }}>Y</span>
                          ) : (
                            <span style={{ opacity: 0.4 }}>—</span>
                          )}
                        </td>
                        <td className="px-3 py-2 whitespace-nowrap">
                          {cov.status === "PROJECTED" ? (
                            <HoverTip
                              text={`projected from hedged_qty ${r.hedged_qty} ${r.hedged_asset || r.interest_asset || ""} / daily accrual`}
                            >
                              {fmtTs(cov.endDate.toISOString(), 10)}
                            </HoverTip>
                          ) : cov.status === "INFINITE" ? (
                            <span style={{ opacity: 0.7 }} title="Interest rate is 0 — buffer never depletes">∞</span>
                          ) : (
                            <span style={{ opacity: 0.4 }}>—</span>
                          )}
                        </td>
                      </>
                    );
                  })()}
                  <td className="px-3 py-2 whitespace-nowrap">
                    <span
                      className="px-1.5 py-0.5 text-[10px]"
                      style={{
                        background:
                          r.status === "LIVE" ? "#eef5e9" :
                          r.status === "MATURED" ? "#eef0f6" :
                          r.status === "CANCELLED" ? "#fff0eb" : "#f6f3ec",
                        border: `1px solid ${
                          r.status === "LIVE" ? "#7ea66a" :
                          r.status === "MATURED" ? "#c8cde0" :
                          r.status === "CANCELLED" ? "#e08a6a" : "#d9d4c7"
                        }`,
                        color:
                          r.status === "LIVE" ? "#1f4a1f" :
                          r.status === "MATURED" ? "#1f63ea" :
                          r.status === "CANCELLED" ? "#7a1f00" : "#1f1f1f",
                      }}
                    >{r.status}</span>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    {mapCount === 0 ? (
                      <span style={{ opacity: 0.55 }}>—</span>
                    ) : (
                      <HoverTip text={(r.mappings || []).map((m) => m.counterpart_deal_ref).join(", ")}>
                        <span
                          className="px-1.5 py-0.5 text-[10px]"
                          style={{ background: "#eef0f6", border: "1px solid #c8cde0", color: "#1f63ea" }}
                        >
                          ↗ {mapCount} · {mapTotal >= 0 ? "+" : ""}{mapTotal.toLocaleString("en-US", { maximumFractionDigits: 5 })} {r.principal_asset || ""}
                        </span>
                      </HoverTip>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <EnquiryPaginationBar
        page={page}
        totalPages={totalPages}
        pageSize={pageSize}
        setPage={setPage}
        setPageSize={setPageSize}
        pageStart={pageStart}
        pageEnd={pageEnd}
        totalRows={totalRows}
        BB={BB}
      />

      <LoanScheduleExportModal
        open={showLoanScheduleModal}
        onClose={() => setShowLoanScheduleModal(false)}
        onError={setError}
      />
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
  const { user, logout } = useAuth();
  const [appView, setAppView] = useState("booking"); // "booking" | "users" | "tokens"
  const fileInputRef = useRef(null);
  const clock = useClock();

  // Fetch the live token list from server.js (refreshed hourly). On failure
  // we silently keep the bundled TOKENS seed so the form still works offline.
  // Same-origin: Vite proxies /tokens.json in dev, ingress routes in UAT/prod.
  const [liveTokens, setLiveTokens] = useState(TOKENS);
  useEffect(() => {
    (async () => {
      try {
        const r = await fetch("/tokens.json", { cache: "no-cache" });
        if (!r.ok) return;
        const j = await r.json();
        if (Array.isArray(j?.tokens) && j.tokens.length > 0) {
          setLiveTokens(j.tokens);
        }
      } catch { /* keep bundled TOKENS seed */ }
    })();
  }, []);

  // ─── Live loans (for the cashflow form's loan-link picker) ─────────
  // Fetched once on mount + after every successful insert/amend, so a
  // freshly booked loan shows up in the picker without a hard refresh.
  // Filtered to the form's current portfolio inside the picker.
  const [liveLoans, setLiveLoans] = useState([]);
  const refreshLiveLoans = useCallback(async () => {
    try {
      const r = await api("/api/loan/recent?limit=200", { cache: "no-cache" });
      const j = await r.json();
      if (j.ok && Array.isArray(j.rows)) setLiveLoans(j.rows);
    } catch { /* server might be down — picker just shows empty */ }
  }, []);
  useEffect(() => { refreshLiveLoans(); }, [refreshLiveLoans]);

  // ─── Refdata (counterparties, portfolios, users) — runtime fetch ───
  // PORTFOLIOS / COUNTERPARTIES / SUPERADMIN_USERS / USER_PROFILES are
  // module-scope mutable holders. fetchRefdataOnce() populates them
  // from /refdata/*.json. We bump refdataTick to force a re-render
  // each time so pickers see the new lists.
  const [refdataTick, setRefdataTick] = useState(0);
  const [refdataLoading, setRefdataLoading] = useState(false);
  const [refdataLastAt, setRefdataLastAt] = useState(null);
  const [refdataError, setRefdataError] = useState(null);

  useEffect(() => {
    // Initial load on mount + auto-refresh so PORTFOLIOS / COUNTERPARTIES
    // stay current as the user keeps the tab open. Lightweight: just
    // re-pulls the JSON files (no MySQL resync — that's the manual
    // "↻ Refresh refdata" button's job or the server's hourly tick).
    let cancelled = false;
    const refresh = async () => {
      if (cancelled) return;
      try {
        await fetchRefdataOnce();
        if (!cancelled) {
          setRefdataTick((t) => t + 1);
          setRefdataLastAt(new Date());
          setRefdataError(null);
        }
      } catch (e) {
        if (!cancelled) setRefdataError(String(e));
      }
    };
    refresh(); // initial mount
    // Refetch when the tab regains focus or returns to visible — covers
    // "I left the tab open overnight and came back" without forcing a
    // hard refresh.
    const onFocus = () => refresh();
    const onVisibility = () => {
      if (document.visibilityState === "visible") refresh();
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibility);
    // Periodic background refresh — every 2 minutes while the tab is
    // open. The server regenerates the JSON files hourly at HH:15 UTC,
    // so 2-minute polling catches any out-of-band manual refresh too.
    const interval = setInterval(refresh, 120_000);
    return () => {
      cancelled = true;
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisibility);
      clearInterval(interval);
    };
  }, []);

  // Manual "↻ Refresh refdata" button handler: kicks the server to
  // re-sync all 4 sources from MySQL, then re-reads the JSON files.
  const refreshRefdata = useCallback(async () => {
    if (refdataLoading) return;
    setRefdataLoading(true);
    setRefdataError(null);
    let serverOk = false;
    try {
      const r = await api("/api/refdata/refresh", { method: "POST" });
      if (r.ok) serverOk = true;
    } catch { /* server unreachable */ }
    if (!serverOk) {
      setRefdataError("server refresh failed — check trade-booking server is running");
      setRefdataLoading(false);
      return;
    }
    try {
      await fetchRefdataOnce();
      setRefdataTick((t) => t + 1);
      setRefdataLastAt(new Date());
    } catch (e) {
      setRefdataError(String(e));
    } finally {
      setRefdataLoading(false);
    }
  }, [refdataLoading]);

  // Seed form.created_by from SUPERADMIN_USERS once refdata is available.
  // Fires on each refdataTick bump. initial() runs synchronously at mount
  // (before fetchRefdataOnce resolves) so SUPERADMIN_USERS was empty at
  // that point and created_by was left "". The functional setState here
  // is a no-op when created_by is already truthy. Note: we deliberately
  // don't add form.created_by to the dep array — form is declared lower
  // in this component (temporal dead zone), and SHARED_KEYS /
  // initialSharedForCategory below cover the category-switch case.
  useEffect(() => {
    if (SUPERADMIN_USERS.length === 0) return;
    setForm((f) => (f.created_by ? f : { ...f, created_by: SUPERADMIN_USERS[0] }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refdataTick]);

  // Keep form.created_by in sync with the session user so existing submit
  // handlers that read form.created_by continue to work correctly.
  // The server stamps user_id from the session anyway, but this keeps
  // the field accurate for any client-side reads.
  useEffect(() => {
    if (user?.username) {
      setForm((f) => ({ ...f, created_by: user.username }));
    }
  }, [user?.username]);

  const initial = () => ({
    trade_id: genTradeId("SPOT"),
    external_trade_id: "",
    created_at: isoNow(),
    last_modified_at: isoNow(),
    created_by: SUPERADMIN_USERS[0] || "",
    trade_date: nowUtc(),
    value_date: nowUtc(),
    // Portfolio is the source of truth — entity is derived from it
    // via PORTFOLIOS[].entity. Empty string means "not yet selected".
    portfolio: "",
    // Display fallbacks captured straight off the loaded row, so the
    // picker can render the existing deal's portfolio / counterparty
    // labels without waiting on the async refdata fetch.
    portfolio_name_row: "",
    counterparty_id_row: "",
    account_id: "",
    venue_type: "CEX",
    venue: "Binance",
    category: "SPOT",
    status: "CONFIRMED",
    tx_id: "",
    notes: "",
    // SPOT
    spot_direction: "LONG",
    spot_internal: false,
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
    cf_direction: "OUTGOING",
    cf_type: "",
    cf_mirror: false,
    cf_mirror_account_venue_type: "EXCHANGE",
    cf_mirror_account_name: "",
    cf_asset: "USDT",
    cf_amount: "",
    // Loan ↔ cashflow mappings. Only meaningful when cf_type is one of
    // LOAN / LOAN REPAYMENT / INTEREST EXPENSE / INTEREST INCOME — see
    // LOAN_RELATED_CF_TYPES. Persisted in loan_cashflow_map (not on
    // trades_cashflow) so it ships via _meta.loan_deal_refs.
    cf_loan_deal_refs: [],
    network: "",
    gas_fee: "",
    gas_asset: "ETH",
    tx_hash: "",
    loan_direction: "BORROW",
    loan_type: "VIP LOAN",
    loan_term_days: "",
    principal_asset: "USDT",
    interest_asset: "USDT",
    principal_amount: "",
    interest_rate: "",
    interest_type: "FIXED",
    // Days-per-year for interest accrual. 365 (Actual/365) is the
    // crypto default; 360 (Actual/360) for USD money-market style loans.
    day_count_basis: 365,
    floating_benchmark: "",
    // Optional withholding-tax rate (% of accrued interest). Empty
    // means not applicable; the schedule's WHT column stays blank.
    wht_pct: "",
    collateral_asset: "",
    collateral_amount: "",
    is_hedged: false,
    // Hedged asset defaults to track interest_asset (the typical hedge
    // — sell the same asset interest accrues in). Synced automatically
    // when interest_asset or principal_asset change; user can override.
    hedged_asset: "USDT",
    hedged_qty: "",
    hedged_price: "",
    hedge_proceeds_asset: "USDT",
    hedge_proceeds_amount: "",
    attachments: [],
  });

  const [form, setForm] = useState(initial);

  // When the cashflow is tagged to a loan, the cashflow's asset is
  // *constrained* to match the loan's relevant asset:
  //   LOAN / LOAN REPAYMENT   → loan.principal_asset
  //   INTEREST EXPENSE/INCOME → loan.interest_asset
  // (e.g. a 3,300-ETH loan's interest payments must also be in ETH unless
  // the loan was booked with a different interest_asset on purpose.)
  // Returns the locked symbol, or "" when nothing is locked yet, or
  // null when the picked loans disagree (caller treats as a conflict).
  const cfAssetLock = useMemo(() => {
    if (!LOAN_RELATED_CF_TYPES.has(form.cf_type)) return "";
    const refs = form.cf_loan_deal_refs || [];
    if (refs.length === 0) return "";
    const useInterest =
      form.cf_type === "INTEREST EXPENSE" || form.cf_type === "INTEREST INCOME";
    const assets = new Set();
    for (const r of refs) {
      const loan = liveLoans.find((l) => l.deal_ref === r);
      if (!loan) continue;
      assets.add(useInterest ? loan.interest_asset : loan.principal_asset);
    }
    if (assets.size === 0) return "";
    if (assets.size > 1) return null; // conflict — UI shouldn't allow this
    return [...assets][0];
  }, [form.cf_type, form.cf_loan_deal_refs, liveLoans]);

  // Auto-snap cf_asset (and fee_asset, if it was trailing) to the lock.
  // Only fires when the lock is a real symbol — for null (conflict) we
  // leave the user's prior asset alone so the warning surfaces it.
  useEffect(() => {
    if (!cfAssetLock) return;
    setForm((f) => {
      if (f.cf_asset === cfAssetLock) return f;
      return {
        ...f,
        cf_asset: cfAssetLock,
        fee_asset: f.fee_asset === f.cf_asset ? cfAssetLock : f.fee_asset,
        last_modified_at: isoNow(),
      };
    });
  }, [cfAssetLock]);

  const [submittedRecord, setSubmittedRecord] = useState(null);
  const [copied, setCopied] = useState(false);
  // Cashflow tx-hash fetch state (Task 7).
  const [txFetchLoading, setTxFetchLoading] = useState(false);
  const [txFetchError, setTxFetchError] = useState(null);
  const [txFetchResult, setTxFetchResult] = useState(null); // {transfers, gas_fee, …} | null
  const [txFetchSuccess, setTxFetchSuccess] = useState(null);
  // ENV is derived from window.location.hostname, not user-toggleable:
  //   localhost / 127.0.0.1            → UAT  (dev mirrors UAT backend)
  //   hostname contains 'test' or 'uat' → UAT
  //   everything else                  → PROD
  const env = (() => {
    if (typeof window === "undefined") return "PROD";
    const h = window.location.hostname.toLowerCase();
    if (h === "localhost" || h === "127.0.0.1") return "UAT";
    if (h.includes("test") || h.includes("uat")) return "UAT";
    return "PROD";
  })();
  const [view, setView] = useState("DEAL_ENQUIRY");
  const [createDealOpen, setCreateDealOpen] = useState(false);
  // Per-category snapshot of shared fields. When you switch from SPOT to
  // LOAN, the current SPOT values for dates/portfolio/counterparty/status/etc.
  // are stashed here under "SPOT"; when you switch back to SPOT, they're
  // restored. This keeps each product form independent.
  const [categoryCache, setCategoryCache] = useState({});
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v, last_modified_at: isoNow() }));
  const setMany = (patch) => setForm((f) => ({ ...f, ...patch, last_modified_at: isoNow() }));

  // Cashflow tx-hash fetch handler (Task 7).
  async function handleFetchTx() {
    setTxFetchError(null);
    setTxFetchResult(null);
    setTxFetchLoading(true);
    try {
      const res = await fetch("/api/cashflow/fetch-tx", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          tx_hash: form.tx_hash.trim(),
          network: form.network,
        }),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) {
        setTxFetchError(txFetchErrorMessage(res.status, json, form.network));
        return;
      }
      if (json.transfers && json.transfers.length === 1) {
        applyAutofill(json.transfers[0], json);
        setTxFetchResult(null); // hide the result; the form now has the data
      } else {
        // Multi-transfer — Task 9 surfaces the picker by keeping txFetchResult set.
        setTxFetchResult(json);
      }
    } catch (e) {
      setTxFetchError("Couldn't reach the server, try again");
    } finally {
      setTxFetchLoading(false);
    }
  }

  // Autofill helper (Task 8): fills empty-only fields from a single transfer.
  function isEmpty(v) {
    return v === "" || v === null || v === undefined;
  }

  function applyAutofill(transfer, result) {
    const dateOnly = (result.timestamp || "").slice(0, 10); // "2026-05-22T…" → "2026-05-22"
    const stamp = `from: ${result.tx_from} → to: ${result.tx_to} (tx ${form.tx_hash})`;
    const patch = {};
    if (isEmpty(form.cf_asset))   patch.cf_asset   = transfer.asset;
    if (isEmpty(form.cf_amount))  patch.cf_amount  = transfer.amount;
    if (isEmpty(form.gas_asset))  patch.gas_asset  = result.gas_asset;
    if (isEmpty(form.gas_fee))    patch.gas_fee    = result.gas_fee;
    if (isEmpty(form.trade_date)) patch.trade_date = dateOnly;
    if (isEmpty(form.value_date)) patch.value_date = dateOnly;
    patch.notes = isEmpty(form.notes) ? stamp : `${form.notes}\n${stamp}`;
    // Resolve counterparty from refdata: if exactly one of from/to maps to a
    // counterparty (not our own wallet/exchange), fill it empty-only.
    const resolutions = result.resolutions || {};
    const counterpartyOwners = new Set(
      [transfer.from, transfer.to]
        .map((a) => resolutions[(a || "").toLowerCase()])
        .filter((r) => r && r.kind === "counterparty")
        .map((r) => r.owner),
    );
    let filledCp = null;
    if (counterpartyOwners.size === 1 && isEmpty(form.counterparty)) {
      patch.counterparty = [...counterpartyOwners][0];
      filledCp = patch.counterparty;
    }
    setMany(patch);
    setTxFetchSuccess(filledCp ? `Filled from chain — counterparty: ${filledCp}` : "Filled from chain");
    setTimeout(() => setTxFetchSuccess(null), 4000);
  }

  function txFetchErrorMessage(status, json, network) {
    if (status === 400) return "Couldn't read that hash, double-check it";
    if (status === 404) return `Not found on ${network} — wrong network?`;
    if (status === 422) return "No token or native transfers found in this tx";
    if (status === 502) return "Couldn't reach chain explorer, try again";
    return "Something went wrong fetching this tx";
  }

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
    "created_by",
  ];

  const initialSharedForCategory = (cat) => ({
    trade_id: genTradeId(cat),
    external_trade_id: "",
    trade_date: nowUtc(),
    value_date: nowUtc(),
    portfolio: "",
    status: defaultStatusFor(cat),
    counterparty: "",
    // Carry the current superadmin default so switching categories
    // doesn't drop the form's "Created by" back to blank.
    created_by: SUPERADMIN_USERS[0] || "",
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

  // INTER PTF FUNDING mirror-leg accounts. For mirror trades, the counterparty
  // field holds the counterparty portfolio's number — the leg-2 account belongs
  // to THAT portfolio, not the booking portfolio.
  const mirrorAccountOptions = useMemo(() => {
    const portfolioName = PORTFOLIOS.find(
      (p) => String(p.number) === String(form.counterparty)
    )?.name;
    if (!portfolioName) return [];
    const pool =
      form.cf_mirror_account_venue_type === "EXCHANGE"
        ? ACCOUNTS_EXCHANGE
        : form.cf_mirror_account_venue_type === "WALLET"
        ? ACCOUNTS_WALLET
        : form.cf_mirror_account_venue_type === "BROKER"
        ? ACCOUNTS_BROKER
        : [];
    return pool.filter((a) => a.portfolio === portfolioName);
  }, [form.counterparty, form.cf_mirror_account_venue_type]);

  // INTER PTF FUNDING auto-comment. Produces strings like:
  //   OUTGOING: "PTF 8888 TREASURY FUNDS PTF 8041 CENTRAL RISK BOOK 1000 USDT"
  //   INCOMING: "PTF 8041 CENTRAL RISK BOOK RETURNED PTF 8888 TREASURY 1000 USDT"
  // The short portfolio name is the last " - "-separated segment of the full
  // portfolio name (e.g. "TOKKA LABS - MM - CENTRAL RISK BOOK" → "CENTRAL RISK BOOK").
  // Returns null when we don't have enough context to render a template.
  const ipfNotesTemplate = useMemo(() => {
    if (form.cf_type !== "INTER PTF FUNDING") return null;
    if (!form.portfolio || !form.counterparty || !form.cf_amount || !form.cf_asset) return null;
    const booker = PORTFOLIOS.find((p) => String(p.number) === String(form.portfolio));
    const cp = PORTFOLIOS.find((p) => String(p.number) === String(form.counterparty));
    if (!booker || !cp) return null;
    const shortName = (n) => n.split(" - ").pop().trim();
    const bookerShort = shortName(booker.name);
    const cpShort = shortName(cp.name);
    if (form.cf_direction === "OUTGOING") {
      return `PTF ${booker.number} ${bookerShort} FUNDS PTF ${cp.number} ${cpShort} ${form.cf_amount} ${form.cf_asset}`;
    }
    return `PTF ${cp.number} ${cpShort} RETURNED PTF ${booker.number} ${bookerShort} ${form.cf_amount} ${form.cf_asset}`;
  }, [
    form.cf_type, form.cf_direction, form.portfolio, form.counterparty,
    form.cf_amount, form.cf_asset,
  ]);

  // Keep track of the last auto-generated notes string so we can detect manual
  // edits: if notes still equals what we last wrote, we own it and may refresh;
  // once the user changes it, we leave it alone.
  const lastAutoNotesRef = useRef("");
  useEffect(() => {
    if (ipfNotesTemplate == null) {
      // Either left IPF mode or a required input went blank. If notes is still
      // the auto string, clear it; otherwise leave the user's content.
      if (lastAutoNotesRef.current && form.notes === lastAutoNotesRef.current) {
        set("notes", "");
      }
      if (form.cf_type !== "INTER PTF FUNDING") {
        lastAutoNotesRef.current = "";
      }
      return;
    }
    if (form.notes === "" || form.notes === lastAutoNotesRef.current) {
      set("notes", ipfNotesTemplate);
      lastAutoNotesRef.current = ipfNotesTemplate;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ipfNotesTemplate, form.cf_type]);

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
      const cfSignedAmount = form.cf_direction === "OUTGOING" ? -cfMagnitude : cfMagnitude;
      // Key order mirrors trades_cashflow column order exactly. effective_*
      // are server-set on INSERT; emitted here as null placeholders so the
      // JSON shape lines up 1:1 with the table for backend mapping.
      const cfRecord = {
        deal_ref: form.trade_id,
        external_trade_id: form.external_trade_id || null,
        txn_type: "CASHFLOW",
        cashflow_type: form.cf_type || null,
        direction: form.cf_direction,
        // Prefer the live PORTFOLIOS lookup; fall back to the row value
        // captured at amend-load so refdata gaps don't null out entity /
        // portfolio_id / portfolio_name (which would fail NOT NULL checks).
        entity: portfolioEntry?.entity || form.entity_row || null,
        portfolio_id: portfolioEntry ? String(portfolioEntry.number) : (form.portfolio || null),
        portfolio_name: portfolioEntry?.name || form.portfolio_name_row || null,
        counterparty: form.counterparty || null,
        // Immutable refdata id (CID000001 …) so we keep a stable link to
        // reference_data.counterparty even if the name is later renamed.
        // For INTER PTF FUNDING the counterparty field holds a portfolio
        // number (not a refdata name) → COUNTERPARTY_IDS lookup misses
        // and formatCID(undefined) returns null. That's the right shape.
        counterparty_id: formatCID(COUNTERPARTY_IDS[form.counterparty]),
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
          // Loan ↔ cashflow links. Backend's cashflow_insert/amend reads
          // this and writes rows into loan_cashflow_map in the same txn.
          // Only meaningful for LOAN_RELATED_CF_TYPES — for other types
          // the picker is hidden so this stays []. Mirror-leg 2 inherits
          // the same refs (irrelevant in practice — IPF isn't loan-related).
          loan_deal_refs: LOAN_RELATED_CF_TYPES.has(form.cf_type)
            ? (form.cf_loan_deal_refs || []).filter(Boolean)
            : [],
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
          account: form.cf_mirror_account_name || null,
          account_type: form.cf_mirror_account_name ? form.cf_mirror_account_venue_type : null,
          direction: cfRecord.direction === "OUTGOING" ? "INCOMING" : "OUTGOING",
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

    // ─── LOAN: flat, schema-aligned to trades_loan ──────────────────────
    // Every top-level key maps 1:1 to a column in the trades_loan table
    // (see trade-booking/scripts/apply_schema_loan.py). Key order mirrors
    // the DDL column order exactly so the backend can build INSERTs
    // without renaming. UI-only state (loan_term_days, attachments) sits
    // in `_meta` so the backend can strip it cleanly.
    if (form.category === "LOAN") {
      const hasCollateral = !!form.collateral_asset;
      const loanRecord = {
        deal_ref: form.trade_id,
        // Schema column is `order_id` (counterparty's loan reference, e.g.
        // Binance VIP loan ID); React state still calls it
        // external_trade_id to share the input with SPOT/FUTURE/CASHFLOW.
        order_id: form.external_trade_id || null,
        txn_type: "LOAN",
        direction: form.loan_direction,
        loan_type: form.loan_type,
        entity: portfolioEntry?.entity || form.entity_row || null,
        portfolio_id: portfolioEntry ? String(portfolioEntry.number) : (form.portfolio || null),
        portfolio_name: portfolioEntry?.name || form.portfolio_name_row || null,
        counterparty_id: formatCID(COUNTERPARTY_IDS[form.counterparty]),
        counterparty: form.counterparty || null,
        principal_asset: form.principal_asset,
        principal_amount: parseFloat(form.principal_amount) || 0,
        interest_asset: form.interest_asset,
        interest_rate_pa_pct: parseFloat(form.interest_rate) || 0,
        interest_type: form.interest_type,
        day_count_basis: parseInt(form.day_count_basis, 10) || 365,
        floating_benchmark:
          form.interest_type === "FLOATING" ? form.floating_benchmark || null : null,
        // Optional WHT % — NULL when blank so the column stays
        // truly absent rather than storing 0.
        wht_pct: form.wht_pct === "" || form.wht_pct == null
          ? null
          : (parseFloat(form.wht_pct) || 0),
        // trades_loan_collateral_pair CHECK: both NULL or both set.
        collateral_asset: hasCollateral ? form.collateral_asset : null,
        collateral_amount: hasCollateral ? parseFloat(form.collateral_amount) || 0 : null,
        // trades_loan_hedge_consistency CHECK: hedge_* required when is_hedged.
        // hedged_asset is locked to interest_asset by form UX, so we always
        // derive it here rather than trust form.hedged_asset state.
        is_hedged: form.is_hedged,
        hedged_asset: form.is_hedged ? form.interest_asset : null,
        hedged_qty: form.is_hedged ? parseFloat(form.hedged_qty) || 0 : null,
        hedged_price: form.is_hedged ? parseFloat(form.hedged_price) || 0 : null,
        hedge_proceeds_asset: form.is_hedged ? form.hedge_proceeds_asset : null,
        hedge_proceeds_amount:
          form.is_hedged ? parseFloat(form.hedge_proceeds_amount) || 0 : null,
        // form.trade_date is "Start Date"; form.value_date is "Maturity Date"
        // (NULL = open-term).
        trade_date: form.trade_date,
        maturity_date: form.value_date || null,
        effective_start: null,
        effective_end: null,
        user_id: form.created_by || null,
        status: form.status,
        comment: form.notes || null,
        _meta: {
          // Derived in the form for convenience; schema doesn't store it
          // (maturity_date - trade_date is the canonical term).
          loan_term_days: parseInt(form.loan_term_days, 10) || null,
          attachments: form.attachments.map(({ _file, ...rest }) => rest),
        },
      };
      return loanRecord;
    }

    // ─── SPOT: flat, schema-aligned for future trades_spot ──────────────
    // Key order is the proposed trades_spot column order (see
    // trade-booking/docs/spot-schema-mapping.md). The target table doesn't
    // exist yet — when it lands, mirror this ordering in
    // apply_schema_spot.py and keep this branch and the DDL in sync.
    if (form.category === "SPOT") {
      const spotRecord = {
        deal_ref: form.trade_id,
        external_trade_id: form.external_trade_id || null,
        txn_type: "SPOT",
        direction: form.spot_direction,
        entity: portfolioEntry?.entity || form.entity_row || null,
        portfolio_id: portfolioEntry ? String(portfolioEntry.number) : (form.portfolio || null),
        portfolio_name: portfolioEntry?.name || form.portfolio_name_row || null,
        counterparty: form.counterparty || null,
        counterparty_id: formatCID(COUNTERPARTY_IDS[form.counterparty]),
        account: form.account_name || null,
        account_type: form.account_venue_type,
        base_asset: form.base_asset,
        base_amount: parseFloat(form.base_amount) || 0,
        quote_asset: form.quote_asset,
        quote_amount: parseFloat(form.quote_amount) || 0,
        price: parseFloat(form.price) || 0,
        fee_asset: form.fee_asset,
        fee_amount: parseFloat(form.fee_amount) || 0,
        trade_date: form.trade_date,
        value_date: form.value_date,
        txid_reference: form.tx_hash || null,
        effective_start: null,
        effective_end: null,
        user_id: form.created_by || null,
        status: form.status,
        comment: form.notes || null,
        _meta: {
          attachments: form.attachments.map(({ _file, ...rest }) => rest),
        },
      };
      return spotRecord;
    }

    // ─── FUTURE: legacy base+payload split ──────────────────────────────
    // Target table hasn't been designed yet, so the JSON keeps a
    // form-driven shape until the schema is nailed down.
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
    if (form.category === "FUTURE") {
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
  // Guard against double-submits: a fast double-click (or a finger
  // bouncing on the button) would fire two POSTs before the first
  // returned, allocating two consecutive deal_refs from the sequence.
  // Flips true on submit start, back to false in finally.
  const [isSubmitting, setIsSubmitting] = useState(false);
  // null | { dealRef: string, message: string }
  const [conflictModal, setConflictModal] = useState(null);
  // null | "MCF-42"  — when set, form is in amend mode (PUT vs POST)
  const [amendingDealRef, setAmendingDealRef] = useState(null);
  // Snapshot of form + categoryCache taken right before an Amend opens.
  // The Amend modal overlays the user's in-progress Create Deal draft;
  // on close we restore the snapshot so the draft survives. Cleared
  // after restore and on successful submit. Only set when transitioning
  // from "no amend" → "amend", not on conflict-modal reloads (which
  // re-enter loadIntoForm while already in amend mode).
  const formSnapshotRef = useRef(null);
  // Top-level success notice that survives modal close. Auto-clears
  // after 4s. null | { message: string }
  const [toast, setToast] = useState(null);
  // Bumped after a successful insert/amend so the Deal Enquiry table
  // re-fetches its rows on the next render.
  const [dealEnquiryRefreshSignal, setDealEnquiryRefreshSignal] = useState(0);
  // null | { dealRef, rows, loading, error } — drives HistoryModal
  const [historyModal, setHistoryModal] = useState(null);
  // null | { dealRef, loan, loading, error } — drives LoanScheduleModal
  const [loanScheduleModal, setLoanScheduleModal] = useState(null);

  async function openLoanSchedule(dealRef) {
    setLoanScheduleModal({ dealRef, loan: null, loading: true, error: null });
    let res;
    try {
      res = await api(`/api/loan/${encodeURIComponent(dealRef)}`);
    } catch (e) {
      setLoanScheduleModal({ dealRef, loan: null, loading: false, error: String(e) });
      return;
    }
    const result = await res.json().catch(() => ({ ok: false, error: "non-JSON server response" }));
    if (!result.ok) {
      setLoanScheduleModal({ dealRef, loan: null, loading: false, error: result.error || "Failed to load loan" });
      return;
    }
    setLoanScheduleModal({ dealRef, loan: result.rows[0], loading: false, error: null });
  }

  // When the user clicks a cashflow ref inside the loan schedule, fetch
  // the cashflow row and open it in the form for amend (same UX as
  // clicking a row in Deal Enquiry).
  async function openCashflowFromSchedule(cashflowDealRef) {
    // loadIntoForm already dispatches on the deal_ref prefix → /api/cashflow/:ref
    setLoanScheduleModal(null);
    await loadIntoForm(cashflowDealRef);
  }

  // "+ Book Cashflow" from the Loan Schedule modal — opens the Cashflow
  // form pre-populated with the loan's portfolio/counterparty/interest_asset
  // and the loan tagged in the picker. Snapshots the current draft first
  // so closing without submit restores the user's in-progress work
  // (same pattern as Amend overlay).
  function openCashflowBookingForLoan(loan) {
    if (!loan) return;
    formSnapshotRef.current = { form, categoryCache };
    // Direction-aware defaults: BORROW → INTEREST EXPENSE OUTGOING (you
    // pay interest); LEND → INTEREST INCOME INCOMING (you receive).
    // User can change cf_type to LOAN / LOAN REPAYMENT etc. if they're
    // booking a different leg of the loan lifecycle.
    const isLend = loan.direction === "LEND";
    const cfType = isLend ? "INTEREST INCOME" : "INTEREST EXPENSE";
    const cfDirection = isLend ? "INCOMING" : "OUTGOING";
    const interestAsset = loan.interest_asset || "USDT";
    setForm({
      ...initial(),
      category: "CASHFLOW",
      portfolio: String(loan.portfolio_id || ""),
      counterparty: loan.counterparty || "",
      cf_type: cfType,
      cf_direction: cfDirection,
      cf_asset: interestAsset,
      fee_asset: interestAsset,
      cf_loan_deal_refs: [loan.deal_ref],
    });
    setCategoryCache({});
    setLoanScheduleModal(null);
    setAmendingDealRef(null);
    setCreateDealOpen(true);
  }

  async function openHistory(dealRef) {
    setHistoryModal({ dealRef, rows: [], loading: true, error: null });
    const product = productFromDealRef(dealRef);
    const base = product === "LOAN" ? "loan" : product === "SPOT" ? "spot" : "cashflow";
    let res;
    try {
      res = await api(`/api/${base}/${encodeURIComponent(dealRef)}/history`);
    } catch (e) {
      setHistoryModal({ dealRef, rows: [], loading: false, error: String(e) });
      return;
    }
    const result = await res.json().catch(() => ({ ok: false, error: "non-JSON server response" }));
    if (!result.ok) {
      setHistoryModal({ dealRef, rows: [], loading: false, error: result.error || "Failed to load history" });
      return;
    }
    setHistoryModal({ dealRef, rows: result.rows, loading: false, error: null });
  }

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
      // Guard against null/undefined → "null"/"undefined" strings. The
      // backend returns portfolio_id as a string already, but a missing
      // value should land as "" (form's default), not a literal "null".
      portfolio: row.portfolio_id != null ? String(row.portfolio_id) : "",
      // Capture the display fields straight from the row so the pickers
      // don't have to wait on the refdata fetch. The refdata is still
      // the source of truth for new bookings; these fields are only
      // fallbacks for the picker label when refdata is unavailable.
      portfolio_name_row: row.portfolio_name || "",
      // Fallback for the readonly Entity input when PORTFOLIOS refdata
      // doesn't include this portfolio (or hasn't loaded yet).
      entity_row: row.entity || "",
      counterparty_id_row: row.counterparty_id || "",
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
      // Don't copy row.user_id into created_by — the form's created_by
      // represents WHO IS DOING THIS ACTION NOW (the amender), not the
      // original author. Copying the original leaks the prior author's
      // identity into the JSON preview and submit payload; server.js
      // stampUserId() rewrites it back to the session user before
      // persistence, so DB rows are still correct, but the UI preview
      // was confusing. Leaving created_by untouched preserves whatever
      // the session-user useEffect set it to.
      status: row.status,
      notes: row.comment || "",
      // Pre-fill the loan picker from joined mappings (server attaches
      // `mappings: [{counterpart_deal_ref, mapping_type, mapped_amount}]`).
      cf_loan_deal_refs: (row.mappings || []).map((m) => m.counterpart_deal_ref).filter(Boolean),
    };
  }

  // Inverse of outputRecord for category="LOAN". Maps a backend
  // trades_loan row back into form-state keys.
  function loanPayloadToFormState(row) {
    return {
      category: "LOAN",
      trade_id: row.deal_ref,
      // Schema column is order_id; form state reuses external_trade_id.
      external_trade_id: row.order_id || "",
      loan_direction: row.direction,
      loan_type: row.loan_type,
      portfolio: row.portfolio_id != null ? String(row.portfolio_id) : "",
      // Fallbacks from the row so pickers can render without waiting
      // for the refdata fetch to complete.
      portfolio_name_row: row.portfolio_name || "",
      entity_row: row.entity || "",
      counterparty_id_row: row.counterparty_id || "",
      counterparty: row.counterparty || "",
      principal_asset: row.principal_asset,
      principal_amount: row.principal_amount == null ? "" : String(row.principal_amount),
      interest_asset: row.interest_asset,
      interest_rate: row.interest_rate_pa_pct == null ? "" : String(row.interest_rate_pa_pct),
      interest_type: row.interest_type,
      day_count_basis: row.day_count_basis ?? 365,
      floating_benchmark: row.floating_benchmark || "",
      wht_pct: row.wht_pct == null ? "" : String(row.wht_pct),
      collateral_asset: row.collateral_asset || "",
      collateral_amount: row.collateral_amount == null ? "" : String(row.collateral_amount),
      is_hedged: !!row.is_hedged,
      // If the loaded row is unhedged (hedged_asset NULL), preseed the
      // picker with the loan's interest_asset so flipping is_hedged on
      // starts at the typical default rather than a random "BTC".
      hedged_asset: row.hedged_asset || row.interest_asset || "USDT",
      hedged_qty: row.hedged_qty == null ? "" : String(row.hedged_qty),
      hedged_price: row.hedged_price == null ? "" : String(row.hedged_price),
      hedge_proceeds_asset: row.hedge_proceeds_asset || "USDT",
      hedge_proceeds_amount:
        row.hedge_proceeds_amount == null ? "" : String(row.hedge_proceeds_amount),
      // Loan-specific naming for the date pair: trade_date=Start, maturity_date=Maturity.
      trade_date: row.trade_date,
      value_date: row.maturity_date || "",
      // loan_term_days is derived in the form; clear so the open-term
      // input shows blank unless the user re-enters a term.
      loan_term_days: "",
      // created_by intentionally NOT copied from row.user_id; see the
      // matching note in payloadToFormState (cashflow).
      status: row.status,
      notes: row.comment || "",
    };
  }

  // Inverse of outputRecord for category="SPOT". Maps a backend
  // trades_spot row back into form-state keys.
  function spotPayloadToFormState(row) {
    // If the stored counterparty matches a portfolio number, this was
    // booked as an internal SPOT — restore the Internal checkbox so the
    // counterparty picker re-renders as a PortfolioPicker.
    const isInternal = !!(
      row.counterparty &&
      PORTFOLIOS.some((p) => String(p.number) === String(row.counterparty))
    );
    return {
      category: "SPOT",
      trade_id: row.deal_ref,
      external_trade_id: row.external_trade_id || "",
      spot_direction: row.direction,
      spot_internal: isInternal,
      portfolio: row.portfolio_id != null ? String(row.portfolio_id) : "",
      portfolio_name_row: row.portfolio_name || "",
      entity_row: row.entity || "",
      counterparty_id_row: row.counterparty_id || "",
      counterparty: row.counterparty || "",
      account_name: row.account || "",
      account_venue_type: row.account_type || "",
      base_asset: row.base_asset,
      base_amount: row.base_amount == null ? "" : String(row.base_amount),
      quote_asset: row.quote_asset,
      quote_amount: row.quote_amount == null ? "" : String(row.quote_amount),
      price: row.price == null ? "" : String(row.price),
      fee_asset: row.fee_asset || "",
      fee_amount: row.fee_amount == null ? "0" : String(row.fee_amount),
      trade_date: row.trade_date,
      value_date: row.value_date,
      tx_hash: row.txid_reference || "",
      // created_by intentionally NOT copied from row.user_id; see the
      // matching note in payloadToFormState (cashflow).
      status: row.status,
      notes: row.comment || "",
    };
  }

  // Deal-ref prefix routes to the right product backend.
  // MCF → cashflow (trade_seq_cashflow), MLA → loan (trade_seq_loan),
  // MFX → spot (trade_seq_spot).
  function productFromDealRef(dealRef) {
    if (typeof dealRef === "string" && dealRef.startsWith("MLA")) return "LOAN";
    if (typeof dealRef === "string" && dealRef.startsWith("MFX")) return "SPOT";
    return "CASHFLOW";
  }

  // Synchronous: row data is already in hand (Deal Enquiry already
  // fetched the recent list). No network round-trip on row click.
  function loadRowIntoForm(row) {
    setFeedback(null);
    // Snapshot the existing draft before overwriting — but only if
    // we're entering amend mode fresh. Conflict-modal "Reload" calls
    // this while already in amend mode; in that case the snapshot
    // already represents the pre-amend draft and we shouldn't clobber
    // it with the now-amended state.
    if (!amendingDealRef) {
      formSnapshotRef.current = { form, categoryCache };
    }
    const product =
      row.txn_type === "LOAN" ? "LOAN"
      : row.txn_type === "SPOT" ? "SPOT"
      : "CASHFLOW";
    setMany(
      product === "LOAN" ? loanPayloadToFormState(row)
      : product === "SPOT" ? spotPayloadToFormState(row)
      : payloadToFormState(row)
    );
    setAmendingDealRef(row.deal_ref);
    // Don't change view — if the user is on Deal Enquiry, the form opens
    // as a modal (see ModalShell wrapper); if they're already on
    // Trade Input, the form is already visible inline.
  }

  // Async: re-fetches the live row by deal_ref. Used by the conflict
  // modal's Reload button, where the cached copy is known to be stale.
  async function loadIntoForm(dealRef) {
    setFeedback(null);
    const product = productFromDealRef(dealRef);
    const base = product === "LOAN" ? "loan" : product === "SPOT" ? "spot" : "cashflow";
    let res;
    try {
      res = await api(`/api/${base}/${encodeURIComponent(dealRef)}`);
    } catch (e) {
      setFeedback({ kind: "error", message: "Server unreachable", detail: String(e) });
      return;
    }
    const result = await res.json().catch(() => ({ ok: false, error: "non-JSON server response" }));
    if (!result.ok) {
      setFeedback({ kind: "error", message: result.error || "Failed to load deal" });
      return;
    }
    loadRowIntoForm(result.rows[0]);
  }

  const handleSubmit = async () => {
    if (form.category !== "CASHFLOW" && form.category !== "LOAN" && form.category !== "SPOT") {
      // FUTURE: not wired to backend yet — keep the existing JSON
      // preview behavior so that form still works.
      if (!canSubmit) return;
      setSubmittedRecord(outputRecord);
      return;
    }
    if (!canSubmit) return;
    if (isSubmitting) return;  // bail on duplicate clicks while in-flight
    setIsSubmitting(true);
    setFeedback(null);
    const base =
      form.category === "LOAN" ? "loan"
      : form.category === "SPOT" ? "spot"
      : "cashflow";
    const endpoint = amendingDealRef
      ? `/api/${base}/amend`
      : `/api/${base}/insert`;
    try {
      let res;
      try {
        res = await api(endpoint, {
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
        const verb = amendingDealRef ? "updated" : "booked";
        const refs = result.rows.map((r) => r.deal_ref);
        const label = refs.length > 1 ? `Deals ${refs.join(" + ")}` : `Deal ${refs[0]}`;
        setAmendingDealRef(null);          // closes the amend modal (if open)
        setCreateDealOpen(false);           // closes the create modal (if open)
        setFeedback(null);                  // clear any prior inline error
        setForm(initial());                 // fresh form, default category SPOT
        setCategoryCache({});               // drop any other-product drafts too
        formSnapshotRef.current = null;     // submitted — pre-amend draft no longer relevant
        setToast({ message: `${label} ${verb}` });
        setDealEnquiryRefreshSignal((s) => s + 1);   // table refetches
        refreshLiveLoans();                          // picker sees the new loan
        setTimeout(() => setToast(null), 4000);
      } else if (res.status === 409) {
        setConflictModal({ dealRef: amendingDealRef, message: result.error });
      } else {
        setFeedback({ kind: "error", message: result.error || "Booking failed", detail: result.detail });
      }
    } finally {
      setIsSubmitting(false);
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
      spot_internal: false,
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
      cf_direction: "OUTGOING",
      cf_type: "",
      cf_mirror: false,
      cf_mirror_account_venue_type: "EXCHANGE",
      cf_mirror_account_name: "",
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
      loan_type: "VIP LOAN",
      loan_term_days: "",
      principal_asset: "USDT",
      interest_asset: "USDT",
      principal_amount: "",
      interest_rate: "",
      interest_type: "FIXED",
      floating_benchmark: "",
      wht_pct: "",
      collateral_asset: "",
      collateral_amount: "",
      is_hedged: false,
      hedged_asset: "USDT",
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

  if (appView === "tokens") {
    return <ApiTokens onClose={() => setAppView("booking")} />;
  }

  if (appView === "users" && user?.role === "admin") {
    return <UserAdmin onClose={() => setAppView("booking")} />;
  }

  return (
    <TokensContext.Provider value={liveTokens}>
    <div
      className="h-screen flex flex-col overflow-hidden"
      style={{
        background: BB.bg,
        color: BB.text,
        fontFamily: "'IBM Plex Mono', ui-monospace, monospace",
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
            className="text-[9px] tracking-[0.34em] uppercase font-mono"
            style={{ color: "#9a9488", fontWeight: 400, paddingLeft: 1 }}
          >
            Trade Management System
          </span>
        </div>

        {/* RIGHT — minimal indicator dots. Full status surfaces on hover via
            HoverTip (instant, no browser title-attribute delay). Left dot =
            environment (PROD/UAT derived from hostname). Right dot = refdata
            sync state; click to re-sync. */}
        <div className="flex items-center gap-3">
          {/* ENV dot */}
          <HoverTip text={`ENV: ${env}`} placement="bottom">
            <span
              aria-label={`Environment: ${env}`}
              className="inline-block"
              style={{
                width: 10,
                height: 10,
                borderRadius: "50%",
                background: env === "PROD" ? BB.green : "#1f63ea",
                boxShadow: `0 0 8px ${env === "PROD" ? BB.green : "#1f63ea"}`,
              }}
            />
          </HoverTip>

          {/* REFDATA dot — click to re-sync MySQL refdata */}
          <HoverTip
            placement="bottom"
            text={
              refdataError
                ? `REFDATA: error — ${refdataError}`
                : refdataLoading
                ? "REFDATA: syncing…"
                : refdataLastAt
                ? `REFDATA: ${refdataLastAt.toLocaleTimeString()} · click to re-sync`
                : "REFDATA: click to load"
            }
          >
            <button
              type="button"
              onClick={refreshRefdata}
              disabled={refdataLoading}
              aria-label="Refresh reference data"
              className="flex items-center transition-opacity hover:opacity-80"
              style={{
                background: "transparent",
                border: "none",
                padding: 4,
                opacity: refdataLoading ? 0.55 : 1,
                cursor: refdataLoading ? "wait" : "pointer",
              }}
            >
              <span
                aria-hidden
                className="inline-block"
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: "50%",
                  background: refdataError ? BB.red : refdataLoading ? "#1f63ea" : BB.green,
                  boxShadow: `0 0 8px ${refdataError ? BB.red : refdataLoading ? "#1f63ea" : BB.green}`,
                }}
              />
            </button>
          </HoverTip>

          <span aria-hidden className="h-4 w-px" style={{ background: "#3a3834" }} />

          {/* UTC date · time */}
          <div className="flex items-baseline gap-2 text-[10px] tracking-[0.22em] uppercase font-mono">
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
            {/* Primary action — opens the Create Deal modal */}
            <div className="px-5 pb-3">
              <button
                type="button"
                // No reset on open — the in-progress Create Deal draft
                // is preserved across modal close+reopen. Reset only
                // fires on a successful submit (see handleSubmit). If
                // the user comes from an Amend, the snapshot/restore
                // logic in loadRowIntoForm already restored the draft
                // before this point.
                onClick={() => setCreateDealOpen(true)}
                className="w-full py-2.5 text-[12px] font-medium uppercase tracking-[0.22em] transition-colors font-mono flex items-center justify-center gap-2"
                style={{
                  background: BB.text,
                  color: "#f2efe8",
                  border: `1px solid ${BB.text}`,
                  cursor: "pointer",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = BB.orange;
                  e.currentTarget.style.borderColor = BB.orange;
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = BB.text;
                  e.currentTarget.style.borderColor = BB.text;
                }}
              >
                + Create Deal
              </button>
            </div>

            {/* Separator between primary action and standalone items */}
            <div
              className="mx-5 mb-2"
              style={{ borderTop: `1px dashed #d9d4c7` }}
            />

            <NavTabRow
              label="Deal Enquiry"
              active={view === "DEAL_ENQUIRY"}
              onClick={() => setView("DEAL_ENQUIRY")}
            />
            <NavTabRow
              label="Loan Enquiry"
              active={view === "LOAN_ENQUIRY"}
              onClick={() => setView("LOAN_ENQUIRY")}
            />
            <NavTabRow
              label="Pending Bookings"
              active={view === "PENDING_BOOKINGS"}
              onClick={() => setView("PENDING_BOOKINGS")}
            />

            {user?.role === "admin" && (
              <>
                {/* Separator before the admin-only section */}
                <div
                  className="mx-5 my-2"
                  style={{ borderTop: `1px dashed #d9d4c7` }}
                />
                <NavTabRow
                  label="Users"
                  active={appView === "users"}
                  onClick={() => setAppView("users")}
                />
              </>
            )}

            <NavTabRow
              label="API Tokens"
              active={appView === "tokens"}
              onClick={() => setAppView("tokens")}
            />
          </div>

          {/* ─── User profile footer (clock lives in the top banner) ─── */}
          {(() => {
            // Identity + role come from the session (useAuth), not from
            // USER_PROFILES which is built from the MySQL refdata mirror
            // and would miss any locally-created auth users.
            const displayName = user?.username
              ? user.username
                  .split(".")
                  .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
                  .join(" ")
              : form.created_by || "—";
            const profile = {
              name: displayName,
              role: user?.role || "user",
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
                <button
                  type="button"
                  onClick={logout}
                  title="Log out"
                  className="w-full text-[9px] tracking-[0.2em] uppercase font-mono py-2 mt-3 transition-colors"
                  style={{
                    color: BB.mute,
                    background: "transparent",
                    border: `1px solid ${BB.border}`,
                    cursor: "pointer",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.color = BB.text;
                    e.currentTarget.style.borderColor = BB.text;
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.color = BB.mute;
                    e.currentTarget.style.borderColor = BB.border;
                  }}
                >
                  LOG OUT
                </button>
              </div>
            );
          })()}
        </aside>

        {/* ─── MAIN PANEL ─── */}
        <main className="flex-1 min-w-0 overflow-y-auto">
          {view === "DEAL_ENQUIRY" && (
            <DealEnquiry
              BB={BB}
              onSelect={(row) => loadRowIntoForm(row)}
              onHistory={(dealRef) => openHistory(dealRef)}
              onMappingClick={(loanDealRef) => openLoanSchedule(loanDealRef)}
              refreshSignal={dealEnquiryRefreshSignal}
            />
          )}
          {view === "LOAN_ENQUIRY" && (
            <LoanEnquiry
              BB={BB}
              // Clicking the deal_ref opens the schedule modal (the
              // canonical "view a loan" surface). The modal exposes an
              // Amend button that re-routes to the form.
              onSelect={(row) => openLoanSchedule(row.deal_ref)}
              onHistory={(dealRef) => openHistory(dealRef)}
              refreshSignal={dealEnquiryRefreshSignal}
            />
          )}
          {view === "PENDING_BOOKINGS" && (
            <PlaceholderView
              title="Pending Bookings"
              subtitle="Bookings awaiting approval, attached documentation, or settlement confirmation. Approve, reject, or amend from here. Coming soon."
            />
          )}
          {form.category !== "FUTURE" && (
      <ModalShell
        open={createDealOpen || Boolean(amendingDealRef)}
        onClose={() => {
          // A snapshot exists when the form was overlaid with "other"
          // data — either an Amend row OR a loan-pre-filled Cashflow
          // booking. Either way, restore the user's prior draft on
          // close so their in-progress Create Deal survives. Pure
          // Create Deal opens take no snapshot, so close just leaves
          // the form untouched (continues from where they left off).
          if (formSnapshotRef.current) {
            setForm(formSnapshotRef.current.form);
            setCategoryCache(formSnapshotRef.current.categoryCache);
          }
          formSnapshotRef.current = null;
          setCreateDealOpen(false);
          setAmendingDealRef(null);
          setFeedback(null);
        }}
      >
      <ProductTabs
        active={form.category}
        onChange={(k) => switchCategory(k)}
        locked={Boolean(amendingDealRef)}
      />
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
            <Field label="Internal Trade ID" span={6}>
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
            <Field label={form.category === "LOAN" ? "Order ID" : "External Trade ID (optional)"} span={6}>
              <Input
                placeholder={form.category === "LOAN" ? "" : "exchange order id / counterparty ref / 0x…"}
                value={form.external_trade_id}
                onChange={(e) => set("external_trade_id", e.target.value)}
              />
            </Field>
            {form.category === "LOAN" ? (
              <>
                <Field label="Start Date" required span={3}>
                  <DatePicker
                    value={(form.trade_date || "").slice(0, 10)}
                    onChange={(v) => setLoanField("trade_date", v)}
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
                  <DatePicker
                    value={(form.value_date || "").slice(0, 10)}
                    onChange={(v) => setLoanField("value_date", v)}
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
            <Field label="Created By" required span={4}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 10px", background: "#0a0a0a", border: "1px solid #1f1f1f" }}>
                <span style={{ fontSize: 11, color: "#7d7d7d", letterSpacing: 1 }}>BOOKED BY</span>
                <span style={{ fontSize: 13, color: "#e5e5e5", fontFamily: "'IBM Plex Mono', ui-monospace, monospace" }}>{user?.username || "—"}</span>
              </div>
            </Field>
            {form.category === "CASHFLOW" && (
              <>
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
                      const wasLoanRelated = LOAN_RELATED_CF_TYPES.has(form.cf_type);
                      const nowLoanRelated = LOAN_RELATED_CF_TYPES.has(nextType);
                      // Drop any loan picker selections when the new type
                      // isn't loan-related — keeps stale mapping refs from
                      // shipping in _meta.
                      const patch = { cf_type: nextType };
                      if (wasIPF !== nowIPF) {
                        Object.assign(patch, {
                          counterparty: "",
                          cf_mirror: false,
                          cf_mirror_account_name: "",
                          cf_mirror_account_venue_type: "EXCHANGE",
                        });
                      }
                      if (wasLoanRelated && !nowLoanRelated) {
                        patch.cf_loan_deal_refs = [];
                      }
                      setMany(patch);
                    }}
                  >
                    <option value="">— select —</option>
                    {CASHFLOW_TYPES.map((x) => (
                      <option key={x}>{x}</option>
                    ))}
                  </Select>
                </Field>
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
                ) : LOAN_RELATED_CF_TYPES.has(form.cf_type) ? (
                  (() => {
                    // Picker options = live loans (effective_end IS NULL)
                    // filtered to the cashflow's selected portfolio. If
                    // portfolio is blank we show everything so the user
                    // can preview; the filter snaps once they pick one.
                    const onPortfolio = form.portfolio
                      ? liveLoans.filter((l) => String(l.portfolio_id) === String(form.portfolio))
                      : liveLoans;
                    // Asset-compatibility filter: once one loan is picked,
                    // hide loans whose locking-asset would conflict (so the
                    // user can never end up in a "mixed assets" state).
                    // cfAssetLock=="" means no lock yet (zero picked or all
                    // candidate loans agree); cfAssetLock=null means
                    // existing picks already conflict — show everything so
                    // the user can recover by removing one.
                    const useInterest =
                      form.cf_type === "INTEREST EXPENSE" || form.cf_type === "INTEREST INCOME";
                    const eligible = cfAssetLock
                      ? onPortfolio.filter((l) => {
                          const a = useInterest ? l.interest_asset : l.principal_asset;
                          return a === cfAssetLock;
                        })
                      : onPortfolio;
                    return (
                      <Field label="Linked Loans (optional)" span={8}>
                        <LoanPicker
                          selected={form.cf_loan_deal_refs || []}
                          onChange={(next) => set("cf_loan_deal_refs", next)}
                          options={eligible}
                        />
                        {form.portfolio && eligible.length === 0 && (
                          <div
                            className="text-[10px] mt-1 font-mono"
                            style={{ color: BB.mute || "#6a665c" }}
                          >
                            {cfAssetLock
                              ? `No more live loans on portfolio ${form.portfolio} in ${cfAssetLock}.`
                              : `No live loans on portfolio ${form.portfolio} — book the loan first if needed.`}
                          </div>
                        )}
                        {cfAssetLock === null && (
                          <div
                            className="text-[10px] mt-1 font-mono"
                            style={{ color: "#a23b1a" }}
                          >
                            ⚠ Linked loans use different assets — remove one to continue.
                          </div>
                        )}
                      </Field>
                    );
                  })()
                ) : (
                  <div className="col-span-8" />
                )}
              </>
            )}
            <Field label="Portfolio" required span={6}>
              <PortfolioPicker
                value={form.portfolio}
                onChange={(v) =>
                  // Clear the row-side fallback once the user picks a new
                  // portfolio — the refdata lookup is now authoritative.
                  setMany({ portfolio: v, account_name: "", portfolio_name_row: "" })
                }
                options={PORTFOLIOS}
                fallbackLabel={form.portfolio_name_row}
              />
            </Field>
            <Field label="Entity (auto from portfolio)" span={6}>
              <Input
                value={
                  PORTFOLIOS.find(
                    (p) => String(p.number) === String(form.portfolio)
                  )?.entity || form.entity_row || ""
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
              headerExtra={
                form.category === "SPOT" ? (
                  <label
                    className="text-[10px] cursor-pointer flex items-center gap-1.5 font-mono"
                    style={{ color: BB.text }}
                  >
                    <input
                      type="checkbox"
                      checked={form.spot_internal}
                      onChange={(e) =>
                        setMany({
                          spot_internal: e.target.checked,
                          counterparty: "",
                          counterparty_id_row: "",
                        })
                      }
                      style={{ accentColor: BB.orange }}
                    />
                    Internal
                  </label>
                ) : null
              }
            >
              {(form.category === "CASHFLOW" && form.cf_type === "INTER PTF FUNDING") ||
               (form.category === "SPOT" && form.spot_internal) ? (
                <PortfolioPicker
                  value={form.counterparty}
                  onChange={(v) =>
                    setMany({
                      counterparty: String(v),
                      cf_mirror_account_name: "",
                      counterparty_id_row: "",
                    })
                  }
                  options={PORTFOLIOS.filter(
                    (p) => String(p.number) !== String(form.portfolio)
                  )}
                  fallbackLabel={
                    // Counterparty on an internal-counterparty row (INTER PTF
                    // FUNDING cashflow or internal SPOT) is a portfolio number —
                    // try to label it from the refdata lookup name first, else
                    // stay quiet.
                    (PORTFOLIOS.find((p) => String(p.number) === String(form.counterparty))?.name) || ""
                  }
                />
              ) : (
                <CounterpartyPicker
                  value={form.counterparty}
                  onChange={(v) => setMany({ counterparty: v, counterparty_id_row: "" })}
                  options={
                    form.category === "LOAN"
                      ? COUNTERPARTIES.filter((c) => c.type === "LENDER")
                      : COUNTERPARTIES
                  }
                  fallbackLabel={form.counterparty_id_row}
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
                  <DatePicker
                    value={form.fut_expiry}
                    onChange={(v) => set("fut_expiry", v)}
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
              accent={form.cf_direction === "INCOMING" ? BB.green : BB.red}
            >
              {/* Direction — INCOMING / OUTGOING toggle */}
              <Field label="Direction" required span={12}>
                <div className="flex gap-2">
                  {CASHFLOW_DIRECTIONS.map((d) => {
                    const active = form.cf_direction === d;
                    const tone = d === "INCOMING" ? BB.green : BB.red;
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

              <Field label="Notional Asset" required span={3}>
                <AssetPicker
                  value={form.cf_asset}
                  // Lock the asset when a loan link constrains it.
                  // The auto-sync useEffect above keeps cf_asset in sync;
                  // disabling the picker just stops the user from changing
                  // it back to something incompatible.
                  disabled={!!cfAssetLock}
                  onChange={(v) => {
                    // Fee Asset trails Notional Asset until the user customizes it.
                    // We detect "uncustomized" by checking whether fee_asset still
                    // matches the prior cf_asset; if so, sync to the new value.
                    setForm((f) => ({
                      ...f,
                      cf_asset: v,
                      fee_asset: f.fee_asset === f.cf_asset ? v : f.fee_asset,
                      last_modified_at: isoNow(),
                    }));
                  }}
                />
                {cfAssetLock && (
                  <div
                    className="text-[10px] mt-1 font-mono"
                    style={{ color: BB.mute || "#6a665c" }}
                  >
                    Locked to {cfAssetLock} by {(form.cf_loan_deal_refs || []).join(", ")}
                  </div>
                )}
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

              {form.cf_type === "INTER PTF FUNDING" && form.cf_mirror && (
                <>
                  <Field label="Mirror Account Type" required span={4}>
                    <Select
                      value={form.cf_mirror_account_venue_type}
                      onChange={(e) =>
                        setMany({
                          cf_mirror_account_venue_type: e.target.value,
                          cf_mirror_account_name: "",
                        })
                      }
                    >
                      {ACCOUNT_VENUE_TYPES.map((v) => (
                        <option key={v.key} value={v.key}>
                          {v.label}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="Mirror Account Name" required span={8}>
                    <AccountPicker
                      value={form.cf_mirror_account_name}
                      onChange={(v) => set("cf_mirror_account_name", v)}
                      options={mirrorAccountOptions}
                      placeholder={
                        !form.counterparty
                          ? "— select counterparty portfolio first —"
                          : mirrorAccountOptions.length === 0
                          ? "— no accounts for this portfolio + venue —"
                          : "— select account —"
                      }
                    />
                  </Field>
                </>
              )}

              <Field label="Network" span={4}>
                <Select value={form.network} onChange={(e) => set("network", e.target.value)}>
                  <option value="">— off-chain —</option>
                  {NETWORKS.map((x) => (
                    <option key={x}>{x}</option>
                  ))}
                </Select>
              </Field>
              <Field label="Tx Hash (optional)" span={8}>
                <div className="flex gap-2 items-stretch">
                  <Input
                    placeholder="0x… (on-chain hash, if applicable)"
                    value={form.tx_hash}
                    onChange={(e) => {
                      set("tx_hash", e.target.value);
                      setTxFetchError(null);
                      setTxFetchResult(null);
                      setTxFetchSuccess(null);
                    }}
                  />
                  {(() => {
                    const disabledReason = fetchButtonDisabledReason(form.network, form.tx_hash);
                    return (
                      <button
                        type="button"
                        onClick={handleFetchTx}
                        disabled={txFetchLoading || disabledReason !== null}
                        title={disabledReason || "Fetch on-chain details"}
                        className="px-3 py-1 text-[11px] font-mono tracking-[0.12em] uppercase transition-colors flex items-center gap-1 whitespace-nowrap"
                        style={{
                          background: txFetchLoading || disabledReason !== null ? BB.surface2 : BB.orange,
                          color: txFetchLoading || disabledReason !== null ? BB.faint : "#ffffff",
                          border: `1px solid ${txFetchLoading || disabledReason !== null ? BB.border : BB.orange}`,
                          cursor: txFetchLoading || disabledReason !== null ? "not-allowed" : "pointer",
                        }}
                      >
                        {txFetchLoading
                          ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Fetching…</>
                          : "Fetch"}
                      </button>
                    );
                  })()}
                </div>
                {txFetchError && (
                  <div className="text-[11px] mt-1 font-mono" style={{ color: BB.red }}>
                    {txFetchError}
                  </div>
                )}
                {txFetchSuccess && (
                  <div className="text-[11px] mt-1 font-mono" style={{ color: BB.green }}>
                    {txFetchSuccess}
                  </div>
                )}
                {txFetchResult && txFetchResult.transfers && txFetchResult.transfers.length > 1 && (
                  <div className="mt-2 rounded p-2" style={{ background: BB.surface, border: `1px solid ${BB.border}` }}>
                    <div className="text-[11px] font-mono mb-1" style={{ color: BB.mute }}>
                      Multiple transfers in this tx — pick the one to import:
                    </div>
                    <ul className="space-y-1">
                      {txFetchResult.transfers.map((t, i) => {
                        const resolutions = txFetchResult.resolutions || {};
                        const fromR = resolutions[(t.from || "").toLowerCase()];
                        const toR = resolutions[(t.to || "").toLowerCase()];
                        return (
                        <li key={i} className="flex items-center justify-between">
                          <span className="text-[11px] font-mono" style={{ color: BB.text }}>
                            <span style={{ color: BB.yellow }}>{t.amount}</span>{" "}{t.asset}
                            <span style={{ color: BB.faint }}>
                              {" "}— {shortAddr(t.from)}{fromR ? ` (${fromR.owner})` : ""}
                              {" "}→ {shortAddr(t.to)}{toR ? ` (${toR.owner})` : ""}
                            </span>
                          </span>
                          <button
                            type="button"
                            onClick={() => { applyAutofill(t, txFetchResult); setTxFetchResult(null); }}
                            className="ml-2 px-2 py-0.5 text-[11px] font-mono tracking-[0.1em] uppercase transition-colors whitespace-nowrap"
                            style={{ background: BB.orange, color: "#ffffff", border: `1px solid ${BB.orange}`, cursor: "pointer" }}
                            onMouseEnter={(ev) => { ev.currentTarget.style.background = BB.amber; ev.currentTarget.style.borderColor = BB.amber; }}
                            onMouseLeave={(ev) => { ev.currentTarget.style.background = BB.orange; ev.currentTarget.style.borderColor = BB.orange; }}
                          >
                            Use this
                          </button>
                        </li>
                        );
                      })}
                    </ul>
                    <button
                      type="button"
                      onClick={() => setTxFetchResult(null)}
                      className="mt-2 text-[11px] font-mono underline"
                      style={{ color: BB.faint, cursor: "pointer" }}
                      onMouseEnter={(ev) => { ev.currentTarget.style.color = BB.dim; }}
                      onMouseLeave={(ev) => { ev.currentTarget.style.color = BB.faint; }}
                    >
                      Cancel
                    </button>
                  </div>
                )}
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
                      setForm((f) => {
                        const next = { ...f, interest_asset: v, last_modified_at: isoNow() };
                        // Hedged Asset auto-tracks Interest Asset, but only
                        // while the user hasn't diverged them. Once they pick
                        // a different hedged_asset, this stops overriding.
                        if (f.hedged_asset === f.interest_asset) {
                          next.hedged_asset = v;
                        }
                        return next;
                      })
                    }
                  />
                </Field>
                <Field label="Interest Rate (% p.a.)" span={3}>
                  <NumberInput
                    placeholder="e.g. 8.5"
                    value={form.interest_rate}
                    onChange={(v) =>
                      setForm((f) => {
                        const next = { ...f, interest_rate: v, last_modified_at: isoNow() };
                        // Hedging only makes sense when interest accrues. If the
                        // rate is cleared to 0 (or blanked), force is_hedged off
                        // so the disabled checkbox can't leave stale state.
                        const n = parseFloat(v);
                        if (!(isFinite(n) && n > 0)) next.is_hedged = false;
                        return next;
                      })
                    }
                  />
                </Field>
                <Field label="Interest Type" span={3}>
                  <Select
                    value={form.interest_type}
                    onChange={(e) => set("interest_type", e.target.value)}
                  >
                    <option>FIXED</option>
                    <option>FLOATING</option>
                  </Select>
                </Field>
                <Field label="Day Basis" span={3}>
                  <Select
                    value={String(form.day_count_basis ?? 365)}
                    onChange={(e) => set("day_count_basis", parseInt(e.target.value, 10))}
                  >
                    <option value="365">365</option>
                    <option value="360">360</option>
                  </Select>
                </Field>
                <Field label="WHT (%)" span={3}>
                  <NumberInput
                    placeholder="e.g. 15"
                    value={form.wht_pct}
                    onChange={(v) => set("wht_pct", v)}
                  />
                </Field>
                {form.interest_type === "FLOATING" ? (
                  <Field label="Floating Benchmark" span={3}>
                    <Input
                      placeholder="e.g. SOFR + 200bps"
                      value={form.floating_benchmark}
                      onChange={(e) => set("floating_benchmark", e.target.value)}
                    />
                  </Field>
                ) : (
                  <div className="col-span-3" />
                )}

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
                {(() => {
                  const rateNum = parseFloat(form.interest_rate);
                  const hedgeAllowed = isFinite(rateNum) && rateNum > 0;
                  return (
                    <div className="col-span-12 flex items-center gap-2 mb-1">
                      <input
                        type="checkbox"
                        id="is_hedged"
                        checked={form.is_hedged}
                        disabled={!hedgeAllowed}
                        onChange={(e) => set("is_hedged", e.target.checked)}
                        style={{
                          accentColor: BB.orange,
                          cursor: hedgeAllowed ? "pointer" : "not-allowed",
                          opacity: hedgeAllowed ? 1 : 0.45,
                        }}
                      />
                      <label
                        htmlFor="is_hedged"
                        className="text-[11px] flex items-center gap-1.5 font-mono"
                        style={{
                          color: BB.text,
                          cursor: hedgeAllowed ? "pointer" : "not-allowed",
                          opacity: hedgeAllowed ? 1 : 0.55,
                        }}
                        title={hedgeAllowed ? undefined : "Set an interest rate > 0 to enable hedging"}
                      >
                        <Link2 size={11} style={{ color: BB.cyan }} />
                        This loan is hedged with a spot trade
                      </label>
                    </div>
                  );
                })()}
                {form.is_hedged && (
                  <>
                    <Field label="Hedged Asset" span={4}>
                      <div
                        className="text-[12px] font-mono px-2 py-1.5"
                        style={{
                          background: BB.surface2,
                          border: `1px solid ${BB.border}`,
                          color: BB.text,
                          opacity: 0.85,
                        }}
                        title="Hedged asset is locked to Interest Asset"
                      >
                        {form.interest_asset || "—"}
                        <span style={{ opacity: 0.55, marginLeft: 6 }}>
                          (= Interest Asset)
                        </span>
                      </div>
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
              <Input
                type="text"
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
              disabled={!canSubmit || isSubmitting}
              className="flex-1 py-3 text-[12px] font-semibold uppercase tracking-[0.28em] transition-colors font-mono"
              style={{
                background: canSubmit && !isSubmitting ? BB.orange : BB.surface2,
                color: canSubmit && !isSubmitting ? "#ffffff" : BB.faint,
                border: `1px solid ${canSubmit && !isSubmitting ? BB.orange : BB.border}`,
                cursor: canSubmit && !isSubmitting ? "pointer" : "not-allowed",
                letterSpacing: "0.28em",
              }}
              onMouseEnter={(ev) => {
                if (canSubmit && !isSubmitting) ev.currentTarget.style.background = BB.amber;
              }}
              onMouseLeave={(ev) => {
                if (canSubmit && !isSubmitting) ev.currentTarget.style.background = BB.orange;
              }}
            >
              {isSubmitting
                ? "Submitting…"
                : amendingDealRef ? `Update ${amendingDealRef}` : (
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
      </ModalShell>
          )}

          {/* Inline footer — sits at the bottom of the scrollable main, so
              it appears only when the user scrolls past the table rather
              than locking to the viewport edge. */}
          <div
            className="px-5 py-4 text-center"
            style={{
              fontSize: 9,
              letterSpacing: 0.5,
              color: "#5d5d5d",
              fontFamily: "'IBM Plex Mono', ui-monospace, monospace",
            }}
          >
            © 2026 Tokka Labs - Middle Office.
          </div>
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
            <FloatingToast toast={toast} onDismiss={() => setToast(null)} />
            <HistoryModal
              open={Boolean(historyModal)}
              dealRef={historyModal?.dealRef}
              state={historyModal}
              onClose={() => setHistoryModal(null)}
            />
            <LoanScheduleModal
              open={Boolean(loanScheduleModal)}
              dealRef={loanScheduleModal?.dealRef}
              state={loanScheduleModal}
              currentUser={form.created_by}
              onClose={() => setLoanScheduleModal(null)}
              onAmend={(loan) => {
                // Close schedule, then drop the loan row into the form
                // for amendment. Reuses the existing loanPayloadToFormState
                // → setMany → amendingDealRef pipeline.
                setLoanScheduleModal(null);
                loadRowIntoForm(loan);
              }}
              onHistory={(dealRef) => {
                setLoanScheduleModal(null);
                openHistory(dealRef);
              }}
              onCashflowSelect={openCashflowFromSchedule}
              onBookCashflow={openCashflowBookingForLoan}
            />
      </div>
    </div>
    </TokensContext.Provider>
  );
}
