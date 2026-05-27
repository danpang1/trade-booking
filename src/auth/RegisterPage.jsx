import React, { useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import tokkaLogo from "../assets/tokka-labs-logo.png";
import { register } from "./api.js";

const BB = {
  bg:     "#000000",
  fg:     "#e5e5e5",
  dim:    "#7d7d7d",
  panel:  "#0a0a0a",
  border: "#1f1f1f",
  accent: "#1f63ea",
  red:    "#FF4D4F",
};

const inputStyle = {
  width: "100%", padding: "8px 10px", background: "#000",
  color: "#e5e5e5", border: "1px solid #1f1f1f", outline: "none",
  fontFamily: "inherit", fontSize: 13,
};

function PasswordInput({ value, onChange, disabled }) {
  const [show, setShow] = useState(false);
  return (
    <div style={{ position: "relative" }}>
      <input
        type={show ? "text" : "password"} value={value} onChange={onChange}
        style={{ ...inputStyle, paddingRight: 36 }} disabled={disabled}
      />
      <button
        type="button" tabIndex={-1} onClick={() => setShow((v) => !v)}
        title={show ? "Hide password" : "Show password"}
        style={{
          position: "absolute", right: 6, top: "50%", transform: "translateY(-50%)",
          background: "transparent", border: "none", color: BB.dim, cursor: "pointer",
          padding: 4, display: "flex", alignItems: "center",
        }}
      >
        {show ? <EyeOff size={14} /> : <Eye size={14} />}
      </button>
    </div>
  );
}

export default function RegisterPage({ onRegistered, onBackToLogin }) {
  const [username, setUsername] = useState("");
  const [email, setEmail]       = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm]   = useState("");
  const [error, setError]       = useState("");
  const [pending, setPending]   = useState(false);

  const passwordsMismatch = confirm.length > 0 && password !== confirm;
  const canSubmit = username && email && password && confirm && !passwordsMismatch && !pending;

  async function submit(e) {
    e.preventDefault();
    setError("");
    if (passwordsMismatch) { setError("passwords do not match"); return; }
    setPending(true);
    const { status, body } = await register({ username: username.trim(), email: email.trim(), password });
    setPending(false);
    if (status === 200 && body?.ok) {
      onRegistered("Account submitted. You'll be notified when an admin approves it.");
      return;
    }
    setError(body?.error || `HTTP ${status}`);
  }

  return (
    <div style={{
      minHeight: "100vh", background: BB.bg, color: BB.fg,
      display: "flex", alignItems: "center", justifyContent: "center",
      fontFamily: "var(--font-mono)",
    }}>
      <form onSubmit={submit} style={{
        width: 360, padding: 32, background: BB.panel,
        border: `1px solid ${BB.border}`,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 24 }}>
          <img src={tokkaLogo} alt="Tokka" style={{ height: 28 }} />
          <div style={{ fontSize: 13, color: BB.dim, letterSpacing: 1.2 }}>REQUEST ACCOUNT</div>
        </div>

        <label style={{ display: "block", fontSize: 11, color: BB.dim, marginBottom: 4 }}>USERNAME</label>
        <input autoFocus value={username} onChange={(e) => setUsername(e.target.value)}
               style={inputStyle} disabled={pending} />

        <label style={{ display: "block", fontSize: 11, color: BB.dim, marginBottom: 4, marginTop: 16 }}>EMAIL</label>
        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
               style={inputStyle} disabled={pending} />

        <label style={{ display: "block", fontSize: 11, color: BB.dim, marginBottom: 4, marginTop: 16 }}>PASSWORD</label>
        <PasswordInput value={password} onChange={(e) => setPassword(e.target.value)} disabled={pending} />

        <label style={{ display: "block", fontSize: 11, color: BB.dim, marginBottom: 4, marginTop: 16 }}>CONFIRM PASSWORD</label>
        <PasswordInput value={confirm} onChange={(e) => setConfirm(e.target.value)} disabled={pending} />

        {passwordsMismatch && (
          <div style={{ marginTop: 8, color: BB.red, fontSize: 11 }}>passwords do not match</div>
        )}
        {error && (
          <div style={{ marginTop: 14, color: BB.red, fontSize: 12 }}>{error}</div>
        )}

        <button type="submit" disabled={!canSubmit} style={{
          width: "100%", marginTop: 20, padding: "10px 16px",
          background: BB.accent, color: BB.bg, border: "none",
          fontFamily: "inherit", fontSize: 13, fontWeight: 600, letterSpacing: 1,
          cursor: canSubmit ? "pointer" : "not-allowed", opacity: canSubmit ? 1 : 0.5,
        }}>
          {pending ? "SUBMITTING…" : "REQUEST ACCOUNT"}
        </button>

        <button type="button" onClick={onBackToLogin} disabled={pending} style={{
          width: "100%", marginTop: 10, padding: "8px 16px",
          background: "transparent", color: BB.dim, border: "none",
          fontFamily: "inherit", fontSize: 11, letterSpacing: 1.5, cursor: "pointer",
        }}>
          ← BACK TO SIGN IN
        </button>
      </form>
    </div>
  );
}
