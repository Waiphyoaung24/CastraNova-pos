import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Plus } from "lucide-react"
import { type ReactNode, useEffect, useId, useRef, useState } from "react"

import {
  type ProductCreate,
  type ProductPublic,
  ProductsService,
  type TrackingMode,
} from "@/client"
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import useCustomToast from "@/hooks/useCustomToast"
import {
  buildAutoSku,
  buildProductPayload,
  canCreateProduct,
  generateSkuBase,
  randomSkuSuffix,
} from "@/lib/product-create"

const TRACKING_MODES: TrackingMode[] = ["QUANTITY", "SERIALIZED"]

/** "New product" — the register form behind a dialog, off the Products page header. */
export function ProductCreateDialog() {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()
  const skuId = useId()
  const modelId = useId()
  const brandId = useId()
  const categoryId = useId()
  const retailId = useId()
  const repairId = useId()
  const minStockId = useId()
  const trackingId = useId()

  const contentRef = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [sku, setSku] = useState("")
  // Auto-suggest the SKU from brand + model until the user edits it by hand.
  // The suffix is minted once per dialog session so it stays stable while the
  // brand/model change (regenerated on reset).
  const [skuDirty, setSkuDirty] = useState(false)
  const [skuSuffix, setSkuSuffix] = useState(randomSkuSuffix)
  const [modelName, setModelName] = useState("")
  const [brand, setBrand] = useState("")
  const [category, setCategory] = useState("")
  const [trackingMode, setTrackingMode] = useState<TrackingMode>("QUANTITY")
  const [retailPrice, setRetailPrice] = useState("")
  const [repairPrice, setRepairPrice] = useState("")
  const [minStock, setMinStock] = useState("")

  useEffect(() => {
    if (skuDirty) return
    setSku(buildAutoSku(generateSkuBase({ brand, modelName }), skuSuffix))
  }, [brand, modelName, skuSuffix, skuDirty])

  const handleSkuChange = (v: string) => {
    setSku(v)
    // A manual, non-empty edit locks auto-fill; clearing the field resumes it.
    setSkuDirty(v.trim() !== "")
  }

  const reset = () => {
    setSku("")
    setSkuDirty(false)
    setSkuSuffix(randomSkuSuffix())
    setModelName("")
    setBrand("")
    setCategory("")
    setTrackingMode("QUANTITY")
    setRetailPrice("")
    setRepairPrice("")
    setMinStock("")
  }

  const draft = {
    sku,
    modelName,
    brand,
    category,
    trackingMode,
    retailPrice,
    repairPrice,
    minStock,
  }

  const mutation = useMutation<ProductPublic, Error, ProductCreate>({
    mutationFn: (payload) =>
      ProductsService.createProduct({ requestBody: payload }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["products"] })
      showSuccessToast("Product created.")
      setOpen(false)
      reset()
    },
    onError: () =>
      showErrorToast("Could not create the product. Please try again."),
  })

  const canSubmit = canCreateProduct(draft) && !mutation.isPending

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
          New product
        </Button>
      </DialogTrigger>
      <DialogContent
        ref={contentRef}
        className="sm:max-w-lg"
        onOpenAutoFocus={(e) => {
          e.preventDefault()
          contentRef.current?.focus()
        }}
      >
        <DialogHeader>
          <DialogTitle>New product</DialogTitle>
        </DialogHeader>
        <div className="grid gap-4 sm:grid-cols-2">
          <SectionLabel>Identity</SectionLabel>
          <Field
            id={skuId}
            label="SKU"
            value={sku}
            onChange={handleSkuChange}
            placeholder="e.g. IP15P-256-BLK"
            hint="Auto-generated from brand + model — edit to override."
          />
          <Field
            id={modelId}
            label="Model name"
            value={modelName}
            onChange={setModelName}
            placeholder="e.g. iPhone 15 Pro"
          />
          <Field
            id={brandId}
            label="Brand"
            value={brand}
            onChange={setBrand}
            placeholder="e.g. Apple"
          />
          <Field
            id={categoryId}
            label="Category"
            value={category}
            onChange={setCategory}
            placeholder="e.g. Smartphone"
          />

          <SectionLabel>Classification</SectionLabel>
          <div className="space-y-2">
            <Label htmlFor={trackingId}>Tracking</Label>
            <Select
              value={trackingMode}
              onValueChange={(v) => setTrackingMode(v as TrackingMode)}
            >
              <SelectTrigger id={trackingId} className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TRACKING_MODES.map((m) => (
                  <SelectItem key={m} value={m}>
                    {m}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-muted-foreground text-sm">
              Quantity counts stock as a number; Serialized tracks each unit by
              its own barcode.
            </p>
          </div>
          <Field
            id={minStockId}
            label="Min stock level"
            value={minStock}
            onChange={setMinStock}
            type="number"
            numeric
            placeholder="e.g. 5"
          />

          <SectionLabel>Pricing</SectionLabel>
          <Field
            id={retailId}
            label="Project price (THB)"
            value={retailPrice}
            onChange={setRetailPrice}
            type="number"
            numeric
            placeholder="0.00"
          />
          <Field
            id={repairId}
            label="Repair price (THB)"
            value={repairPrice}
            onChange={setRepairPrice}
            type="number"
            numeric
            placeholder="0.00"
          />
        </div>
        <DialogFooter>
          <Button
            type="button"
            disabled={!canSubmit}
            onClick={() => mutation.mutate(buildProductPayload(draft))}
          >
            {mutation.isPending ? "Creating…" : "Create product"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Full-width group heading inside the form grid — splits a long field list
 * into scannable sections (Identity / Classification / Pricing). */
function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <h3 className="text-muted-foreground col-span-full text-xs font-semibold tracking-wide uppercase not-first:mt-2">
      {children}
    </h3>
  )
}

function Field({
  id,
  label,
  value,
  onChange,
  type = "text",
  numeric = false,
  placeholder,
  hint,
}: {
  id: string
  label: string
  value: string
  onChange: (v: string) => void
  type?: string
  /** Tabular monospace + decimal keypad for prices/quantities. */
  numeric?: boolean
  /** Example/format hint shown when the field is empty. */
  placeholder?: string
  /** Helper text shown under the input. */
  hint?: string
}) {
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className={numeric ? "num" : undefined}
        {...(numeric ? { inputMode: "decimal" as const } : {})}
        {...(type === "number" ? { min: 0 } : {})}
      />
      {hint ? <p className="text-muted-foreground text-sm">{hint}</p> : null}
    </div>
  )
}
