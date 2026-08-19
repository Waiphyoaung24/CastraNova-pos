import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useEffect, useId, useRef, useState } from "react"

import { type ProductPublic, ProductsService } from "@/client"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { LoadingButton } from "@/components/ui/loading-button"
import useCustomToast from "@/hooks/useCustomToast"
import { useRole } from "@/hooks/useRole"
import {
  buildAutoSku,
  generateSkuBase,
  randomSkuSuffix,
} from "@/lib/product-create"
import {
  buildProductUpdate,
  canDeleteProduct,
  canSaveProduct,
  type ProductEditDraft,
  productToDraft,
} from "@/lib/product-edit"
import { handleError } from "@/utils"

/** One labelled text/number input row, matching the create form's Field. */
function EditField({
  label,
  value,
  onChange,
  type = "text",
  numeric = false,
  disabled = false,
  placeholder,
  hint,
}: {
  label: string
  value: string
  onChange?: (v: string) => void
  type?: string
  numeric?: boolean
  disabled?: boolean
  placeholder?: string
  hint?: string
}) {
  const id = useId()
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type={type}
        value={value}
        disabled={disabled}
        placeholder={placeholder}
        onChange={(e) => onChange?.(e.target.value)}
        className={numeric ? "num" : undefined}
        {...(numeric ? { inputMode: "decimal" as const } : {})}
        {...(type === "number" ? { min: 0 } : {})}
      />
      {hint ? <p className="text-muted-foreground text-xs">{hint}</p> : null}
    </div>
  )
}

/** The active/retired toggle plus its consequence note. Spans the grid. */
function ActiveField({
  checked,
  onChange,
}: {
  checked: boolean
  onChange: (v: boolean) => void
}) {
  const id = useId()
  return (
    <div className="space-y-2 sm:col-span-2">
      <div className="flex items-center gap-3">
        <Checkbox
          id={id}
          checked={checked}
          onCheckedChange={(v) => onChange(v === true)}
        />
        <Label htmlFor={id} className="font-normal">
          Active
        </Label>
      </div>
      <p className="text-muted-foreground text-xs">
        Retired products can't be sold, received, or used on tickets. Existing
        stock stays and can still be drained via Adjust.
      </p>
    </div>
  )
}

