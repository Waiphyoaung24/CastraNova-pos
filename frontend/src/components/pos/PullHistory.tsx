import { ChevronRight, CircleCheck } from "lucide-react"
import type { ReactNode } from "react"

import type {
  ProjectPullLinePublic,
  ProjectPullPublic,
  ProjectPullState,
} from "@/client/types.gen"
import { lineLabel } from "@/components/pos/PullFulfillPanel"
import { Badge } from "@/components/ui/badge"
import {
  type ProjectPullGroup,
  type PullTotals,
  suppliedReturned,
} from "@/lib/pull-history"

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

const day = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  })

export const dateTime = (iso: string) =>
  new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  })

/** A UNIT line names its model and serial; a PART line its model and SKU. */
export function itemName(line: ProjectPullLinePublic): string {
  return line.line_kind === "UNIT"
    ? `${line.model_name} · ${lineLabel(line)}`
    : lineLabel(line)
}

/**
 * Everything that left the shelf, split into what came back (green) and what
 * is still out on site (gold). A short hand-out can have more out than was
 * supplied, so the bar's scale is returned + still out, not allocated.
 */
export function StockBar({ totals }: { totals: PullTotals }) {
  const left = totals.returned + totals.stillOut
  const returnedPct = left === 0 ? 0 : (totals.returned / left) * 100
  return (
    <div
      role="img"
      aria-label={`${totals.stillOut} still out, ${totals.returned} returned`}
      className="bg-muted flex h-1.5 w-full overflow-hidden rounded-full"
    >
      <div
        className="bg-success/70 h-full"
        style={{ width: `${returnedPct}%` }}
      />
      <div
        className="bg-primary h-full"
        style={{ width: `${left === 0 ? 0 : 100 - returnedPct}%` }}
      />
    </div>
  )
}

/** The figure that matters on site: what is still out, or that it's all back. */
export function StillOut({ totals }: { totals: PullTotals }) {
  if (totals.supplied === 0 && totals.stillOut === 0) {
    return (
      <span className="text-muted-foreground text-sm">Nothing given out</span>
    )
  }
  if (totals.stillOut === 0) {
    return (
      <span className="text-success flex items-center gap-1.5 text-sm font-medium">
        <CircleCheck className="size-4" aria-hidden="true" />
        All back
      </span>
    )
  }
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="num text-primary font-display text-2xl leading-none font-semibold">
        {totals.stillOut}
      </span>
      <span className="text-muted-foreground text-sm">still out</span>
    </span>
  )
}

function SuppliedLine({ totals }: { totals: PullTotals }) {
  const short = totals.allocated - totals.supplied
  if (totals.allocated === 0) return null
  return (
    <p className="text-muted-foreground text-xs">
      Supplied <span className="num text-foreground">{totals.supplied}</span> of{" "}
      <span className="num">{totals.allocated}</span>
      {totals.returned > 0 ? (
        <>
          , <span className="num">{totals.returned}</span> returned
        </>
      ) : null}
      {short > 0 ? (
        <span className="text-destructive">
          , <span className="num">{short}</span> short
        </span>
      ) : null}
    </p>
  )
}

/**
 * Past requests rolled up per project. Each card leads with what is still out
 * on site; opening it shows that project's requests as a dated timeline.
 * Native <details> does the expand/collapse.
 */
export function ProjectHistory({
  groups,
  renderActions,
}: {
  groups: ProjectPullGroup[]
  renderActions: (pull: ProjectPullPublic) => ReactNode
}) {
  return (
    <ul className="space-y-2">
      {groups.map((g) => (
        <li key={g.projectId}>
          <details className="group bg-card hover:border-primary/30 open:border-primary/40 rounded-lg border transition-colors">
            <summary className="focus-visible:ring-ring grid cursor-pointer list-none grid-cols-[auto_1fr] items-center gap-x-3 gap-y-3 rounded-lg px-4 py-4 focus-visible:ring-2 focus-visible:outline-none sm:grid-cols-[auto_1fr_16rem] [&::-webkit-details-marker]:hidden">
              <ChevronRight
                className="text-muted-foreground size-4 shrink-0 transition-transform group-open:rotate-90"
                aria-hidden="true"
              />
              <div className="min-w-0">
                <p className="flex flex-wrap items-baseline gap-x-2">
                  <span className="font-display truncate font-semibold">
                    {g.name}
                  </span>
                  <span className="num text-muted-foreground text-xs">
                    {g.code}
                  </span>
                </p>
                <p className="text-muted-foreground truncate text-sm">
                  {g.customerName}, {g.pulls.length}{" "}
                  {g.pulls.length === 1 ? "request" : "requests"}, last{" "}
                  {day(g.lastAt)}
                </p>
              </div>
              <div className="col-start-2 space-y-2 sm:col-start-3">
                <div className="flex items-baseline justify-between gap-3">
                  <StillOut totals={g.totals} />
                  <SuppliedLine totals={g.totals} />
                </div>
                <StockBar totals={g.totals} />
              </div>
            </summary>
            <ol className="border-t px-4 pt-4 pb-2">
              {g.pulls.map((pull) => (
                <li
                  key={pull.id}
                  className="relative ml-1 border-l pb-5 pl-5 last:border-transparent last:pb-2"
                >
                  <span
                    aria-hidden="true"
                    className="bg-card border-primary absolute top-1.5 -left-[5px] size-2.5 rounded-full border-2"
                  />
                  <PullTimelineEntry
                    pull={pull}
                    actions={renderActions(pull)}
                  />
                </li>
              ))}
            </ol>
          </details>
        </li>
      ))}
    </ul>
  )
}

/** One request on a project's timeline: date, status, items, actions. */
function PullTimelineEntry({
  pull,
  actions,
}: {
  pull: ProjectPullPublic
  actions: ReactNode
}) {
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <time dateTime={pull.created_at} className="num text-sm font-medium">
          {dateTime(pull.created_at)}
        </time>
        <Badge variant={STATE_VARIANT[pull.state]}>
          {STATE_LABEL[pull.state]}
        </Badge>
        <div className="ml-auto">{actions}</div>
      </div>
      {pull.admin_notes ? (
        <p className="text-muted-foreground text-sm">{pull.admin_notes}</p>
      ) : null}
      <ul className="bg-muted/40 divide-y rounded-md">
        {pull.lines.map((line) => {
          const returned = suppliedReturned(line)
          const out = line.returnable_qty ?? 0
          return (
            <li
              key={line.id}
              className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-3 py-2 text-sm"
            >
              <span>{itemName(line)}</span>
              <span className="text-muted-foreground text-xs">
                {/* A UNIT line is one serial, so it carries no qty. */}
                Supplied{" "}
                <span className="num text-foreground">
                  {line.fulfilled_qty}/{line.requested_qty ?? 1}
                </span>
                {returned > 0 ? `, ${returned} returned` : ""}
                {out > 0 ? (
                  <span className="text-primary">, {out} still out</span>
                ) : null}
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
