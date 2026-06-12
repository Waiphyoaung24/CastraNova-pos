import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"

import { ProjectsService } from "@/client"
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
      <div>
        {isAdmin && (
          <Link
            to="/projects"
            className="text-muted-foreground text-sm hover:underline"
          >
            ← Projects
          </Link>
        )}
        <div className="mt-2 flex items-center gap-3">
          <h1 className="num text-2xl font-bold tracking-tight">
            {project.code}
          </h1>
          <Badge variant="secondary">{project.status ?? "ACTIVE"}</Badge>
        </div>
        <p className="text-muted-foreground">{project.name}</p>
        <Link
          to="/customer/$customerId"
          params={{ customerId: project.customer_id }}
          className="text-sm hover:underline"
        >
          View customer
        </Link>
      </div>

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
