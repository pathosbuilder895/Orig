import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/**
 * Dev server proxies API calls to the Docker backend so the browser stays
 * same-origin — no CORS configuration required during local UI development.
 */
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8001", changeOrigin: true },
      "/health": { target: "http://127.0.0.1:8001", changeOrigin: true },
      "/readiness": { target: "http://127.0.0.1:8001", changeOrigin: true },
    },
  },
});
