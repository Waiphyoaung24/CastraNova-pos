import { expect, test } from "@playwright/test"
import { COUNTRIES } from "../src/lib/countries"

// supplier.country is varchar(64); every entry must fit, have no duplicates,
// and be sorted so the picker's initial (unfiltered) list reads predictably.

test("COUNTRIES has no duplicates", () => {
  expect(new Set(COUNTRIES).size).toBe(COUNTRIES.length)
})

test("COUNTRIES is sorted A→Z", () => {
  const sorted = [...COUNTRIES].sort((a, b) => a.localeCompare(b))
  expect(COUNTRIES).toEqual(sorted)
})

test("every country name fits the varchar(64) column", () => {
  for (const country of COUNTRIES) {
    expect(country.length).toBeLessThanOrEqual(64)
  }
})
