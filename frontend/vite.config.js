import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, /api calls are proxied to the FastAPI server so the browser only ever talks to our backend.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8000" } },
});
