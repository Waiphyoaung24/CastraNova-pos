import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useId, useRef, useState } from "react"

import {
  type CustomerOption,
  type ProjectPublic,
  ProjectsService,
} from "@/client"
import { EntityCombobox } from "@/components/Common/EntityCombobox"
import { Button } from "@/components/ui/button"
import { DatePicker } from "@/components/ui/date-picker"
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
import { isValidDateRange } from "@/lib/project-form"

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
  const contentRef = useRef<HTMLDivElement>(null)
  const [draft, setDraft] = useState<ProjectEditDraft>(() =>
    projectToEditDraft(project),
  )
  // Baseline captured once at mount, so the dirty-check compares against what
  // the user started editing (not a value shifted by a background refetch).
  const [baseline] = useState(() => projectToEditDraft(project))
  // Which of this dialog's own date pickers are open — see onOpenChange below.
  const [pickerOpen, setPickerOpen] = useState({ start: false, end: false })

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
  const datesOutOfOrder = !isValidDateRange(draft.startDate, draft.endDate)

  return (
    <Dialog
      open
      // Required by the Customer field's EntityCombobox — see EntityCombobox.tsx.
      modal={false}
      onOpenChange={(next) => {
        // modal={false} keeps this Dialog listening for Escape at the document,
        // and Radix fires every layer's handler rather than only the topmost —
        // so dismissing an open date picker used to tear down the edit form
        // with it. The picker's own layer closes it; this one stands down while
        // one of ITS OWN pickers is open. Tracked as state rather than probed
        // from the DOM, so an unrelated popover elsewhere on the page can never
        // swallow a legitimate dismissal of this dialog.
        if (!next && (pickerOpen.start || pickerOpen.end)) return
        if (!next) onClose()
      }}
    >
      <DialogContent
        ref={contentRef}
        onOpenAutoFocus={(e) => {
          e.preventDefault()
          contentRef.current?.focus()
        }}
      >
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
              <Label id={`${startId}-label`} htmlFor={startId}>
                Start date
              </Label>
              <DatePicker
                id={startId}
                labelledBy={`${startId}-label`}
                value={draft.startDate}
                onChange={(iso) => patch({ startDate: iso })}
                onOpenChange={(o) => setPickerOpen((p) => ({ ...p, start: o }))}
                placeholder="No start date"
              />
            </div>
            <div className="space-y-2">
              <Label id={`${endId}-label`} htmlFor={endId}>
                End date
              </Label>
              <DatePicker
                id={endId}
                labelledBy={`${endId}-label`}
                value={draft.endDate}
                onChange={(iso) => patch({ endDate: iso })}
                onOpenChange={(o) => setPickerOpen((p) => ({ ...p, end: o }))}
                invalid={datesOutOfOrder}
                placeholder="No end date"
              />
            </div>
          </div>
          {datesOutOfOrder ? (
            <p role="alert" className="text-destructive text-sm">
              End date must be on or after the start date.
            </p>
          ) : null}
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
