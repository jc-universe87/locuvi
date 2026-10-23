import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The phone app build (npm run build:pocket) runs from files and sub-folders: relative paths.
const pocket = process.env.VITE_POCKET === "1";

export default defineConfig({
  plugins: [react()],
  base: pocket ? "./" : "/",
  worker: { format: "es" },
  server: {
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  // No data: URI inlining: the server CSP only allows same-origin fonts/scripts.
  build: { sourcemap: false, target: "es2020", assetsInlineLimit: 0, outDir: pocket ? "dist-pocket" : "dist" },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
  },
});
