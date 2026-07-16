import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Pencil } from "lucide-react"
import { useId, useState } from "react"

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
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { LoadingButton } from "@/components/ui/loading-button"
import useCustomToast from "@/hooks/useCustomToast"
import {
  buildProductUpdate,
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
}: {
  label: string
  value: string
  onChange?: (v: string) => void
  type?: string
  numeric?: boolean
  disabled?: boolean
  placeholder?: string
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

export function EditProductDialog({ product }: { product: ProductPublic }) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<ProductEditDraft>(() =>
    productToDraft(product),
  )
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  // Reseed the form from the latest product each time the dialog opens.
  function onOpenChange(next: boolean) {
    if (next) setDraft(productToDraft(product))
    setOpen(next)
  }

  function patch(key: keyof ProductEditDraft, value: string) {
    setDraft((prev) => ({ ...prev, [key]: value }))
  }

  const mutation = useMutation({
    mutationFn: () =>
      ProductsService.updateProduct({
        productId: product.id,
        requestBody: buildProductUpdate(draft),
      }),
    onSuccess: () => {
      showSuccessToast("Product updated")
      setOpen(false)
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["products"] })
      queryClient.invalidateQueries({ queryKey: ["price-history", product.id] })
    },
  })

  // Don't fire a no-op PATCH (which would still bump updated_at) when nothing
  // changed; both sides compare the same SKU/tracking-free editable draft.
  const isUnchanged =
    JSON.stringify(draft) === JSON.stringify(productToDraft(product))

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button type="button" variant="outline" size="sm">
          <Pencil className="mr-1 size-4" />
          Edit
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Edit product — {product.sku}</DialogTitle>
          <DialogDescription>
            Update this product's details and pricing. Changing a price is
            recorded in its price history.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-2 sm:grid-cols-2">
          <EditField label="SKU" value={product.sku} disabled />
          <EditField
            label="Tracking"
            value={product.tracking_mode ?? "QUANTITY"}
            disabled
          />
          <EditField
            label="Model name"
            value={draft.modelName}
            onChange={(v) => patch("modelName", v)}
            placeholder="e.g. iPhone 15 Pro"
          />
          <EditField
            label="Brand"
            value={draft.brand}
            onChange={(v) => patch("brand", v)}
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
            label="Retail price (THB)"
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
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline" disabled={mutation.isPending}>
              Cancel
            </Button>
          </DialogClose>
          <LoadingButton
            type="button"
            loading={mutation.isPending}
            disabled={!canSaveProduct(draft) || isUnchanged}
            onClick={() => mutation.mutate()}
          >
            Save
          </LoadingButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
