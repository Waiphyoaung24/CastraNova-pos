import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { Fragment, useState } from "react"

import type { ProjectConsumptionRowPublic } from "@/client"
import { ProjectPullsService, ProjectsService } from "@/client"
import { PageHeader } from "@/components/Common/PageHeader"
import { PaginationControls } from "@/components/Common/PaginationControls"
import { lineLabel } from "@/components/pos/PullFulfillPanel"
import { STATE_LABEL, STATE_VARIANT } from "@/components/pos/PullQueue"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { usePagination } from "@/hooks/usePagination"
import {
  budgetRemaining,
  consumedItemLabel,
  isAdminProjectDashboard,
} from "@/lib/project-dashboard"
import { returnedQty } from "@/lib/pull-return"
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

      {isAdmin && (
        <Card>
          <CardHeader>
            <CardTitle>Budget</CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-3 gap-4">
            <Figure
              label="Budget"
              value={data.budget_thb ? formatThb(data.budget_thb) : "—"}
            />
            <Figure
              label="Consumed cost"
              value={formatThb(data.consumed_cost_thb)}
            />
            <Figure
              label="Remaining"
              value={remaining ? formatThb(remaining) : "—"}
            />
          </CardContent>
        </Card>
      )}

      {isAdmin ? <ConsumedItems rows={data.consumed_items} /> : null}

      <RequestHistory projectId={projectId} />
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
      <h2 className="text-lg font-semibold">Consumed items</h2>
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

/**
 * Every stock request raised for this project, newest first, with what was
 * asked for, given out and brought back. No cost here, so staff see it too.
 */
function RequestHistory({ projectId }: { projectId: string }) {
  const { page, pageSize, skip, limit, setPage } = usePagination()
  const { data } = useQuery({
    queryKey: ["project-pulls", "project", projectId, { skip, limit }],
    queryFn: () =>
      ProjectPullsService.readProjectPulls({ projectId, skip, limit }),
  })
  const pulls = data?.data ?? []

  return (
    <div className="space-y-2">
      <h2 className="text-lg font-semibold">Request history</h2>
      {pulls.length === 0 ? (
        <p className="text-muted-foreground py-6 text-center text-sm">
          No requests yet.
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Item</TableHead>
              <TableHead className="text-right">Requested</TableHead>
              <TableHead className="text-right">Given</TableHead>
              <TableHead className="text-right">Returned</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {pulls.map((pull) => (
              <Fragment key={pull.id}>
                <TableRow className="bg-muted/40 hover:bg-muted/40">
                  <TableCell colSpan={4}>
                    <div className="flex flex-wrap items-center gap-3">
                      <span className="num font-medium">
                        {new Date(pull.created_at).toLocaleString()}
                      </span>
                      <Badge variant={STATE_VARIANT[pull.state]}>
                        {STATE_LABEL[pull.state]}
                      </Badge>
                      {pull.admin_notes ? (
                        <span className="text-muted-foreground truncate text-sm">
                          {pull.admin_notes}
                        </span>
                      ) : null}
                    </div>
                  </TableCell>
                </TableRow>
                {pull.lines.map((line) => {
                  const returned = returnedQty(pull, line)
                  return (
                    <TableRow key={line.id}>
                      <TableCell className="pl-6">
                        {line.line_kind === "UNIT"
                          ? `${line.model_name} · ${lineLabel(line)}`
                          : lineLabel(line)}
                      </TableCell>
                      <TableCell className="num text-right">
                        {/* A UNIT line is one serial, so it carries no qty. */}
                        {line.requested_qty ?? 1}
                      </TableCell>
                      <TableCell className="num text-right">
                        {pull.state === "PENDING" ? "—" : line.fulfilled_qty}
                      </TableCell>
                      <TableCell className="num text-right">
                        {returned > 0 ? returned : "—"}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </Fragment>
            ))}
          </TableBody>
        </Table>
      )}
      <PaginationControls
        total={data?.count ?? 0}
        pageSize={pageSize}
        page={page}
        onPageChange={setPage}
      />
    </div>
  )
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div className="space-y-1">
      <p className="text-muted-foreground text-xs uppercase tracking-wide">
        {label}
      </p>
      <p className="num text-lg font-semibold">{value}</p>
    </div>
  )
}
