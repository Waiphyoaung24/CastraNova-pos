import { defineConfig } from "vitest/config"

// Unit tests only. Scoped to colocated `src/**/*.test.ts` so vitest never
// collects `tests/*.spec.ts` — those are Playwright specs, which need a live
// stack and a browser. The two runners stay strictly separate: `test:unit`
// (vitest, no stack) vs `test` (playwright, full stack).
export default defineConfig({
  test: {
    include: ["src/**/*.test.ts"],
  },
})
