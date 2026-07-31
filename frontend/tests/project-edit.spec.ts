import { expect, test } from "@playwright/test"
import type { ProjectPublic } from "../src/client/types.gen"
import {
  buildProjectUpdate,
  canSaveProject,
  type ProjectEditDraft,
  projectToEditDraft,
} from "../src/lib/project-edit"

const baseProject: ProjectPublic = {
  id: "pr1",
  code: "P-001",
  name: "Bakery fitout",
  customer_id: "c1",
  status: "ACTIVE",
  start_date: "2026-01-01",
  end_date: null,
  budget_thb: "5000.00",
}

const draft = (over: Partial<ProjectEditDraft> = {}): ProjectEditDraft => ({
  name: "Bakery fitout",
  customerId: "c1",
  status: "ACTIVE",
  startDate: "2026-01-01",
  endDate: "",
  budget: "5000",
  ...over,
})

test("projectToEditDraft maps a project to editable strings (no code)", () => {
  expect(projectToEditDraft(baseProject)).toEqual({
    name: "Bakery fitout",
    customerId: "c1",
    status: "ACTIVE",
    startDate: "2026-01-01",
    endDate: "",
    budget: "5000.00",
  })
})

test("canSaveProject requires name and customer", () => {
  expect(canSaveProject(draft())).toBe(true)
  expect(canSaveProject(draft({ name: "  " }))).toBe(false)
  expect(canSaveProject(draft({ customerId: "" }))).toBe(false)
})

test("canSaveProject rejects a negative/non-numeric budget but allows blank", () => {
  expect(canSaveProject(draft({ budget: "" }))).toBe(true)
  expect(canSaveProject(draft({ budget: "-1" }))).toBe(false)
  expect(canSaveProject(draft({ budget: "abc" }))).toBe(false)
})

test("canSaveProject rejects an end date before the start date", () => {
  // Same rule as the create form — the two dialogs must agree on what a valid
  // project is, or a project saved in one is rejected by the other.
  expect(
    canSaveProject(draft({ startDate: "2026-03-01", endDate: "2026-02-28" })),
  ).toBe(false)
  expect(
    canSaveProject(draft({ startDate: "2026-03-01", endDate: "2026-03-01" })),
  ).toBe(true)
  expect(
    canSaveProject(draft({ startDate: "2026-03-01", endDate: "2026-03-02" })),
  ).toBe(true)
  // Either date alone is fine.
  expect(canSaveProject(draft({ startDate: "", endDate: "2026-02-28" }))).toBe(
    true,
  )
})

test("buildProjectUpdate sends fields, never code, dates/budget as given", () => {
  expect(buildProjectUpdate(draft({ endDate: "2026-03-01" }))).toEqual({
    name: "Bakery fitout",
    customer_id: "c1",
    status: "ACTIVE",
    start_date: "2026-01-01",
    end_date: "2026-03-01",
    budget_thb: "5000",
  })
})

test("buildProjectUpdate sends null for blank dates and blank budget", () => {
  expect(
    buildProjectUpdate(draft({ startDate: "", endDate: "", budget: "  " })),
  ).toEqual({
    name: "Bakery fitout",
    customer_id: "c1",
    status: "ACTIVE",
    start_date: null,
    end_date: null,
    budget_thb: null,
  })
})

test("buildProjectUpdate never includes code", () => {
  expect("code" in buildProjectUpdate(draft())).toBe(false)
})
