import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { Pencil } from "lucide-react"
import { useMemo, useState } from "react"

import {
  type ProjectPublic,
  type ProjectStatus,
  ProjectsService,
} from "@/client"
import { EntityCombobox } from "@/components/Common/EntityCombobox"
import { ListFilters } from "@/components/Common/ListFilters"
import { ListShell } from "@/components/Common/ListShell"
import { ListTable } from "@/components/Common/ListTable"
import { PageHeader } from "@/components/Common/PageHeader"
import { PaginationControls } from "@/components/Common/PaginationControls"
import { ProjectCreateDialog } from "@/components/projects/ProjectCreateDialog"
import { ProjectEditDialog } from "@/components/projects/ProjectEditDialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { TableCell, TableHead, TableRow } from "@/components/ui/table"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useCustomerOptions } from "@/hooks/useCustomerOptions"
import { useDebouncedValue } from "@/hooks/useDebouncedValue"
import { useIsMobile } from "@/hooks/useMobile"
import { usePagination } from "@/hooks/usePagination"
import { requireAdmin } from "@/lib/route-guards"

type StatusFilter = "ALL" | ProjectStatus

// Column widths in header order (Code, Name, Customer, Status, edit); sum to 100%.
const PROJECT_WIDTHS = ["14%", "30%", "27%", "14%", "15%"]

export const Route = createFileRoute("/_layout/projects")({
  component: Projects,
  beforeLoad: () => requireAdmin(),
  head: () => ({
    meta: [{ title: "Projects - CastraNova POS" }],
  }),
})

function Projects() {
  const isMobile = useIsMobile()
  const [editing, setEditing] = useState<ProjectPublic | null>(null)
  const [search, setSearch] = useState("")
  const [customerId, setCustomerId] = useState("")
  const [status, setStatus] = useState<StatusFilter>("ALL")
  const debouncedSearch = useDebouncedValue(search)
  const { page, pageSize, skip, limit, setPage, reset } = usePagination()
  const activeCount = [
    debouncedSearch,
    customerId,
    status !== "ALL" ? status : "",
  ].filter(Boolean).length
  const hasActiveFilter = activeCount > 0
  const clearFilters = () => {
    setSearch("")
    setCustomerId("")
    setStatus("ALL")
    reset()
  }

  const {
    data: projectPage,
    isPlaceholderData,
    isFetching,
  } = useQuery({
    queryKey: [
      "projects",
      { skip, limit, q: debouncedSearch, customerId, status },
    ],
    queryFn: () =>
      ProjectsService.readProjects({
        skip,
        limit,
        q: debouncedSearch || undefined,
        customerId: customerId || undefined,
        status: status === "ALL" ? undefined : status,
      }),
    placeholderData: keepPreviousData,
  })
  const listLoading = isPlaceholderData || isFetching
  const { data: customers = [] } = useCustomerOptions()
  const projects = projectPage?.data ?? []

  const customerLabels = useMemo(
    () => new Map(customers.map((c) => [c.id, c.name])),
    [customers],
  )

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Projects"
        description="Create and review project records used by pulls."
        actions={<ProjectCreateDialog customers={customers} />}
      />

      <ListFilters activeCount={activeCount} onClear={clearFilters}>
        <Input
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
            reset()
          }}
          placeholder="Search code or name…"
          className="w-full sm:w-64"
        />
        <div className="w-full sm:w-56">
          <EntityCombobox
            items={customers}
            value={customerId || undefined}
            onChange={(next) => {
              setCustomerId(next ?? "")
              reset()
            }}
            getKey={(c) => c.id}
            getLabel={(c) => c.name}
            placeholder="All customers"
            searchPlaceholder="Search customers…"
            emptyText="No customers available"
            allowClear
            ariaLabel="Customer filter"
          />
        </div>
        <Tabs
          value={status}
          onValueChange={(v) => {
            setStatus(v as StatusFilter)
            reset()
          }}
        >
          <TabsList>
            <TabsTrigger value="ALL">All</TabsTrigger>
            <TabsTrigger value="ACTIVE">Active</TabsTrigger>
            <TabsTrigger value="CLOSED">Closed</TabsTrigger>
          </TabsList>
        </Tabs>
      </ListFilters>

      <div className="space-y-2">
        <ListShell loading={listLoading}>
          {projects.length === 0 ? (
            <p className="text-muted-foreground py-6 text-center text-sm">
              {!projectPage
                ? "Loading…"
                : hasActiveFilter
                  ? "No projects match the current filters."
                  : "No projects yet."}
            </p>
          ) : isMobile ? (
            <div className="space-y-3">
              {projects.map((p) => (
                <div key={p.id} className="bg-card rounded-lg border p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <Link
                        to="/project/$projectId"
                        params={{ projectId: p.id }}
                        className="num font-medium hover:underline"
                      >
                        {p.code}
                      </Link>
                      <p className="truncate text-sm">{p.name}</p>
                    </div>
                    <Badge variant="secondary">{p.status ?? "ACTIVE"}</Badge>
                  </div>
                  <div className="mt-3 flex justify-between gap-3 border-t pt-3 text-sm">
                    <span className="text-muted-foreground">Customer</span>
                    <Link
                      to="/customer/$customerId"
                      params={{ customerId: p.customer_id }}
                      className="truncate hover:underline"
                    >
                      {customerLabels.get(p.customer_id) ?? p.customer_id}
                    </Link>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <ListTable
              widths={PROJECT_WIDTHS}
              minWidth={820}
              head={
                <TableRow>
                  <TableHead>Code</TableHead>
                  <TableHead>Name</TableHead>
                  <TableHead>Customer</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right" />
                </TableRow>
              }
            >
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
                  <TableCell className="text-muted-foreground">
                    <Link
                      to="/customer/$customerId"
                      params={{ customerId: p.customer_id }}
                      className="hover:underline"
                    >
                      {customerLabels.get(p.customer_id) ?? p.customer_id}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary">{p.status ?? "ACTIVE"}</Badge>
                  </TableCell>
                  <TableCell className="overflow-visible! text-right">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => setEditing(p)}
                    >
                      <Pencil className="mr-1 size-4" />
                      Edit
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </ListTable>
          )}
        </ListShell>
        <PaginationControls
          total={projectPage?.count ?? 0}
          pageSize={pageSize}
          page={page}
          onPageChange={setPage}
        />
      </div>

      {editing && (
        <ProjectEditDialog
          project={editing}
          customers={customers}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  )
}
