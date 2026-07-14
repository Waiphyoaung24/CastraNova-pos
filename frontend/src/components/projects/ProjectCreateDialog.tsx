import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Plus } from "lucide-react"
import { useId, useState } from "react"

import type { CustomerOption } from "@/client"
import {
  type ProjectCreate,
  type ProjectPublic,
  ProjectsService,
} from "@/client"
import { EntityCombobox } from "@/components/Common/EntityCombobox"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import useCustomToast from "@/hooks/useCustomToast"
import { buildProjectPayload, canCreateProject } from "@/lib/project-create"

/** "New project" — the register form behind a dialog, off the Projects page header. */
export function ProjectCreateDialog({
  customers,
}: {
  customers: CustomerOption[]
}) {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()
  const codeId = useId()
  const nameId = useId()
  const customerSelectId = useId()

  const [open, setOpen] = useState(false)
  const [code, setCode] = useState("")
  const [name, setName] = useState("")
  const [customerId, setCustomerId] = useState("")

  const reset = () => {
    setCode("")
    setName("")
    setCustomerId("")
  }

  const draft = { code, name, customerId }

  const mutation = useMutation<ProjectPublic, Error, ProjectCreate>({
    mutationFn: (payload) =>
      ProjectsService.createProject({ requestBody: payload }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] })
      showSuccessToast("Project created.")
      setOpen(false)
      reset()
    },
    onError: () =>
      showErrorToast("Could not create the project. Please try again."),
  })

  const canSubmit = canCreateProject(draft) && !mutation.isPending

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) reset()
      }}
    >
      <DialogTrigger asChild>
        <Button type="button">
          <Plus className="mr-2 size-4" aria-hidden="true" />
          New project
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New project</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
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
            <Label htmlFor={customerSelectId}>Customer</Label>
            <EntityCombobox
              id={customerSelectId}
              items={customers}
              value={customerId || undefined}
              onChange={(next) => setCustomerId(next ?? "")}
              getKey={(c) => c.id}
              getLabel={(c) => c.name}
              placeholder="Select a customer"
              searchPlaceholder="Search customers…"
              emptyText="No customers available"
              required
            />
          </div>
        </div>
        <DialogFooter>
          <Button
            type="button"
            disabled={!canSubmit}
            onClick={() => mutation.mutate(buildProjectPayload(draft))}
          >
            {mutation.isPending ? "Creating…" : "Create project"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
