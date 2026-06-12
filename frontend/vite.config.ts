import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import { tanstackRouter } from "@tanstack/router-plugin/vite"
import react from "@vitejs/plugin-react-swc"
import { defineConfig } from "vite"
import { VitePWA } from "vite-plugin-pwa"

// https://vitejs.dev/config/
export default defineConfig({
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
            src: "/assets/images/castranova-logo.jpg",
            sizes: "512x512",
            type: "image/jpeg",
            purpose: "any",
          },
        ],
      },
    }),
  ],
})
