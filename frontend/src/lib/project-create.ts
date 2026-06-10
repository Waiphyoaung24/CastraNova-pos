import type { ProjectCreate } from "@/client/types.gen"

// ---------------------------------------------------------------------------
// Pure form logic for the admin Projects create form (FR-003). Mirrors the
// backend ProjectCreate required fields so submit only enables for a body the
// server will accept.
// ---------------------------------------------------------------------------

export interface ProjectDraft {
  code: string
  name: string
  customerId: string
}

export function canCreateProject(d: ProjectDraft): boolean {
  return d.code.trim() !== "" && d.name.trim() !== "" && d.customerId !== ""
}

export function buildProjectPayload(d: ProjectDraft): ProjectCreate {
  return {
    code: d.code.trim(),
    name: d.name.trim(),
    customer_id: d.customerId,
  }
}
