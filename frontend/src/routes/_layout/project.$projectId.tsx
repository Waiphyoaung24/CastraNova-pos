import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { Fragment, useState } from "react"

import type { ProjectConsumptionRowPublic } from "@/client"
import { ProjectsService } from "@/client"
import { PageHeader } from "@/components/Common/PageHeader"
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
import {
  budgetRemaining,
  consumedItemLabel,
  isAdminProjectDashboard,
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

  const { project, pulls } = data
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

      <div className="space-y-2">
        <h2 className="text-lg font-semibold">Pulls</h2>
        {pulls.length === 0 ? (
          <p className="text-muted-foreground py-6 text-center text-sm">
            No pulls yet.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Reference</TableHead>
                <TableHead>When</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pulls.map((t) => (
                <TableRow key={t.reference_id}>
                  <TableCell className="num font-medium">
                    {t.reference_id}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {new Date(t.occurred_at).toLocaleString()}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </div>
  )
}

/**
 * FR-020 consumed-items list: one row per PROJECT_OUT movement, admin-only
 * (it carries cost). A PART row expands to the FIFO batches its cost came from
 * — that is the "batch attribution" the PRD asks for. A UNIT row has nothing to
 * expand: a serialized unit is its own cost layer.
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
                      {r.quantity}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {new Date(r.occurred_at).toLocaleString()}
                    </TableCell>
                    <TableCell className="num text-right">
                      {formatThb(r.total_cost_thb)}
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
                            {d.quantity}
                          </TableCell>
                          <TableCell className="text-muted-foreground text-xs">
                            @ {formatThb(d.unit_cost_thb)}
                          </TableCell>
                          <TableCell className="num text-muted-foreground text-right text-xs">
                            {formatThb(d.total_cost_thb)}
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
