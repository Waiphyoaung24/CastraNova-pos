import type { ProjectCreate } from "@/client/types.gen"
import { isValidBudget, isValidDateRange } from "@/lib/project-form"

// ---------------------------------------------------------------------------
// Pure form logic for the admin Projects create form (FR-003). Mirrors the
// backend ProjectCreate fields so submit only enables for a body the server
// will accept: code/name/customer required, dates and budget optional.
//
// `status` is deliberately absent — a project being created is ACTIVE, which is
// the server default; only the edit form can close one.
// ---------------------------------------------------------------------------

export interface ProjectDraft {
  code: string
  name: string
  customerId: string
  startDate: string
  endDate: string
  budget: string
}

export function canCreateProject(d: ProjectDraft): boolean {
  return (
    d.code.trim() !== "" &&
    d.name.trim() !== "" &&
    d.customerId !== "" &&
    isValidBudget(d.budget) &&
    isValidDateRange(d.startDate, d.endDate)
  )
}

export function buildProjectPayload(d: ProjectDraft): ProjectCreate {
  const start = d.startDate.trim()
  const end = d.endDate.trim()
  const budget = d.budget.trim()
  return {
    code: d.code.trim(),
    name: d.name.trim(),
    customer_id: d.customerId,
    start_date: start === "" ? null : start,
    end_date: end === "" ? null : end,
    budget_thb: budget === "" ? null : budget,
  }
}
