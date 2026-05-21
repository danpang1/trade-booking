import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react({ jsxRuntime: "automatic" }), tailwindcss()],
  server: {
    port: 5180,
    // Proxy /api/* to the Node server (server.js on :5181) so browser
    // fetches stay same-origin. Without this, /api/auth/me hits Vite
    // and gets a 404; api.js's HOSTS fallback only retries on throws,
    // not on 4xx responses, so login would never reach the backend.
    proxy: {
      "/api": { target: "http://localhost:5181", changeOrigin: true },
    },
  },
});
