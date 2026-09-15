import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    proxy: {
      "/health": "http://localhost:8000",
      "/scenarios": "http://localhost:8000",
      "/agent": "http://localhost:8000",
      "/pos": "http://localhost:8000",
      "/approvals": "http://localhost:8000",
      "/traces": "http://localhost:8000",
      "/evals": "http://localhost:8000",
      "/insights": "http://localhost:8000",
      "/tools": "http://localhost:8000",
    },
  },
});
