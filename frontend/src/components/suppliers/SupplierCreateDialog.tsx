import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Plus } from "lucide-react"
import { useState } from "react"

import {
  type SupplierCreate,
  type SupplierPublic,
  SuppliersService,
} from "@/client"
import { SupplierFieldset } from "@/components/suppliers/SupplierFieldset"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import useCustomToast from "@/hooks/useCustomToast"
import {
  buildSupplierPayload,
  canCreateSupplier,
  type SupplierDraft,
} from "@/lib/supplier-create"

const EMPTY_DRAFT: SupplierDraft = { name: "", country: "", contact: "" }

/** "New supplier" — the register form behind a dialog, off the Suppliers page header. */
export function SupplierCreateDialog() {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()

  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<SupplierDraft>(EMPTY_DRAFT)

  const reset = () => setDraft(EMPTY_DRAFT)

  const mutation = useMutation<SupplierPublic, Error, SupplierCreate>({
    mutationFn: (payload) =>
      SuppliersService.createSupplier({ requestBody: payload }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["suppliers"] })
      queryClient.invalidateQueries({ queryKey: ["supplier-countries"] })
      showSuccessToast("Supplier created.")
      setOpen(false)
      reset()
    },
    onError: () =>
      showErrorToast("Could not create the supplier. Please try again."),
  })

  const canSubmit = canCreateSupplier(draft) && !mutation.isPending

  return (
    <Dialog
      open={open}
      // Required by the Country field's EntityCombobox — see EntityCombobox.tsx.
      modal={false}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) reset()
      }}
    >
      <DialogTrigger asChild>
        <Button type="button">
          <Plus className="mr-2 size-4" aria-hidden="true" />
          New supplier
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New supplier</DialogTitle>
        </DialogHeader>
        <SupplierFieldset
          draft={draft}
          onChange={(patch) => setDraft((d) => ({ ...d, ...patch }))}
        />
        <DialogFooter>
          <Button
            type="button"
            disabled={!canSubmit}
            onClick={() => mutation.mutate(buildSupplierPayload(draft))}
          >
            {mutation.isPending ? "Creating…" : "Create supplier"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