export function EditProductDialog({
  product,
  onClose,
}: {
  product: ProductPublic
  onClose: () => void
}) {
  const contentRef = useRef<HTMLDivElement>(null)
  const [draft, setDraft] = useState<ProductEditDraft>(() =>
    productToDraft(product),
  )
  // While the SKU is still editable (fresh product) and untouched by hand, it
  // auto-follows brand + model like the create form. The suffix is minted once
  // per dialog so it stays stable across brand/model edits.
  const [skuDirty, setSkuDirty] = useState(false)
  const [skuSuffix] = useState(randomSkuSuffix)
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  function onOpenChange(next: boolean) {
    if (!next) onClose()
  }

  function patch(key: keyof ProductEditDraft, value: string) {
    setDraft((prev) => ({ ...prev, [key]: value }))
  }

  // Brand/model edits re-suggest the SKU only on a fresh product whose SKU the
  // user hasn't hand-edited; otherwise they leave the SKU untouched.
  function patchIdentity(key: "brand" | "modelName", value: string) {
    setDraft((prev) => {
      const next = { ...prev, [key]: value }
      if (product.is_fresh && !skuDirty) {
        next.sku = buildAutoSku(
          generateSkuBase({ brand: next.brand, modelName: next.modelName }),
          skuSuffix,
        )
      }
      return next
    })
  }

  function handleSkuChange(value: string) {
    // A manual, non-empty edit locks auto-fill; clearing it resumes suggesting
    // from the current brand + model.
    const dirty = value.trim() !== ""
    setSkuDirty(dirty)
    setDraft((prev) => ({
      ...prev,
      sku: dirty
        ? value
        : buildAutoSku(
            generateSkuBase({ brand: prev.brand, modelName: prev.modelName }),
            skuSuffix,
          ),
    }))
  }

  const mutation = useMutation({
    mutationFn: () =>
      ProductsService.updateProduct({
        productId: product.id,
        requestBody: buildProductUpdate(draft),
      }),
    onSuccess: () => {
      showSuccessToast("Product updated")
      onClose()
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["products"] })
      queryClient.invalidateQueries({ queryKey: ["price-history", product.id] })
    },
  })

  const { isSuperuser } = useRole()
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  // When the confirm was armed, so a double-click can't sail through both
  // states and delete without the user ever seeing the confirmation.
  const armedAt = useRef(0)

  // A stray first click must not leave a live confirm sitting in the footer.
  useEffect(() => {
    if (!confirmingDelete) return
    const t = setTimeout(() => setConfirmingDelete(false), 4000)
    return () => clearTimeout(t)
  }, [confirmingDelete])

  function onDeleteClick() {
    if (!confirmingDelete) {
      armedAt.current = Date.now()
      setConfirmingDelete(true)
      return
    }
    // Too fast to be a deliberate second click — this is a double-click on the
    // still-unread "Delete" label. Swallow it and leave the confirm armed.
    if (Date.now() - armedAt.current < 500) return
    deleteMutation.mutate()
  }

  const deleteMutation = useMutation({
    mutationFn: () => ProductsService.deleteProduct({ productId: product.id }),
    onSuccess: () => {
      showSuccessToast("Product deleted")
      onClose()
    },
    // 409 here means the product gained stock in another tab since this dialog
    // rendered, or it has price history (append-only, so never deletable —
    // ProductPublic carries no flag for it, hence no way to hide the button).
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["products"] })
    },
  })

  // Don't fire a no-op PATCH (which would still bump updated_at) when nothing
  // changed; both sides compare the same SKU/tracking-free editable draft.
  const isUnchanged =
    JSON.stringify(draft) === JSON.stringify(productToDraft(product))

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent
        ref={contentRef}
        className="sm:max-w-md"
        onOpenAutoFocus={(e) => {
          e.preventDefault()
          contentRef.current?.focus()
        }}
      >
        <DialogHeader>
          <DialogTitle>Edit product — {product.sku}</DialogTitle>
          <DialogDescription>
            Update this product's details and pricing. Changing a price is
            recorded in its price history.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-2 sm:grid-cols-2">
          <EditField
            label="SKU"
            value={draft.sku}
            onChange={product.is_fresh ? handleSkuChange : undefined}
            disabled={!product.is_fresh}
            hint={
              product.is_fresh
                ? "Auto-generated from brand + model — edit to override."
                : "Locked — product already has stock or history."
            }
          />
          <EditField
            label="Tracking"
            value={product.tracking_mode ?? "QUANTITY"}
            disabled
          />
          <EditField
            label="Model name"
            value={draft.modelName}
            onChange={(v) => patchIdentity("modelName", v)}
            placeholder="e.g. iPhone 15 Pro"
          />
          <EditField
            label="Brand"
            value={draft.brand}
            onChange={(v) => patchIdentity("brand", v)}
            placeholder="e.g. Apple"
          />
          <EditField
            label="Category"
            value={draft.category}
            onChange={(v) => patch("category", v)}
            placeholder="e.g. Smartphone"
          />
          <EditField
            label="Min stock level"
            value={draft.minStock}
            onChange={(v) => patch("minStock", v)}
            type="number"
            numeric
            placeholder="e.g. 5"
          />
          <EditField
            label="Project price (THB)"
            value={draft.retailPrice}
            onChange={(v) => patch("retailPrice", v)}
            type="number"
            numeric
            placeholder="0.00"
          />
          <EditField
            label="Repair price (THB)"
            value={draft.repairPrice}
            onChange={(v) => patch("repairPrice", v)}
            type="number"
            numeric
            placeholder="0.00"
          />
          <ActiveField
            checked={draft.isActive}
            onChange={(v) => setDraft((prev) => ({ ...prev, isActive: v }))}
          />
        </div>
        <DialogFooter className="sm:justify-between">
          {canDeleteProduct(product, isSuperuser) ? (
            <LoadingButton
              type="button"
              variant={confirmingDelete ? "destructive" : "outline"}
              loading={deleteMutation.isPending}
              disabled={mutation.isPending}
              onClick={onDeleteClick}
            >
              {confirmingDelete ? "Click again to delete" : "Delete"}
            </LoadingButton>
          ) : (
            <span />
          )}
          <div className="flex flex-col-reverse gap-2 sm:flex-row">
            <DialogClose asChild>
              <Button
                variant="outline"
                disabled={mutation.isPending || deleteMutation.isPending}
              >
                Cancel
              </Button>
            </DialogClose>
            <LoadingButton
              type="button"
              loading={mutation.isPending}
              disabled={
                !canSaveProduct(draft) ||
                isUnchanged ||
                deleteMutation.isPending
              }
              onClick={() => mutation.mutate()}
            >
              Save
            </LoadingButton>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
