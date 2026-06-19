import type {
  ProjectPublic,
  ProjectStatus,
  ProjectUpdate,
} from "@/client/types.gen"

// Pure form logic for the admin project EDIT dialog. `code` is read-only (the
// project identity) and is never sent. name + customer are required; budget is
// an optional non-negative number; blank dates/budget are sent as null.

export interface ProjectEditDraft {
  name: string
  customerId: string
  status: ProjectStatus
  startDate: string
  endDate: string
  budget: string
}

function isValidBudget(value: string): boolean {
  const trimmed = value.trim()
  if (trimmed === "") return true // optional
  const n = Number(trimmed)
  return Number.isFinite(n) && n >= 0
}

export function projectToEditDraft(p: ProjectPublic): ProjectEditDraft {
  return {
    name: p.name,
    customerId: p.customer_id,
    status: p.status ?? "ACTIVE",
    startDate: p.start_date ?? "",
    endDate: p.end_date ?? "",
    budget: p.budget_thb != null ? String(p.budget_thb) : "",
  }
}

export function canSaveProject(d: ProjectEditDraft): boolean {
  return d.name.trim() !== "" && d.customerId !== "" && isValidBudget(d.budget)
}

export function buildProjectUpdate(d: ProjectEditDraft): ProjectUpdate {
  const start = d.startDate.trim()
  const end = d.endDate.trim()
  const budget = d.budget.trim()
  return {
    name: d.name.trim(),
    customer_id: d.customerId,
    status: d.status,
    start_date: start === "" ? null : start,
    end_date: end === "" ? null : end,
    budget_thb: budget === "" ? null : budget,
  }
}
