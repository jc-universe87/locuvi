import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The phone app build (npm run build:pocket) runs from files and sub-folders: relative paths.
const pocket = process.env.VITE_POCKET === "1";

// The phone app is served as plain files (GitHub Pages for iPhone and iPad, the Android app's
// own files), with no server to send security headers, so its page carries them itself: it
// may only load code from its own address (Pyodide needs WebAssembly compiled in place), and
// connect only to that address and, over https://, to the owner's Nextcloud for sync.
const POCKET_CSP = [
  "default-src 'self'",
  "script-src 'self' 'wasm-unsafe-eval'",
  "worker-src 'self'",
  "connect-src 'self' https:",
  "img-src 'self' blob: data:",
  "style-src 'self' 'unsafe-inline'",
  "font-src 'self'",
  "manifest-src 'self'",
  "frame-src 'none'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'none'",
].join("; ");

const pocketHeaders = {
  name: "locuvi-pocket-headers",
  transformIndexHtml: (html: string) =>
    pocket
      ? html.replace(
          "<head>",
          `<head>\n    <meta http-equiv="Content-Security-Policy" content="${POCKET_CSP}" />\n    <meta name="referrer" content="no-referrer" />`,
        )
      : html,
};

export default defineConfig({
  plugins: [react(), pocketHeaders],
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
