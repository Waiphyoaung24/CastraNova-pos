import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import { tanstackRouter } from "@tanstack/router-plugin/vite"
import react from "@vitejs/plugin-react-swc"
import { defineConfig } from "vite"
import { VitePWA } from "vite-plugin-pwa"

// Enable the PWA service worker only for real deployments (VITE_ENABLE_PWA=true).
// In local dev the SW is self-destroying so it unregisters itself and clears its
// precache, otherwise the nginx static build keeps serving stale UI from cache.
const enablePWA = process.env.VITE_ENABLE_PWA === "true"

// Where the dev server forwards `/api` to. This is resolved by the dev server
// process, NOT the browser, so in Docker it must be the compose service name
// (`http://backend:8000`), which compose.override.yml / compose.e2e.yml set.
// The fallback is for running `bun run dev` directly on the host.
const devApiTarget = process.env.VITE_API_URL || "http://localhost:8000"

// https://vitejs.dev/config/
export default defineConfig({
  server: {
    // Serve the API under the app's OWN origin in dev and E2E. The refresh
    // token is an httponly SameSite=lax cookie, and a browser will not even
    // store such a cookie when the page origin and the API origin are
    // cross-site — which is what made /login/refresh-token 401 for the entire
    // session and set off the retry storm (open-issues-2026-07-29 §1). Proxying
    // removes the origin split (and the CORS dependency) in dev outright.
    proxy: {
      "/api": { target: devApiTarget, changeOrigin: true },
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  plugins: [
    tanstackRouter({
      target: "react",
      autoCodeSplitting: true,
    }),
    react(),
    tailwindcss(),
    VitePWA({
      registerType: "autoUpdate",
      selfDestroying: !enablePWA,
      workbox: {
        globPatterns: ["**/*.{js,css,html,ico,png,jpg,svg,woff2}"],
      },
      manifest: {
        name: "CASTRA NOVA POS",
        short_name: "CASTRA NOVA",
        theme_color: "#0B0B0D",
        background_color: "#0B0B0D",
        display: "standalone",
        start_url: "/",
        icons: [
          {
            src: "/assets/images/castranova-logo.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "any",
          },
        ],
      },
    }),
  ],
})
