import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"

import {
  CustomersService,
  type ProjectSummaryAdminPublic,
  type ProjectSummaryStaffPublic,
} from "@/client"
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
import { isAdminCustomerDashboard } from "@/lib/customer-dashboard"
import { formatThb } from "@/lib/reports"
import { requireAuth } from "@/lib/route-guards"

// Role-tiered (FR-020): both roles may view; lifetime revenue/COGS/margin and
// per-project budget/cost render only when the admin payload carries them. The
// backend redacts for staff; isAdminCustomerDashboard is the client guard.
export const Route = createFileRoute("/_layout/customer/$customerId")({
  component: CustomerDetail,
  beforeLoad: requireAuth,
  head: () => ({
    meta: [{ title: "Customer - CastraNova POS" }],
  }),
})

type ProjectSummary = ProjectSummaryAdminPublic | ProjectSummaryStaffPublic

function CustomerDetail() {
  const { customerId } = Route.useParams()

  const { data, isPending, isError } = useQuery({
    queryKey: ["customer-dashboard", customerId],
    queryFn: () => CustomersService.getCustomerDashboard({ customerId }),
  })

  if (isPending) {
    return (
      <p className="text-muted-foreground py-6 text-center text-sm">Loading…</p>
    )
  }
  if (isError || !data) {
    return (
      <p className="text-muted-foreground py-6 text-center text-sm">
        Could not load the customer.
      </p>
    )
  }

  const { customer, transactions, active_projects, closed_projects } = data
  const isAdmin = isAdminCustomerDashboard(data)

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
        title={customer.name}
        badge={
          <Badge variant="secondary">{customer.type ?? "END_CUSTOMER"}</Badge>
        }
        description={
          customer.contact || customer.country
            ? [customer.contact, customer.country].filter(Boolean).join(" · ")
            : undefined
        }
      />

      {isAdmin && (
        <Card>
          <CardHeader>
            <CardTitle>Lifetime financials</CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-2 gap-x-8 gap-y-4 sm:grid-cols-3">
            <Figure
              label="Sale revenue"
              value={formatThb(data.lifetime_sale_revenue_thb)}
            />
            <Figure
              label="Sale COGS"
              value={formatThb(data.lifetime_sale_cogs_thb)}
            />
            <Figure
              label="Sale margin"
              value={formatThb(data.lifetime_sale_margin_thb)}
            />
            <Figure
              label="Maintenance revenue"
              value={formatThb(data.lifetime_maintenance_revenue_thb)}
            />
            <Figure
              label="Maintenance COGS"
              value={formatThb(data.lifetime_maintenance_cogs_thb)}
            />
            <Figure
              label="Maintenance margin"
              value={formatThb(data.lifetime_maintenance_margin_thb)}
            />
            <Figure
              label="Project COGS"
              value={formatThb(data.lifetime_project_cogs_thb)}
            />
          </CardContent>
        </Card>
      )}

      <div className="space-y-2">
        <h2 className="text-lg font-semibold">Transactions</h2>
        {transactions.length === 0 ? (
          <p className="text-muted-foreground py-6 text-center text-sm">
            No transactions yet.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Kind</TableHead>
                <TableHead>Reference</TableHead>
                <TableHead>When</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {transactions.map((t) => (
                <TableRow key={`${t.kind}-${t.reference_id}`}>
                  <TableCell>{t.kind}</TableCell>
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

      <ProjectsSection
        title="Active projects"
        projects={active_projects}
        isAdmin={isAdmin}
      />
      <ProjectsSection
        title="Closed projects"
        projects={closed_projects}
        isAdmin={isAdmin}
      />
    </div>
  )
}

function ProjectsSection({
  title,
  projects,
  isAdmin,
}: {
  title: string
  projects: ProjectSummary[]
  isAdmin: boolean
}) {
  return (
    <div className="space-y-2">
      <h2 className="text-lg font-semibold">{title}</h2>
      {projects.length === 0 ? (
        <p className="text-muted-foreground py-6 text-center text-sm">None.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Code</TableHead>
              <TableHead>Name</TableHead>
              <TableHead>Status</TableHead>
              {isAdmin && (
                <>
                  <TableHead className="text-right">Budget</TableHead>
                  <TableHead className="text-right">Consumed</TableHead>
                </>
              )}
            </TableRow>
          </TableHeader>
          <TableBody>
            {projects.map((p) => (
              <TableRow key={p.id}>
                <TableCell className="num font-medium">
                  <Link
                    to="/project/$projectId"
                    params={{ projectId: p.id }}
                    className="hover:underline"
                  >
                    {p.code}
                  </Link>
                </TableCell>
                <TableCell>{p.name}</TableCell>
                <TableCell>
                  <Badge variant="secondary">{p.status}</Badge>
                </TableCell>
                {isAdmin && (
                  <>
                    <TableCell className="num text-right">
                      {"budget_thb" in p && p.budget_thb
                        ? formatThb(p.budget_thb)
                        : "—"}
                    </TableCell>
                    <TableCell className="num text-right">
                      {"consumed_cost_thb" in p
                        ? formatThb(p.consumed_cost_thb)
                        : "—"}
                    </TableCell>
                  </>
                )}
              </TableRow>
            ))}
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
