import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// El backend headless corre en :8000 (python -m server.main).
// En desarrollo, Vite (5173) proxea los WebSockets al backend.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist" },
  server: {
    port: 5173,
    proxy: {
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
  test: {
    environment: "happy-dom",
    globals: true,
  },
});
