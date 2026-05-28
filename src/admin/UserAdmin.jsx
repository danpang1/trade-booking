import React, { useEffect, useState, useMemo } from "react";
import { Pencil, Trash2, Plus, X, Check } from "lucide-react";
import { apiJson } from "../auth/api.js";
import UserEditModal from "./UserEditModal.jsx";

// Token-backed palette — mirrors ApiTokens / Deal Enquiry / Pending
// Bookings so the User Admin page shares one visual language with the
// rest of the app. The old Bloomberg-style dark theme (#000 / orange)
// is gone; admin pills now land on Tokka blue (--signal-link).
const BB = {
  bg:     "var(--paper)",
  panel:  "var(--paper-2)",
  border: "var(--rule-2)",
  fg:     "var(--ink)",
  dim:    "var(--ink-3)",
  accent: "var(--signal-link)",
  warn:   "var(--signal-warn)",
  red:    "var(--signal-sell)",
};

function fmtDate(iso) {
  if (!iso) return "—";
  return iso.slice(0, 19).replace("T", " ");
}

// Table cells — 28px dense rows per STYLE_GUIDE §5; mono 10px uppercase
// 0.06em-tracked column heads on paper-2 background. Same as ApiTokens.
const th = { padding: "6px 12px", textAlign: "left", color: "var(--ink-3)", fontSize: 10, letterSpacing: "0.06em", textTransform: "uppercase", background: "var(--paper-2)", borderBottom: "1px solid var(--rule)", fontWeight: 500 };
const td = { padding: "6px 12px", borderBottom: "1px solid var(--rule)", fontSize: 12, color: "var(--ink)" };

// Buttons — primary uses --panel (warm black) for the NEW USER /
// APPROVE AS ADMIN CTAs; ghost is the secondary action; icon is the
// small bordered square used for row actions (Edit / Delete).
const primaryBtn = { display: "inline-flex", alignItems: "center", gap: 6, background: "var(--panel)", color: "var(--panel-ink)", border: "1px solid var(--panel)", padding: "6px 10px", fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: "0.05em", textTransform: "uppercase", cursor: "pointer", borderRadius: 3 };
const ghostBtn   = { display: "inline-flex", alignItems: "center", gap: 6, background: "var(--paper)", color: "var(--ink)", border: "1px solid var(--rule-2)", padding: "6px 10px", fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: "0.05em", textTransform: "uppercase", cursor: "pointer", borderRadius: 3 };
const iconBtn    = { display: "inline-flex", alignItems: "center", justifyContent: "center", background: "transparent", color: "var(--ink)", border: "1px solid var(--rule-2)", padding: 4, cursor: "pointer", borderRadius: 3 };

