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
      // The login and whoami payloads must agree — see userWithScope in
      // serverScope.mjs. If this response predates that (an older server,
      // a cached bundle), scope_state is missing and the UI would read the
      // absent portfolio list as "owns nothing" and empty every picker.
      // Don't guess which it is: ask whoami.
      if (body.user.scope_state === undefined) await refresh();
      return { ok: true };
    }
    return { ok: false, error: body?.error || "Login failed" };
  }, [refresh]);

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
