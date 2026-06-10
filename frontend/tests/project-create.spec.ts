import { expect, test } from "@playwright/test"
import {
  buildProjectPayload,
  canCreateProject,
  type ProjectDraft,
} from "../src/lib/project-create"

// Pure-logic coverage of the admin Projects create form (FR-003). Mirrors the
// backend ProjectCreate required fields (code, name, customer_id) so the UI
// only enables submit for a body the server will accept.

function draft(over: Partial<ProjectDraft>): ProjectDraft {
  return { code: "", name: "", customerId: "", ...over }
}

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
  })
})
