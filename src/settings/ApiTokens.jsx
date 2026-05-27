import React, { useEffect, useState } from "react";
import { Plus, X } from "lucide-react";
import { listTokens, revokeToken } from "../auth/api.js";
import TokenGenerateModal from "./TokenGenerateModal.jsx";

// Token-backed palette — pulls from src/tokens.css so this page shares
// the paper/ink surface with Deal Enquiry, Pending Bookings, etc. The
// previous orange accent (#FA8C16) becomes Tokka blue (--signal-link).
const BB = {
  bg:     "var(--paper)",
  panel:  "var(--paper-2)",
  border: "var(--rule-2)",
  fg:     "var(--ink)",
  dim:    "var(--ink-3)",
  accent: "var(--signal-link)",
  red:    "var(--signal-sell)",
};

function fmtDate(iso) {
  if (!iso) return "—";
  return iso.slice(0, 19).replace("T", " ");
}

// Table cells — 28px dense rows per STYLE_GUIDE §5; mono 10px uppercase
// 0.06em-tracked column heads on paper-2 background, matching every
// other table in the app.
const th = { padding: "6px 12px", textAlign: "left", color: "var(--ink-3)", fontSize: 10, letterSpacing: "0.06em", textTransform: "uppercase", background: "var(--paper-2)", borderBottom: "1px solid var(--rule)", fontWeight: 500 };
const td = { padding: "6px 12px", borderBottom: "1px solid var(--rule)", fontSize: 12, color: "var(--ink)" };

// Buttons — STYLE_GUIDE §6.3. Primary uses --panel (warm black) bg with
// --panel-ink text so it matches the Approve / Book Cashflow buttons.
// (The user's "orange → tokka blue" maps to the ACTIVE status colour;
// the primary button stays dark for app-wide consistency.)
const primaryBtn = { display: "inline-flex", alignItems: "center", gap: 6, background: "var(--panel)", color: "var(--panel-ink)", border: "1px solid var(--panel)", padding: "6px 10px", fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: "0.05em", textTransform: "uppercase", cursor: "pointer", borderRadius: 3 };
const ghostBtn   = { display: "inline-flex", alignItems: "center", gap: 6, background: "var(--paper)", color: "var(--ink)", border: "1px solid var(--rule-2)", padding: "6px 10px", fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: "0.05em", textTransform: "uppercase", cursor: "pointer", borderRadius: 3 };
const iconBtn    = { display: "inline-flex", alignItems: "center", justifyContent: "center", background: "transparent", color: "var(--ink)", border: "1px solid var(--rule-2)", padding: 4, cursor: "pointer", borderRadius: 3 };

