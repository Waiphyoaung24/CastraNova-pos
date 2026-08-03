import path from "node:path"
import { defineConfig } from "vitest/config"

// Unit tests only. Scoped to colocated `src/**/*.test.ts` so vitest never
// collects `tests/*.spec.ts` — those are Playwright specs, which need a live
// stack and a browser. The two runners stay strictly separate: `test:unit`
// (vitest, no stack) vs `test` (playwright, full stack).
//
// This config replaces vite.config.ts rather than extending it, so the `@`
// alias has to be repeated here for any test that *value*-imports from `@/`.
export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    include: ["src/**/*.test.ts"],
  },
})
