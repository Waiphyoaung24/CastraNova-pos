import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { FolderKanban, Pencil } from "lucide-react"
import { useId, useMemo, useState } from "react"

import {
  type ProjectCreate,
  type ProjectPublic,
  ProjectsService,
} from "@/client"
import { PageHeader } from "@/components/Common/PageHeader"
import { ProjectEditDialog } from "@/components/projects/ProjectEditDialog"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { EntityCombobox } from "@/components/Common/EntityCombobox"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import useCustomToast from "@/hooks/useCustomToast"
import { useIsMobile } from "@/hooks/useMobile"
import { useCustomerOptions } from "@/hooks/useCustomerOptions"
import { usePagination } from "@/hooks/usePagination"
import { PaginationControls } from "@/components/Common/PaginationControls"
import { buildProjectPayload, canCreateProject } from "@/lib/project-create"
import { requireAdmin } from "@/lib/route-guards"

export const Route = createFileRoute("/_layout/projects")({
  component: Projects,
  beforeLoad: () => requireAdmin(),
  head: () => ({
    meta: [{ title: "Projects - CastraNova POS" }],
  }),
})

function Projects() {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()
  const isMobile = useIsMobile()
  const codeId = useId()
  const nameId = useId()

  const [code, setCode] = useState("")
  const [name, setName] = useState("")
  const [customerId, setCustomerId] = useState("")
  const [editing, setEditing] = useState<ProjectPublic | null>(null)
  const { page, pageSize, skip, limit, setPage } = usePagination()

  const { data: projectPage } = useQuery({
    queryKey: ["projects", { skip, limit }],
    queryFn: () => ProjectsService.readProjects({ skip, limit }),
    placeholderData: keepPreviousData,
  })
  const { data: customers = [] } = useCustomerOptions()
  const projects = projectPage?.data ?? []

  const customerLabels = useMemo(
    () => new Map(customers.map((c) => [c.id, c.name])),
    [customers],
  )

  const createMutation = useMutation<ProjectPublic, Error, ProjectCreate>({
    mutationFn: (payload) =>
      ProjectsService.createProject({ requestBody: payload }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] })
      setCode("")
      setName("")
      setCustomerId("")
      showSuccessToast("Project created.")
    },
    onError: () =>
      showErrorToast("Could not create the project. Please try again."),
  })

  const canCreate =
    canCreateProject({ code, name, customerId }) && !createMutation.isPending

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Projects"
        description="Create and review project records used by pulls."
      />

      <Alert>
        <FolderKanban />
        <AlertTitle>Manage your projects</AlertTitle>
        <AlertDescription>
          Set up a project with its code, name, and customer so warehouse pulls
          can be raised against it. Open any project's code in the list to view
          its full record.
        </AlertDescription>
      </Alert>

      <Card>
        <CardHeader>
          <CardTitle>New project</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor={codeId}>Code</Label>
            <Input
              id={codeId}
              value={code}
              maxLength={64}
              placeholder="e.g. PRJ-001"
              onChange={(e) => setCode(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={nameId}>Name</Label>
            <Input
              id={nameId}
              value={name}
              maxLength={255}
              placeholder="e.g. Downtown store fit-out"
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label>Customer</Label>
            <EntityCombobox
              items={customers}
              value={customerId}
              onChange={(id) => setCustomerId(id ?? "")}
              getKey={(customer) => customer.id}
              getLabel={(customer) => customer.name}
              placeholder="Select a customer"
              searchPlaceholder="Search customers…"
              emptyText="No customers available"
              ariaLabel="Customer"
            />
          </div>
          <Button
            type="button"
            disabled={!canCreate}
            onClick={() =>
              createMutation.mutate(
                buildProjectPayload({ code, name, customerId }),
              )
            }
          >
            {createMutation.isPending ? "Creating…" : "Create project"}
          </Button>
        </CardContent>
      </Card>

      <div className="space-y-2">
        <h2 className="text-lg font-semibold">Existing projects</h2>
        {projects.length === 0 ? (
          <p className="text-muted-foreground py-6 text-center text-sm">
            No projects yet.
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
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Code</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Customer</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right" />
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
                  <TableCell className="text-right">
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
            </TableBody>
          </Table>
        )}
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
