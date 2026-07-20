import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { type SupplierPublic, SuppliersService } from "@/client"
import { SupplierFieldset } from "@/components/suppliers/SupplierFieldset"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import useCustomToast from "@/hooks/useCustomToast"
import {
  buildSupplierPayload,
  canCreateSupplier,
  type SupplierDraft,
} from "@/lib/supplier-create"

export function SupplierEditDialog({
  supplier,
  onClose,
}: {
  supplier: SupplierPublic
  onClose: () => void
}) {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<SupplierDraft>({
    name: supplier.name,
    country: supplier.country ?? "",
    contact: supplier.contact ?? "",
  })

  const mutation = useMutation<SupplierPublic, Error, void>({
    mutationFn: () =>
      SuppliersService.updateSupplier({
        supplierId: supplier.id,
        requestBody: buildSupplierPayload(draft),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["suppliers"] })
      queryClient.invalidateQueries({ queryKey: ["supplier-countries"] })
      showSuccessToast("Supplier updated.")
      onClose()
    },
    onError: () =>
      showErrorToast("Could not update the supplier. Please try again."),
  })

  // Skip a no-op PATCH (which would still bump updated_at) when nothing changed.
  const isUnchanged =
    draft.name === supplier.name &&
    draft.country === (supplier.country ?? "") &&
    draft.contact === (supplier.contact ?? "")
  const canSave =
    canCreateSupplier(draft) && !isUnchanged && !mutation.isPending

  return (
    <Dialog
      open
      // Required by the Country field's EntityCombobox — see EntityCombobox.tsx.
      modal={false}
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit supplier</DialogTitle>
          <DialogDescription>Update this supplier's details.</DialogDescription>
        </DialogHeader>
        <SupplierFieldset
          draft={draft}
          onChange={(patch) => setDraft((d) => ({ ...d, ...patch }))}
        />
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
