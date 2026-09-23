import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { Fragment, type ReactNode, useState } from "react"

import type { ProjectConsumptionRowPublic, ProjectPullPublic } from "@/client"
import { ProjectPullsService, ProjectsService } from "@/client"
import { PageHeader } from "@/components/Common/PageHeader"
import { PullRequestCard } from "@/components/pos/PullHistory"
import { StatCard } from "@/components/reports/StatCard"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useIsMobile } from "@/hooks/useMobile"
import {
  budgetRemaining,
  consumedItemLabel,
  type ItemTotalsRow,
  isAdminProjectDashboard,
  projectItemTotals,
} from "@/lib/project-dashboard"
import { formatThb } from "@/lib/reports"
import { requireAuth } from "@/lib/route-guards"

// Role-tiered (FR-020): both roles may view; budget/consumed-cost render only
// when the admin payload carries them. The backend redacts for staff; the
// isAdminProjectDashboard guard is belt-and-suspenders on the client.
export const Route = createFileRoute("/_layout/project/$projectId")({
  component: ProjectDetail,
  beforeLoad: requireAuth,
  head: () => ({
    meta: [{ title: "Project - CastraNova POS" }],
  }),
})

function ProjectDetail() {
  const { projectId } = Route.useParams()

  const { data, isPending, isError } = useQuery({
    queryKey: ["project-dashboard", projectId],
    queryFn: () => ProjectsService.getProjectDashboard({ projectId }),
  })
  // Every request for this project, newest first. No cost on it, so staff see
  // it too. ponytail: one page of 500 feeds both the totals and the history;
  // page it (and total server-side) if a project ever outgrows that.
  const { data: pullPage } = useQuery({
    queryKey: ["project-pulls", "project", projectId],
    queryFn: () =>
      ProjectPullsService.readProjectPulls({ projectId, limit: 500 }),
  })
  const pulls = pullPage?.data ?? []
  const { rows, totals } = projectItemTotals(pulls)

  if (isPending) {
    return (
      <p className="text-muted-foreground py-6 text-center text-sm">Loading…</p>
    )
  }
  if (isError || !data) {
    return (
      <p className="text-muted-foreground py-6 text-center text-sm">
        Could not load the project.
      </p>
    )
  }

  const { project } = data
  const isAdmin = isAdminProjectDashboard(data)
  const remaining = isAdmin
    ? budgetRemaining(data.budget_thb, data.consumed_cost_thb)
    : null

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        backLink={
          isAdmin && (
            <Link
              to="/projects"
              className="text-muted-foreground text-sm hover:underline"
            >
              ← Projects
            </Link>
          )
        }
        title={project.code}
        titleClassName="num"
        badge={<Badge variant="secondary">{project.status ?? "ACTIVE"}</Badge>}
        description={project.name}
        footer={
          <Link
            to="/customer/$customerId"
            params={{ customerId: project.customer_id }}
            className="text-sm hover:underline"
          >
            View customer
          </Link>
        }
      />

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Allocated" value={totals.allocated} />
        <StatCard label="Supplied" value={totals.supplied} />
        <StatCard label="Returned" value={totals.returned} />
        <StatCard
          label="Still out"
          value={totals.stillOut}
          hint="Not back in stock"
        />
      </div>

      {isAdmin && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <StatCard
            label="Budget"
            value={data.budget_thb ? formatThb(data.budget_thb) : "—"}
          />
          <StatCard label="Spent" value={formatThb(data.consumed_cost_thb)} />
          <StatCard
            label="Remaining"
            value={remaining ? formatThb(remaining) : "—"}
          />
        </div>
      )}

      <ItemTotalsList rows={rows} />

      <OrderHistory pulls={pulls} />

      {isAdmin ? <ConsumedItems rows={data.consumed_items} /> : null}
    </div>
  )
}

/**
 * FR-020 consumed-items list: one row per PROJECT_OUT or pull RETURNED
 * movement, admin-only (it carries cost). A PART row expands to the FIFO
 * batches its cost came from — that is the "batch attribution" the PRD asks
 * for. A UNIT row has nothing to expand: a serialized unit is its own cost
 * layer.
 */
