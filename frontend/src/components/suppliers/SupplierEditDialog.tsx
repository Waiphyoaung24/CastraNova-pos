import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useId, useState } from "react"

import { type SupplierPublic, SuppliersService } from "@/client"
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
  const nameId = useId()
  const countryId = useId()
  const contactId = useId()
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
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit supplier</DialogTitle>
          <DialogDescription>Update this supplier's details.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor={nameId}>Name</Label>
            <Input
              id={nameId}
              value={draft.name}
              placeholder="e.g. Acme Trading Co."
              onChange={(e) =>
                setDraft((d) => ({ ...d, name: e.target.value }))
              }
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={countryId}>Country</Label>
            <Input
              id={countryId}
              value={draft.country}
              placeholder="e.g. Thailand"
              onChange={(e) =>
                setDraft((d) => ({ ...d, country: e.target.value }))
              }
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={contactId}>Contact</Label>
            <Input
              id={contactId}
              value={draft.contact}
              placeholder="Phone, email, or contact person"
              onChange={(e) =>
                setDraft((d) => ({ ...d, contact: e.target.value }))
              }
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
