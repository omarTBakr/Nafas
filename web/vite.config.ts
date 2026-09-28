/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the app and the gateway share an origin through this proxy,
// so the httpOnly session cookie just works and there is no CORS to configure.
const GATEWAY = process.env.NAFAS_GATEWAY ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    proxy: { "/api": GATEWAY },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
    // Worker threads, not forked processes: on a slow disk (this project lives
    // on a USB drive) a forked worker loading jsdom could miss Vitest's start
    // deadline, and whole test files failed as "no tests" without running.
    pool: "threads",
    // and a few at a time rather than one per core, for the same reason
    maxWorkers: 4,
  },
});
