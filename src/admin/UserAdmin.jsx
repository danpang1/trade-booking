import React, { useEffect, useState, useMemo } from "react";
import { Pencil, Trash2, Plus, X } from "lucide-react";
import { apiJson } from "../auth/api.js";
import UserEditModal from "./UserEditModal.jsx";

const BB = {
  bg: "#000", panel: "#0a0a0a", border: "#1f1f1f",
  fg: "#e5e5e5", dim: "#7d7d7d", accent: "#FA8C16", red: "#FF4D4F",
};

function fmtDate(iso) {
  if (!iso) return "";
  return iso.slice(0, 19).replace("T", " ");
}

const td        = { padding: "10px 16px", borderBottom: `1px solid ${BB.border}` };
const primaryBtn = { display: "flex", alignItems: "center", gap: 6, background: BB.accent, color: BB.bg, border: "none", padding: "6px 12px", fontFamily: "inherit", fontSize: 11, letterSpacing: 1, cursor: "pointer" };
const ghostBtn   = { display: "flex", alignItems: "center", gap: 6, background: "transparent", color: BB.fg, border: `1px solid ${BB.border}`, padding: "6px 12px", fontFamily: "inherit", fontSize: 11, letterSpacing: 1, cursor: "pointer" };
const iconBtn    = { background: "transparent", color: BB.fg, border: `1px solid ${BB.border}`, padding: 4, cursor: "pointer" };

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
    <div style={{
      minHeight: "100vh", background: BB.bg, color: BB.fg,
      fontFamily: "'IBM Plex Mono', ui-monospace, monospace",
    }}>
      <div style={{
        padding: "16px 24px", display: "flex", alignItems: "center",
        justifyContent: "space-between", borderBottom: `1px solid ${BB.border}`,
      }}>
        <div style={{ fontSize: 13, letterSpacing: 2, color: BB.dim }}>USER ADMIN</div>
        <div style={{ display: "flex", gap: 12 }}>
          <button onClick={() => setModal({ mode: "create" })} style={primaryBtn}>
            <Plus size={14} /> NEW USER
          </button>
          <button onClick={onClose} style={ghostBtn}>
            <X size={14} /> CLOSE
          </button>
        </div>
      </div>

      <div style={{ display: "flex", gap: 24, padding: "12px 24px", borderBottom: `1px solid ${BB.border}` }}>
        {[["active", "ACTIVE", active.length], ["pending", "PENDING", pending.length]].map(([key, label, count]) => {
          const isActive = tab === key;
          return (
            <button key={key} onClick={() => setTab(key)} style={{
              background: "transparent", border: "none",
              color: isActive ? BB.fg : BB.dim,
              fontFamily: "inherit", fontSize: 11, letterSpacing: 1.5, padding: "4px 0",
              borderBottom: isActive ? `2px solid ${BB.accent}` : "2px solid transparent",
              cursor: "pointer", display: "flex", alignItems: "center", gap: 8,
            }}>
              {label}
              {count > 0 && (
                <span style={{
                  background: key === "pending" ? BB.accent : BB.border,
                  color: key === "pending" ? BB.bg : BB.fg,
                  padding: "1px 6px", fontSize: 10, fontWeight: 600,
                }}>{count}</span>
              )}
            </button>
          );
        })}
      </div>

      {error && (
        <div style={{ margin: 24, padding: 12, border: `1px solid ${BB.red}`, color: BB.red, fontSize: 12 }}>
          {error}
        </div>
      )}

      {tab === "active" ? (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr style={{ color: BB.dim, textAlign: "left" }}>
              {["ID", "USERNAME", "EMAIL", "ROLE", "APPROVED BY", "CREATED", "UPDATED", ""].map((h) => (
                <th key={h} style={{ padding: "10px 16px", borderBottom: `1px solid ${BB.border}`, letterSpacing: 1 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={8} style={{ padding: 16, color: BB.dim }}>loading…</td></tr>}
            {!loading && active.map((u) => {
              const isLastAdmin = u.role === "admin" && adminCount <= 1;
              return (
                <tr key={u.id}>
                  <td style={td}>{u.id}</td>
                  <td style={td}>{u.username}</td>
                  <td style={td}>{u.email}</td>
                  <td style={{ ...td, color: u.role === "admin" ? BB.accent : BB.fg }}>{u.role}</td>
                  <td style={{ ...td, color: BB.dim }}>{u.approved_by || ""}</td>
                  <td style={td}>{fmtDate(u.created_at)}</td>
                  <td style={td}>{fmtDate(u.updated_at)}</td>
                  <td style={{ ...td, display: "flex", gap: 8 }}>
                    <button onClick={() => setModal({ mode: "edit", user: u, isLastAdmin })} style={iconBtn} title="Edit">
                      <Pencil size={14} />
                    </button>
                    <button
                      onClick={() => onDelete(u)}
                      style={{ ...iconBtn, opacity: isLastAdmin ? 0.3 : 1, cursor: isLastAdmin ? "not-allowed" : "pointer" }}
                      disabled={isLastAdmin}
                      title={isLastAdmin ? "Cannot delete last admin" : "Delete"}
                    >
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr style={{ color: BB.dim, textAlign: "left" }}>
              {["USERNAME", "EMAIL", "SUBMITTED AT", "ACTIONS"].map((h) => (
                <th key={h} style={{ padding: "10px 16px", borderBottom: `1px solid ${BB.border}`, letterSpacing: 1 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={4} style={{ padding: 16, color: BB.dim }}>loading…</td></tr>}
            {!loading && pending.length === 0 && (
              <tr><td colSpan={4} style={{ padding: 16, color: BB.dim, fontStyle: "italic" }}>No pending registrations.</td></tr>
            )}
            {!loading && pending.map((u) => (
              <tr key={u.id}>
                <td style={td}>{u.username}</td>
                <td style={td}>{u.email}</td>
                <td style={td}>{fmtDate(u.created_at)}</td>
                <td style={{ ...td, display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <button style={ghostBtn} onClick={() => onApprove(u, "user")}>APPROVE AS USER</button>
                  <button style={primaryBtn} onClick={() => onApprove(u, "admin")}>APPROVE AS ADMIN</button>
                  <button
                    style={{ ...ghostBtn, color: BB.red, borderColor: BB.red }}
                    onClick={() => onReject(u)}
                  >REJECT</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

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