function ConsumedItems({ rows }: { rows: ProjectConsumptionRowPublic[] }) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  function toggle(key: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (!next.delete(key)) next.add(key)
      return next
    })
  }

  return (
    <div className="space-y-2">
      <h2 className="text-lg font-semibold">Cost by batch</h2>
      {rows.length === 0 ? (
        <p className="text-muted-foreground py-6 text-center text-sm">
          Nothing consumed yet.
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Item</TableHead>
              <TableHead className="text-right">Qty</TableHead>
              <TableHead>When</TableHead>
              <TableHead className="text-right">Cost</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r, i) => {
              // Movements have no id in the payload; a project can consume the
              // same product twice in one pull at the same instant, so index is
              // the only stable discriminator here.
              const key = `${r.project_pull_id}-${r.product_id}-${i}`
              const isOpen = expanded.has(key)
              const canExpand = r.draws.length > 0
              const returned = r.event_type === "RETURNED"
              return (
                <Fragment key={key}>
                  <TableRow>
                    <TableCell className="num font-medium">
                      {canExpand ? (
                        <button
                          type="button"
                          onClick={() => toggle(key)}
                          aria-expanded={isOpen}
                          className="hover:underline"
                        >
                          {isOpen ? "▾" : "▸"} {consumedItemLabel(r)}
                        </button>
                      ) : (
                        consumedItemLabel(r)
                      )}
                    </TableCell>
                    <TableCell className="num text-right">
                      {returned ? `−${r.quantity}` : r.quantity}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {returned ? "Returned · " : ""}
                      {new Date(r.occurred_at).toLocaleString()}
                    </TableCell>
                    <TableCell className="num text-right">
                      {returned
                        ? `−${formatThb(r.total_cost_thb)}`
                        : formatThb(r.total_cost_thb)}
                    </TableCell>
                  </TableRow>
                  {isOpen
                    ? r.draws.map((d) => (
                        <TableRow
                          key={`${key}-${d.batch_no}`}
                          className="bg-muted/40"
                        >
                          <TableCell className="num text-muted-foreground pl-8 text-xs">
                            {d.batch_no}
                          </TableCell>
                          <TableCell className="num text-muted-foreground text-right text-xs">
                            {returned ? `−${d.quantity}` : d.quantity}
                          </TableCell>
                          <TableCell className="text-muted-foreground text-xs">
                            @ {formatThb(d.unit_cost_thb)}
                          </TableCell>
                          <TableCell className="num text-muted-foreground text-right text-xs">
                            {returned
                              ? `−${formatThb(d.total_cost_thb)}`
                              : formatThb(d.total_cost_thb)}
                          </TableCell>
                        </TableRow>
                      ))
                    : null}
                </Fragment>
              )
            })}
          </TableBody>
        </Table>
      )}
    </div>
  )
}

/** One row per product across every request: a table, or lines on a phone. */
function ItemTotalsList({ rows }: { rows: ItemTotalsRow[] }) {
  const isMobile = useIsMobile()
  return (
    <Section title="Items">
      {rows.length === 0 ? (
        <Empty>Nothing allocated yet.</Empty>
      ) : isMobile ? (
        <ul className="bg-card divide-y rounded-lg border">
          {rows.map((r) => (
            <li key={r.productId} className="space-y-1 px-4 py-2 text-sm">
              <p className="font-medium">{r.label}</p>
              <p className="text-muted-foreground num text-xs">
                {r.allocated} allocated · {r.supplied} supplied · {r.returned}{" "}
                returned ·{" "}
                <span className="text-foreground font-semibold whitespace-nowrap">
                  {r.stillOut} still out
                </span>
              </p>
            </li>
          ))}
        </ul>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Item</TableHead>
              <TableHead className="text-right">Allocated</TableHead>
              <TableHead className="text-right">Supplied</TableHead>
              <TableHead className="text-right">Returned</TableHead>
              <TableHead className="text-right">Still out</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.productId}>
                <TableCell className="font-medium">{r.label}</TableCell>
                <TableCell className="num text-right">{r.allocated}</TableCell>
                <TableCell className="num text-right">{r.supplied}</TableCell>
                <TableCell className="num text-right">
                  {r.returned || "—"}
                </TableCell>
                <TableCell className="num text-right font-semibold">
                  {r.stillOut}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Section>
  )
}

/** One card per request: when, its status, and each item's counts. */
function OrderHistory({ pulls }: { pulls: ProjectPullPublic[] }) {
  return (
    <Section title="Order history">
      {pulls.length === 0 ? (
        <Empty>No requests yet.</Empty>
      ) : (
        <ol className="space-y-3">
          {pulls.map((pull) => (
            <li key={pull.id}>
              <PullRequestCard pull={pull} />
            </li>
          ))}
        </ol>
      )}
    </Section>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h2 className="text-lg font-semibold">{title}</h2>
      {children}
    </section>
  )
}

function Empty({ children }: { children: ReactNode }) {
  return (
    <p className="text-muted-foreground rounded-lg border border-dashed py-6 text-center text-sm">
      {children}
    </p>
  )
}
