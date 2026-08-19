import { expect, test } from "@playwright/test"

import {
  channelLabel,
  trackingModeLabel,
  unitStatusLabel,
} from "../src/lib/labels"

// Pure-logic coverage of the staff-facing display-label helpers.
// No browser / backend required — mirrors the useRole.spec.ts pattern.

test("trackingModeLabel maps known modes to plain words", () => {
  expect(trackingModeLabel("SERIALIZED")).toBe("Serialized")
  expect(trackingModeLabel("QUANTITY")).toBe("Quantity")
})

test("trackingModeLabel returns the raw value for unknown modes", () => {
  expect(trackingModeLabel("WHATEVER")).toBe("WHATEVER")
})

test("unitStatusLabel maps every UnitState to a plain word", () => {
  expect(unitStatusLabel("RECEIVED")).toBe("Just received")
  expect(unitStatusLabel("IN_STOCK")).toBe("In stock")
  expect(unitStatusLabel("SOLD")).toBe("Sold")
  expect(unitStatusLabel("MAINTENANCE_OUT")).toBe("In repair")
  expect(unitStatusLabel("PROJECT_OUT")).toBe("Used on project")
  expect(unitStatusLabel("ADJUSTED_OUT")).toBe("Removed")
})

test("unitStatusLabel humanizes an unknown state instead of showing raw enum", () => {
  expect(unitStatusLabel("SOME_NEW_STATE")).toBe("Some new state")
})

test("channelLabel keeps LINE, names Telegram, and passes through unknowns", () => {
  expect(channelLabel("LINE")).toBe("LINE")
  expect(channelLabel("TELEGRAM")).toBe("Telegram")
  // VIBER survives in the enum for historical notification log rows but has
  // no sender and never renders in the grid, so it has no friendly name --
  // it must fall through like any unknown channel rather than throw.
  expect(channelLabel("VIBER")).toBe("VIBER")
  expect(channelLabel("SMS")).toBe("SMS")
})
