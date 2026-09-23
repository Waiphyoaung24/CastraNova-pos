import { ChevronRight } from "lucide-react"
import type { ReactNode } from "react"

import type { ProjectPullPublic, ProjectPullState } from "@/client/types.gen"
import { lineLabel } from "@/components/pos/PullFulfillPanel"
import { Badge } from "@/components/ui/badge"
import {
  type ProjectPullGroup,
  suppliedReturned,
} from "@/lib/project-dashboard"

export const STATE_VARIANT: Record<
  ProjectPullState,
  "default" | "secondary" | "destructive" | "outline"
> = {
  PENDING: "secondary",
  FULFILLED: "default",
  SHORT: "destructive",
  CANCELLED: "outline",
}

export const STATE_LABEL: Record<ProjectPullState, string> = {
  PENDING: "Waiting",
  FULFILLED: "Done",
  SHORT: "Short",
  CANCELLED: "Cancelled",
}

/** One request: when, its status, and each item's allocated/supplied/returned. */
export function PullRequestCard({
  pull,
  actions,
}: {
  pull: ProjectPullPublic
  /** Buttons shown at the end of the header row (e.g. Open / Cancel). */
  actions?: ReactNode
}) {
  return (
    <div className="bg-card rounded-lg border">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b px-4 py-3">
        <span className="num font-medium">
          {new Date(pull.created_at).toLocaleString()}
        </span>
        <Badge variant={STATE_VARIANT[pull.state]}>
          {STATE_LABEL[pull.state]}
        </Badge>
        <span className="text-muted-foreground text-sm">
          {pull.lines.length} {pull.lines.length === 1 ? "item" : "items"}
        </span>
        {pull.admin_notes ? (
          <span className="text-muted-foreground min-w-0 flex-1 truncate text-sm">
            {pull.admin_notes}
          </span>
        ) : null}
        {actions ? <div className="ml-auto">{actions}</div> : null}
      </div>
      <ul className="divide-y">
        {pull.lines.map((line) => {
          const returned = suppliedReturned(line)
          const out = line.returnable_qty ?? 0
          return (
            <li
              key={line.id}
              className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-4 py-2 text-sm"
            >
              <span>
                {line.line_kind === "UNIT"
                  ? `${line.model_name} · ${lineLabel(line)}`
                  : lineLabel(line)}
              </span>
              <span className="text-muted-foreground num text-xs">
                {/* A UNIT line is one serial, so it carries no qty. */}
                {line.requested_qty ?? 1} allocated
                {line.fulfilled_qty > 0
                  ? ` · ${line.fulfilled_qty} supplied`
                  : ""}
                {returned > 0 ? ` · ${returned} returned` : ""}
                {out > 0 ? ` · ${out} still out` : ""}
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

/**
 * Past requests rolled up per project: a summary line each (totals, last
 * request), opening to that project's requests. Native <details> does the
 * expand/collapse.
 */
export function ProjectHistory({
  groups,
  renderActions,
}: {
  groups: ProjectPullGroup[]
  renderActions: (pull: ProjectPullPublic) => ReactNode
}) {
  return (
    <ul className="space-y-3">
      {groups.map((g) => (
        <li key={g.projectId}>
          <details className="group bg-card rounded-lg border">
            <summary className="flex cursor-pointer list-none flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 [&::-webkit-details-marker]:hidden">
              <ChevronRight
                className="text-muted-foreground size-4 shrink-0 transition-transform group-open:rotate-90"
                aria-hidden="true"
              />
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{g.label}</p>
                <p className="text-muted-foreground truncate text-sm">
                  {g.customerName} · {g.pulls.length}{" "}
                  {g.pulls.length === 1 ? "request" : "requests"} · last{" "}
                  {new Date(g.lastAt).toLocaleDateString()}
                </p>
              </div>
              <dl className="num grid grid-cols-4 gap-4 text-right text-sm">
                <Figure label="Allocated" value={g.totals.allocated} />
                <Figure label="Supplied" value={g.totals.supplied} />
                <Figure label="Returned" value={g.totals.returned} />
                <Figure label="Still out" value={g.totals.stillOut} strong />
              </dl>
            </summary>
            <ol className="space-y-3 border-t p-3">
              {g.pulls.map((pull) => (
                <li key={pull.id}>
                  <PullRequestCard pull={pull} actions={renderActions(pull)} />
                </li>
              ))}
            </ol>
          </details>
        </li>
      ))}
    </ul>
  )
}

function Figure({
  label,
  value,
  strong = false,
}: {
  label: string
  value: number
  strong?: boolean
}) {
  return (
    <div>
      <dt className="text-muted-foreground text-[11px] tracking-wide uppercase">
        {label}
      </dt>
      <dd className={strong ? "font-semibold" : undefined}>{value}</dd>
    </div>
  )
}
