import type {
  ProjectPullLinePublic,
  ProjectPullPublic,
} from "@/client/types.gen"

export interface PullTotals {
  allocated: number
  supplied: number
  returned: number
  /** Out of stock on this project and not back yet (ledger, not inferred). */
  stillOut: number
}

/**
 * Returns of what was actually handed over. A cancel (or a return of a short
 * hand-out's surplus) also writes RETURNED movements, but that stock never
 * reached the project, so it doesn't read as "returned".
 */
export function suppliedReturned(line: ProjectPullLinePublic): number {
  return Math.min(line.returned_qty ?? 0, line.fulfilled_qty)
}

/**
 * Totals across requests. Still-out comes from the ledger (a short hand-out
 * keeps its surplus out until returned). A cancelled request allocated only
 * what it handed out before closing. A UNIT line is one serial, so it
 * allocates one.
 */
export function pullTotals(pulls: ProjectPullPublic[]): PullTotals {
  const totals: PullTotals = {
    allocated: 0,
    supplied: 0,
    returned: 0,
    stillOut: 0,
  }
  for (const pull of pulls) {
    const cancelled = pull.state === "CANCELLED"
    for (const line of pull.lines) {
      totals.allocated += cancelled
        ? line.fulfilled_qty
        : (line.requested_qty ?? 1)
      totals.supplied += line.fulfilled_qty
      totals.returned += suppliedReturned(line)
      totals.stillOut += line.returnable_qty ?? 0
    }
  }
  return totals
}

export interface ProjectPullGroup {
  projectId: string
  name: string
  code: string
  customerName: string
  /** Newest request first, as the list came in. */
  pulls: ProjectPullPublic[]
  lastAt: string
  totals: PullTotals
}

/** Newest-first pulls grouped per project, projects ordered by latest request. */
export function groupPullsByProject(
  pulls: ProjectPullPublic[],
): ProjectPullGroup[] {
  const byProject = new Map<string, ProjectPullPublic[]>()
  for (const pull of pulls) {
    byProject.set(pull.project_id, [
      ...(byProject.get(pull.project_id) ?? []),
      pull,
    ])
  }
  return [...byProject.values()].map((group) => ({
    projectId: group[0].project_id,
    name: group[0].project_name,
    code: group[0].project_code,
    customerName: group[0].customer_name,
    pulls: group,
    lastAt: group[0].created_at,
    totals: pullTotals(group),
  }))
}
