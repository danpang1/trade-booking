import React, { useEffect, useState } from "react";
import { Plus, X } from "lucide-react";
import { listTokens, revokeToken } from "../auth/api.js";
import TokenGenerateModal from "./TokenGenerateModal.jsx";

const BB = {
  bg: "#000", panel: "#0a0a0a", border: "#1f1f1f",
  fg: "#e5e5e5", dim: "#7d7d7d", accent: "#FA8C16", red: "#FF4D4F",
};

function fmtDate(iso) {
  if (!iso) return "—";
  return iso.slice(0, 19).replace("T", " ");
}

const th = { padding: "10px 16px", textAlign: "left", color: BB.dim, fontSize: 10, letterSpacing: 1.5, borderBottom: `1px solid ${BB.border}` };
const td = { padding: "10px 16px", borderBottom: `1px solid ${BB.border}`, fontSize: 12 };
const primaryBtn = { display: "flex", alignItems: "center", gap: 6, background: BB.accent, color: BB.bg, border: "none", padding: "6px 12px", fontFamily: "inherit", fontSize: 11, letterSpacing: 1, cursor: "pointer" };
const ghostBtn   = { display: "flex", alignItems: "center", gap: 6, background: "transparent", color: BB.fg, border: `1px solid ${BB.border}`, padding: "6px 12px", fontFamily: "inherit", fontSize: 11, letterSpacing: 1, cursor: "pointer" };
const iconBtn    = { background: "transparent", color: BB.fg, border: `1px solid ${BB.border}`, padding: 4, cursor: "pointer" };

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

  function status(t) {
    if (t.revoked_at) return { label: "REVOKED", color: BB.red };
    if (new Date(t.expires_at) <= new Date()) return { label: "EXPIRED", color: BB.dim };
    return { label: "ACTIVE", color: BB.accent };
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
      <div style={{
        padding: "16px 24px", display: "flex", alignItems: "center",
        justifyContent: "space-between", borderBottom: `1px solid ${BB.border}`,
      }}>
        <div style={{ fontSize: 13, letterSpacing: 2, color: BB.dim }}>MY API TOKENS</div>
        <div style={{ display: "flex", gap: 12 }}>
          <button onClick={() => setShow(true)} style={primaryBtn}>
            <Plus size={14} /> NEW TOKEN
          </button>
        </div>
      </div>

      {error && (
        <div style={{ padding: "10px 24px", color: BB.red, fontSize: 11 }}>
          {error}
        </div>
      )}

      <div style={{ padding: 24 }}>
        {loading ? (
          <div style={{ color: BB.dim, fontSize: 11 }}>LOADING...</div>
        ) : rows.length === 0 ? (
          <div style={{ color: BB.dim, fontSize: 11, padding: "20px 0" }}>
            No tokens yet. Click NEW TOKEN above to generate one for Claude Code or other clients.
          </div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", background: BB.panel }}>
            <thead>
              <tr>
                <th style={th}>NAME</th>
                <th style={th}>PREFIX</th>
                <th style={th}>STATUS</th>
                <th style={th}>LAST USED</th>
                <th style={th}>EXPIRES</th>
                <th style={th}></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => {
                const s = status(t);
                return (
                  <tr key={t.id}>
                    <td style={td}>{t.name}</td>
                    <td style={{ ...td, color: BB.dim }}>{t.token_prefix}...</td>
                    <td style={{ ...td, color: s.color }}>{s.label}</td>
                    <td style={{ ...td, color: BB.dim }}>{fmtDate(t.last_used_at)}</td>
                    <td style={{ ...td, color: BB.dim }}>{fmtDate(t.expires_at)}</td>
                    <td style={td}>
                      {!t.revoked_at && (
                        <button
                          onClick={() => onRevoke(t)}
                          style={{ ...iconBtn, color: BB.red, borderColor: BB.red }}
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
