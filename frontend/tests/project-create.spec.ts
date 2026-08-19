import { expect, test } from "@playwright/test"
import {
  buildProjectPayload,
  canCreateProject,
  type ProjectDraft,
} from "../src/lib/project-create"

// Pure-logic coverage of the admin Projects create form (FR-003). Mirrors the
// backend ProjectCreate fields so the UI only enables submit for a body the
// server will accept: code/name/customer required, dates and budget optional.

function draft(over: Partial<ProjectDraft>): ProjectDraft {
  return {
    code: "",
    name: "",
    customerId: "",
    startDate: "",
    endDate: "",
    budget: "",
    ...over,
  }
}

/** The three required fields, so optional-field cases start from a valid draft. */
const required = { code: "PRJ-1", name: "Build", customerId: "c-1" }

test("canCreate is false until code, name, and customer are all set", () => {
  expect(canCreateProject(draft({}))).toBe(false)
  expect(canCreateProject(draft({ code: "PRJ-1" }))).toBe(false)
  expect(canCreateProject(draft({ code: "PRJ-1", name: "Build" }))).toBe(false)
  expect(
    canCreateProject(
      draft({ code: "PRJ-1", name: "Build", customerId: "c-1" }),
    ),
  ).toBe(true)
})

test("whitespace-only code or name does not satisfy canCreate", () => {
  expect(
    canCreateProject(draft({ code: "   ", name: "Build", customerId: "c-1" })),
  ).toBe(false)
  expect(
    canCreateProject(draft({ code: "PRJ-1", name: "  ", customerId: "c-1" })),
  ).toBe(false)
})

test("buildProjectPayload trims code/name and maps customer_id", () => {
  expect(
    buildProjectPayload(
      draft({ code: "  PRJ-1 ", name: " Build ", customerId: "c-1" }),
    ),
  ).toEqual({
    code: "PRJ-1",
    name: "Build",
    customer_id: "c-1",
    start_date: null,
    end_date: null,
    budget_thb: null,
  })
})

// --- optional budget (FR-003: "optional budget") ---------------------------

test("canCreate rejects a negative/non-numeric budget but allows blank", () => {
  expect(canCreateProject(draft({ ...required, budget: "" }))).toBe(true)
  expect(canCreateProject(draft({ ...required, budget: "  " }))).toBe(true)
  expect(canCreateProject(draft({ ...required, budget: "0" }))).toBe(true)
  expect(canCreateProject(draft({ ...required, budget: "1500.50" }))).toBe(true)
  expect(canCreateProject(draft({ ...required, budget: "-1" }))).toBe(false)
  expect(canCreateProject(draft({ ...required, budget: "abc" }))).toBe(false)
})

// --- optional dates, and the end-on-or-after-start rule ---------------------

test("canCreate allows blank dates and either date alone", () => {
  expect(canCreateProject(draft({ ...required }))).toBe(true)
  expect(
    canCreateProject(draft({ ...required, startDate: "2026-01-01" })),
  ).toBe(true)
  expect(canCreateProject(draft({ ...required, endDate: "2026-01-01" }))).toBe(
    true,
  )
})

test("canCreate rejects an end date before the start date", () => {
  expect(
    canCreateProject(
      draft({ ...required, startDate: "2026-03-01", endDate: "2026-02-28" }),
    ),
  ).toBe(false)
  // Same day is allowed — a one-day project is legitimate.
  expect(
    canCreateProject(
      draft({ ...required, startDate: "2026-03-01", endDate: "2026-03-01" }),
    ),
  ).toBe(true)
  expect(
    canCreateProject(
      draft({ ...required, startDate: "2026-03-01", endDate: "2026-03-02" }),
    ),
  ).toBe(true)
})

test("buildProjectPayload passes dates and budget through when set", () => {
  expect(
    buildProjectPayload(
      draft({
        ...required,
        startDate: "2026-01-01",
        endDate: "2026-06-30",
        budget: " 5000 ",
      }),
    ),
  ).toEqual({
    code: "PRJ-1",
    name: "Build",
    customer_id: "c-1",
    start_date: "2026-01-01",
    end_date: "2026-06-30",
    budget_thb: "5000",
  })
})
