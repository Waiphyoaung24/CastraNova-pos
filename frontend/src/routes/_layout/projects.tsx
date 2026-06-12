import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { useId, useMemo, useState } from "react"

import {
  CustomersService,
  type ProjectCreate,
  type ProjectPublic,
  ProjectsService,
} from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import useCustomToast from "@/hooks/useCustomToast"
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
  const codeId = useId()
  const nameId = useId()
  const customerSelectId = useId()

  const [code, setCode] = useState("")
  const [name, setName] = useState("")
  const [customerId, setCustomerId] = useState("")

  const { data: projects } = useQuery({
    queryKey: ["projects"],
    queryFn: () => ProjectsService.readProjects(),
  })
  const { data: customers } = useQuery({
    queryKey: ["customers"],
    queryFn: () => CustomersService.readCustomers(),
    staleTime: 5 * 60 * 1000,
  })

  const customerLabels = useMemo(
    () => new Map((customers ?? []).map((c) => [c.id, c.name])),
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
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Projects</h1>
        <p className="text-muted-foreground">
          Create and review project records used by pulls.
        </p>
      </div>

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
              onChange={(e) => setCode(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={nameId}>Name</Label>
            <Input
              id={nameId}
              value={name}
              maxLength={255}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={customerSelectId}>Customer</Label>
            <Select value={customerId} onValueChange={setCustomerId}>
              <SelectTrigger id={customerSelectId} className="w-full">
                <SelectValue placeholder="Select a customer" />
              </SelectTrigger>
              <SelectContent>
                {(customers ?? []).map((c) => (
                  <SelectItem key={c.id} value={c.id}>
                    {c.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
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
        {(projects ?? []).length === 0 ? (
          <p className="text-muted-foreground py-6 text-center text-sm">
            No projects yet.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Code</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Customer</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(projects ?? []).map((p) => (
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
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </div>
  )
}