export default function ApiTokens({ onClose }) {
  const [rows, setRows]       = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState("");
  const [showModal, setShow]  = useState(false);

  async function load() {
    setLoading(true);
    const { status, body } = await listTokens();
    if (status === 200 && body?.ok) {
      setRows(body.tokens || []);
      setError("");
    } else {
      setError(body?.error || `HTTP ${status}`);
    }
    setLoading(false);
  }

  useEffect(() => { load(); }, []);

  async function onRevoke(t) {
    if (!confirm(`Revoke token "${t.name}"? Effective immediately.`)) return;
    const { status, body } = await revokeToken(t.id);
    if (status !== 200 || !body?.ok) {
      setError(body?.error || `Revoke failed (${status})`);
      return;
    }
    await load();
  }

  // ACTIVE pill is the place where "orange → tokka blue" lands —
  // active tokens read as a primary affordance (still usable). Revoked
  // and expired tokens use the status-cancelled / ink-3 muted palette.
  function status(t) {
    if (t.revoked_at) {
      return { label: "REVOKED", fg: "var(--status-cancelled)", bg: "var(--status-cancelled-bg)" };
    }
    if (new Date(t.expires_at) <= new Date()) {
      return { label: "EXPIRED", fg: "var(--ink-3)",            bg: "var(--paper-2)" };
    }
    return   { label: "ACTIVE",  fg: "var(--signal-link)",      bg: "color-mix(in srgb, var(--signal-link) 12%, var(--paper))" };
  }

  return (
    // Flows inline inside <main> alongside Deal/Loan Enquiry + Pending
    // Bookings. No outer 100vh / fixed positioning — the parent layout
    // keeps the top chrome and sidebar in place.
    <div style={{
      color: BB.fg,
      fontFamily: "var(--font-mono)",
      minHeight: "100%",
    }}>
      {/* Page header — serif title + primary CTA, matching Deal Enquiry. */}
      <div style={{
        padding: "16px 24px 12px",
        borderBottom: "1px solid var(--rule)",
        display: "flex", alignItems: "baseline", justifyContent: "space-between",
        gap: 16,
      }}>
        <div>
          <div style={{
            fontFamily: "var(--font-serif)",
            fontSize: 22, fontWeight: 600, letterSpacing: "-0.01em",
            color: "var(--ink)",
          }}>
            API Tokens
          </div>
          <div style={{
            fontSize: 11, color: "var(--ink-3)",
            letterSpacing: "0.06em", textTransform: "uppercase",
            marginTop: 4,
          }}>
            For Claude Code, scripts, or any client calling the MO server
          </div>
        </div>
        <button onClick={() => setShow(true)} style={primaryBtn}>
          <Plus size={14} /> New token
        </button>
      </div>

      {error && (
        <div style={{
          padding: "8px 12px", margin: "12px 24px 0",
          background: "var(--signal-sell-bg)",
          color: "var(--signal-sell)",
          border: "1px solid var(--signal-sell)",
          borderRadius: 3, fontSize: 11,
        }}>
          {error}
        </div>
      )}

      <div style={{ padding: 24 }}>
        {loading ? (
          <div style={{ color: "var(--ink-3)", fontSize: 11 }}>LOADING…</div>
        ) : rows.length === 0 ? (
          <div style={{ color: "var(--ink-3)", fontSize: 12, padding: "20px 0" }}>
            No tokens yet. Click <b>New token</b> above to generate one for Claude Code or other clients.
          </div>
        ) : (
          <div style={{
            border: "1px solid var(--rule-2)", borderRadius: 3, overflow: "hidden",
          }}>
            <table style={{
              width: "100%", borderCollapse: "collapse",
              fontFamily: "var(--font-mono)",
            }}>
              <thead>
                <tr>
                  <th style={th}>Name</th>
                  <th style={th}>Prefix</th>
                  <th style={th}>Status</th>
                  <th style={th}>Last used</th>
                  <th style={th}>Expires</th>
                  <th style={th}></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((t, i) => {
                  const s = status(t);
                  const altBg = i % 2 ? "rgba(0,0,0,0.015)" : "var(--paper)";
                  return (
                    <tr key={t.id} style={{ background: altBg }}>
                      <td style={td}>{t.name}</td>
                      <td style={{ ...td, color: "var(--ink-3)" }}>
                        <code>{t.token_prefix}…</code>
                      </td>
                      <td style={td}>
                        <span style={{
                          display: "inline-flex", alignItems: "center",
                          padding: "2px 6px", borderRadius: 2, lineHeight: 1.2,
                          background: s.bg, color: s.fg,
                          border: `1px solid ${s.fg}`,
                          fontSize: 10, fontWeight: 600,
                          letterSpacing: "0.06em", textTransform: "uppercase",
                        }}>{s.label}</span>
                      </td>
                      <td style={{ ...td, color: "var(--ink-3)" }}>
                        {fmtDate(t.last_used_at)}
                      </td>
                      <td style={{ ...td, color: "var(--ink-3)" }}>
                        {fmtDate(t.expires_at)}
                      </td>
                      <td style={td}>
                        {!t.revoked_at && (
                          <button
                            onClick={() => onRevoke(t)}
                            style={{ ...iconBtn, color: "var(--signal-sell)", borderColor: "var(--signal-sell)" }}
                            title="Revoke"
                          >
                            <X size={12} />
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {showModal && (
        <TokenGenerateModal
          onClose={() => { setShow(false); load(); }}
          onGenerated={() => { /* list reload happens on close */ }}
        />
      )}
    </div>
  );
}
