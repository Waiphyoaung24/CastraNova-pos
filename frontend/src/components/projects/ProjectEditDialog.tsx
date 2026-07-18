import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useId, useState } from "react"

import {
  type CustomerOption,
  type ProjectPublic,
  ProjectsService,
} from "@/client"
import { EntityCombobox } from "@/components/Common/EntityCombobox"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import useCustomToast from "@/hooks/useCustomToast"
import {
  buildProjectUpdate,
  canSaveProject,
  type ProjectEditDraft,
  projectToEditDraft,
} from "@/lib/project-edit"

export function ProjectEditDialog({
  project,
  customers,
  onClose,
}: {
  project: ProjectPublic
  customers: CustomerOption[]
  onClose: () => void
}) {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()
  const codeId = useId()
  const nameId = useId()
  const customerSelectId = useId()
  const statusId = useId()
  const startId = useId()
  const endId = useId()
  const budgetId = useId()
  const [draft, setDraft] = useState<ProjectEditDraft>(() =>
    projectToEditDraft(project),
  )
  // Baseline captured once at mount, so the dirty-check compares against what
  // the user started editing (not a value shifted by a background refetch).
  const [baseline] = useState(() => projectToEditDraft(project))

  function patch(p: Partial<ProjectEditDraft>) {
    setDraft((d) => ({ ...d, ...p }))
  }

  const mutation = useMutation<ProjectPublic, Error, void>({
    mutationFn: () =>
      ProjectsService.updateProject({
        projectId: project.id,
        requestBody: buildProjectUpdate(draft),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] })
      showSuccessToast("Project updated.")
      onClose()
    },
    onError: () =>
      showErrorToast("Could not update the project. Please try again."),
  })

  const isUnchanged = JSON.stringify(draft) === JSON.stringify(baseline)
  const canSave = canSaveProject(draft) && !isUnchanged && !mutation.isPending

  return (
    <Dialog
      open
      // The Customer field's popover combobox is portalled outside this
      // Dialog's DOM subtree; a modal Dialog's focus trap fights that
      // portal for focus (Radix issue: nested modal FocusScopes). Non-modal
      // keeps the overlay/close-on-outside-click behavior but drops the
      // trap, letting the combobox actually receive focus and keystrokes.
      modal={false}
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit project — {project.code}</DialogTitle>
          <DialogDescription>
            Update this project's details. Code can't be changed.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor={codeId}>Code</Label>
            <Input id={codeId} value={project.code} disabled readOnly />
          </div>
          <div className="space-y-2">
            <Label htmlFor={nameId}>Name</Label>
            <Input
              id={nameId}
              value={draft.name}
              placeholder="e.g. Downtown store fit-out"
              onChange={(e) => patch({ name: e.target.value })}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={customerSelectId}>Customer</Label>
            <EntityCombobox
              id={customerSelectId}
              items={customers}
              value={draft.customerId || undefined}
              onChange={(next) => patch({ customerId: next ?? "" })}
              getKey={(c) => c.id}
              getLabel={(c) => c.name}
              placeholder="Select a customer"
              searchPlaceholder="Search customers…"
              emptyText="No customers available"
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={statusId}>Status</Label>
            <Select
              value={draft.status}
              onValueChange={(v) =>
                patch({ status: v as ProjectEditDraft["status"] })
              }
            >
              <SelectTrigger id={statusId} className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ACTIVE">Active</SelectItem>
                <SelectItem value="CLOSED">Closed</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor={startId}>Start date</Label>
              <Input
                id={startId}
                type="date"
                value={draft.startDate}
                onChange={(e) => patch({ startDate: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor={endId}>End date</Label>
              <Input
                id={endId}
                type="date"
                value={draft.endDate}
                onChange={(e) => patch({ endDate: e.target.value })}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor={budgetId}>Budget (THB)</Label>
            <Input
              id={budgetId}
              type="number"
              min={0}
              inputMode="decimal"
              className="num"
              placeholder="0.00"
              value={draft.budget}
              onChange={(e) => patch({ budget: e.target.value })}
            />
          </div>
        </div>
        <DialogFooter>
          <Button
            type="button"
            disabled={!canSave}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