export default function UserAdmin({ onClose }) {
  const [rows, setRows]       = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState("");
  const [modal, setModal]     = useState(null);  // { mode:"create"|"edit", user?, isLastAdmin? }
  const [tab, setTab]         = useState("active");  // "active" | "pending"

  const active  = useMemo(() => rows.filter((r) => r.status !== "pending"), [rows]);
  const pending = useMemo(() => rows.filter((r) => r.status === "pending"), [rows]);
  const adminCount = useMemo(() => active.filter((r) => r.role === "admin").length, [active]);

  async function load() {
    setLoading(true);
    const { status, body } = await apiJson("/api/users");
    if (status === 200 && body?.ok) {
      setRows(body.rows);
      setError("");
    } else {
      setError(body?.error || `HTTP ${status}`);
    }
    setLoading(false);
  }

  useEffect(() => { load(); }, []);
  useEffect(() => {
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, []);

  async function onDelete(user) {
    if (!confirm(`Delete user ${user.username}? This force-logs them out.`)) return;
    const { status, body } = await apiJson(`/api/users/${user.id}`, { method: "DELETE" });
    if (status !== 200 || !body?.ok) {
      setError(body?.error || `Delete failed (${status})`);
      return;
    }
    await load();
  }

  async function onApprove(user, role) {
    if (!confirm(`Approve ${user.username} as ${role.toUpperCase()}?`)) return;
    const { status, body } = await apiJson(`/api/users/${user.id}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role }),
    });
    if (status !== 200 || !body?.ok) {
      setError(body?.error || `Approve failed (${status})`);
      return;
    }
    await load();
  }

  async function onReject(user) {
    if (!confirm(`Reject ${user.username}? This deletes their request.`)) return;
    const { status, body } = await apiJson(`/api/users/${user.id}/reject`, { method: "POST" });
    if (status !== 200 || !body?.ok) {
      setError(body?.error || `Reject failed (${status})`);
      return;
    }
    await load();
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
      {/* Page header — serif title + primary CTA, matching ApiTokens. */}
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
            User Admin
          </div>
          <div style={{
            fontSize: 11, color: "var(--ink-3)",
            letterSpacing: "0.06em", textTransform: "uppercase",
            marginTop: 4,
          }}>
            Manage operators and approve registration requests
          </div>
        </div>
        <button onClick={() => setModal({ mode: "create" })} style={primaryBtn}>
          <Plus size={14} /> New user
        </button>
      </div>

      {/* Tabs — same active/pending toggle; dim text + accent underline. */}
      <div style={{
        display: "flex", gap: 24,
        padding: "10px 24px",
        borderBottom: "1px solid var(--rule)",
      }}>
        {[["active", "Active", active.length, BB.accent], ["pending", "Pending", pending.length, BB.warn]].map(([key, label, count, pillColor]) => {
          const isActive = tab === key;
          return (
            <button key={key} onClick={() => setTab(key)} style={{
              background: "transparent", border: "none",
              color: isActive ? "var(--ink)" : "var(--ink-3)",
              fontFamily: "var(--font-mono)",
              fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase",
              padding: "4px 0",
              borderBottom: isActive ? `2px solid ${BB.accent}` : "2px solid transparent",
              cursor: "pointer", display: "flex", alignItems: "center", gap: 8,
            }}>
              {label}
              {count > 0 && (
                <span style={{
                  display: "inline-flex", alignItems: "center",
                  padding: "1px 6px", borderRadius: 2, lineHeight: 1.2,
                  background: key === "pending"
                    ? "color-mix(in srgb, var(--signal-warn) 14%, var(--paper))"
                    : "var(--paper-2)",
                  color: pillColor,
                  border: `1px solid ${pillColor}`,
                  fontSize: 10, fontWeight: 600,
                }}>{count}</span>
              )}
            </button>
          );
        })}
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
        {tab === "active" ? (
          <div style={{
            border: "1px solid var(--rule-2)", borderRadius: 3, overflow: "hidden",
          }}>
            <table style={{
              width: "100%", borderCollapse: "collapse",
              fontFamily: "var(--font-mono)",
            }}>
              <thead>
                <tr>
                  {["ID", "Username", "Email", "Role", "Approved by", "Created", "Updated", ""].map((h) => (
                    <th key={h} style={th}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr><td colSpan={8} style={{ ...td, color: "var(--ink-3)", padding: 16 }}>LOADING…</td></tr>
                )}
                {!loading && active.length === 0 && (
                  <tr><td colSpan={8} style={{ ...td, color: "var(--ink-3)", padding: 16, fontStyle: "italic" }}>No active users.</td></tr>
                )}
                {!loading && active.map((u, i) => {
                  const isLastAdmin = u.role === "admin" && adminCount <= 1;
                  const altBg = i % 2 ? "rgba(0,0,0,0.015)" : "var(--paper)";
                  return (
                    <tr key={u.id} style={{ background: altBg }}>
                      <td style={{ ...td, color: "var(--ink-3)" }}>{u.id}</td>
                      <td style={td}>{u.username}</td>
                      <td style={{ ...td, color: "var(--ink-3)" }}>{u.email}</td>
                      <td style={td}>
                        <span style={{
                          display: "inline-flex", alignItems: "center",
                          padding: "2px 6px", borderRadius: 2, lineHeight: 1.2,
                          background: u.role === "admin"
                            ? "color-mix(in srgb, var(--signal-link) 12%, var(--paper))"
                            : "var(--paper-2)",
                          color: u.role === "admin" ? BB.accent : "var(--ink-3)",
                          border: `1px solid ${u.role === "admin" ? BB.accent : "var(--rule-2)"}`,
                          fontSize: 10, fontWeight: 600,
                          letterSpacing: "0.06em", textTransform: "uppercase",
                        }}>{u.role}</span>
                      </td>
                      <td style={{ ...td, color: "var(--ink-3)" }}>{u.approved_by || "—"}</td>
                      <td style={{ ...td, color: "var(--ink-3)" }}>{fmtDate(u.created_at)}</td>
                      <td style={{ ...td, color: "var(--ink-3)" }}>{fmtDate(u.updated_at)}</td>
                      <td style={{ ...td, display: "flex", gap: 6 }}>
                        <button onClick={() => setModal({ mode: "edit", user: u, isLastAdmin })} style={iconBtn} title="Edit">
                          <Pencil size={12} />
                        </button>
                        <button
                          onClick={() => onDelete(u)}
                          style={{
                            ...iconBtn,
                            color: isLastAdmin ? "var(--ink-4)" : "var(--signal-sell)",
                            borderColor: isLastAdmin ? "var(--rule-2)" : "var(--signal-sell)",
                            opacity: isLastAdmin ? 0.5 : 1,
                            cursor: isLastAdmin ? "not-allowed" : "pointer",
                          }}
                          disabled={isLastAdmin}
                          title={isLastAdmin ? "Cannot delete last admin" : "Delete"}
                        >
                          <Trash2 size={12} />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
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
                  {["Username", "Email", "Submitted at", "Actions"].map((h) => (
                    <th key={h} style={th}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr><td colSpan={4} style={{ ...td, color: "var(--ink-3)", padding: 16 }}>LOADING…</td></tr>
                )}
                {!loading && pending.length === 0 && (
                  <tr><td colSpan={4} style={{ ...td, color: "var(--ink-3)", padding: 16, fontStyle: "italic" }}>No pending registrations.</td></tr>
                )}
                {!loading && pending.map((u, i) => {
                  const altBg = i % 2 ? "rgba(0,0,0,0.015)" : "var(--paper)";
                  return (
                    <tr key={u.id} style={{ background: altBg }}>
                      <td style={td}>{u.username}</td>
                      <td style={{ ...td, color: "var(--ink-3)" }}>{u.email}</td>
                      <td style={{ ...td, color: "var(--ink-3)" }}>{fmtDate(u.created_at)}</td>
                      <td style={{ ...td, display: "flex", gap: 6, flexWrap: "wrap" }}>
                        <button style={ghostBtn} onClick={() => onApprove(u, "user")}>
                          <Check size={12} /> Approve as user
                        </button>
                        <button style={primaryBtn} onClick={() => onApprove(u, "admin")}>
                          <Check size={12} /> Approve as admin
                        </button>
                        <button
                          style={{ ...ghostBtn, color: "var(--signal-sell)", borderColor: "var(--signal-sell)" }}
                          onClick={() => onReject(u)}
                        >
                          <X size={12} /> Reject
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {modal && (
        <UserEditModal
          mode={modal.mode}
          user={modal.user}
          isLastAdmin={modal.isLastAdmin}
          onClose={() => setModal(null)}
          onSaved={async () => { setModal(null); await load(); }}
        />
      )}
    </div>
  );
}
