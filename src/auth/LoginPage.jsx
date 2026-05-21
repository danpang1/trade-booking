import React, { useState } from "react";
import tokkaLogo from "../assets/tokka-labs-logo.png";
import { useAuth } from "./AuthContext.jsx";

// Bloomberg-terminal palette — mirror TradeBookingForm constants.
const BB = {
  bg:     "#000000",
  fg:     "#e5e5e5",
  dim:    "#7d7d7d",
  panel:  "#0a0a0a",
  border: "#1f1f1f",
  accent: "#1f63ea",  // tokka blue (sampled from logo; matches TradeBookingForm)
  red:    "#FF4D4F",
};

const inputStyle = {
  width: "100%", padding: "8px 10px", background: "#000",
  color: "#e5e5e5", border: "1px solid #1f1f1f", outline: "none",
  fontFamily: "inherit", fontSize: 13,
};

export default function LoginPage({ banner }) {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError]       = useState("");
  const [pending, setPending]   = useState(false);

  async function submit(e) {
    e.preventDefault();
    setError("");
    setPending(true);
    const r = await login(username.trim(), password);
    setPending(false);
    if (!r.ok) setError(r.error);
  }

  return (
    <div style={{
      minHeight: "100vh", background: BB.bg, color: BB.fg,
      display: "flex", alignItems: "center", justifyContent: "center",
      fontFamily: "'JetBrains Mono', monospace",
    }}>
      <form onSubmit={submit} style={{
        width: 360, padding: 32, background: BB.panel,
        border: `1px solid ${BB.border}`,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 24 }}>
          <img src={tokkaLogo} alt="Tokka" style={{ height: 28 }} />
          <div style={{ fontSize: 13, color: BB.dim, letterSpacing: 1.2 }}>TRADE BOOKING</div>
        </div>

        {banner && (
          <div style={{
            marginBottom: 16, padding: "8px 12px",
            background: "#04162a", border: `1px solid ${BB.accent}`,
            color: BB.accent, fontSize: 12,
          }}>{banner}</div>
        )}

        <label style={{ display: "block", fontSize: 11, color: BB.dim, marginBottom: 4 }}>USERNAME</label>
        <input
          autoFocus value={username} onChange={(e) => setUsername(e.target.value)}
          style={inputStyle} disabled={pending}
        />

        <label style={{ display: "block", fontSize: 11, color: BB.dim, marginBottom: 4, marginTop: 16 }}>PASSWORD</label>
        <input
          type="password" value={password} onChange={(e) => setPassword(e.target.value)}
          style={inputStyle} disabled={pending}
        />

        {error && (
          <div style={{ marginTop: 14, color: BB.red, fontSize: 12 }}>{error}</div>
        )}

        <button type="submit" disabled={pending || !username || !password} style={{
          width: "100%", marginTop: 20, padding: "10px 16px",
          background: BB.accent, color: BB.bg, border: "none",
          fontFamily: "inherit", fontSize: 13, fontWeight: 600, letterSpacing: 1,
          cursor: pending ? "wait" : "pointer", opacity: pending ? 0.6 : 1,
        }}>
          {pending ? "SIGNING IN…" : "SIGN IN"}
        </button>
      </form>
    </div>
  );
}
