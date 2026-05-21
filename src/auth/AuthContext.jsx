import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import { apiJson } from "./api.js";

const AuthContext = createContext(null);

export function useAuth() {
  return useContext(AuthContext);
}

export function AuthProvider({ children }) {
  const [user, setUser]   = useState(null);
  const [ready, setReady] = useState(false);  // first /me check finished?

  const refresh = useCallback(async () => {
    const { status, body } = await apiJson("/api/auth/me");
    if (status === 200 && body?.user) setUser(body.user);
    else setUser(null);
    setReady(true);
  }, []);

  const login = useCallback(async (username, password) => {
    const { status, body } = await apiJson("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (status === 200 && body?.user) {
      setUser(body.user);
      return { ok: true };
    }
    return { ok: false, error: body?.error || "Login failed" };
  }, []);

  const logout = useCallback(async () => {
    await apiJson("/api/auth/logout", { method: "POST" });
    setUser(null);
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => {
    function onExpired() { setUser(null); }
    window.addEventListener("auth:expired", onExpired);
    return () => window.removeEventListener("auth:expired", onExpired);
  }, []);

  return (
    <AuthContext.Provider value={{ user, ready, login, logout, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}
