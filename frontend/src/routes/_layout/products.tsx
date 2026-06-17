import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Package } from "lucide-react"
import { type ReactNode, useId, useState } from "react"

import {
  type ProductCreate,
  type ProductPublic,
  ProductsService,
  type TrackingMode,
} from "@/client"
import { PageHeader } from "@/components/Common/PageHeader"
import { EmptyState } from "@/components/EmptyState"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import useCustomToast from "@/hooks/useCustomToast"
import { buildProductPayload, canCreateProduct } from "@/lib/product-create"
import { formatThb } from "@/lib/reports"
import { requireAdmin } from "@/lib/route-guards"

// Admin-only catalog management (FR-001) + per-product price history (FR-002).
export const Route = createFileRoute("/_layout/products")({
  component: Products,
  beforeLoad: () => requireAdmin(),
  head: () => ({
    meta: [{ title: "Products - CastraNova POS" }],
  }),
})

const TRACKING_MODES: TrackingMode[] = ["QUANTITY", "SERIALIZED"]

function Products() {
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

  const [sku, setSku] = useState("")
  const [modelName, setModelName] = useState("")
  const [brand, setBrand] = useState("")
  const [category, setCategory] = useState("")
  const [trackingMode, setTrackingMode] = useState<TrackingMode>("QUANTITY")
  const [retailPrice, setRetailPrice] = useState("")
  const [repairPrice, setRepairPrice] = useState("")
  const [minStock, setMinStock] = useState("")

  const { data: products } = useQuery({
    queryKey: ["products"],
    queryFn: () => ProductsService.readProducts(),
  })

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

  const createMutation = useMutation<ProductPublic, Error, ProductCreate>({
    mutationFn: (payload) =>
      ProductsService.createProduct({ requestBody: payload }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["products"] })
      setSku("")
      setModelName("")
      setBrand("")
      setCategory("")
      setRetailPrice("")
      setRepairPrice("")
      setMinStock("")
      showSuccessToast("Product created.")
    },
    onError: () =>
      showErrorToast("Could not create the product. Please try again."),
  })

  const canCreate = canCreateProduct(draft) && !createMutation.isPending

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Products"
        description="Manage the catalog and review per-product price history."
      />

      <Alert>
        <Package />
        <AlertTitle>Set up a product line</AlertTitle>
        <AlertDescription>
          A product is the catalog entry every unit is sold and repaired against
          — its SKU, model, pricing, and how its stock is counted. Create one
          here, then review or revise its prices from the catalog below.
        </AlertDescription>
      </Alert>

      <Card>
        <CardHeader>
          <CardTitle>New product</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <SectionLabel>Identity</SectionLabel>
          <Field id={skuId} label="SKU" value={sku} onChange={setSku} />
          <Field
            id={modelId}
            label="Model name"
            value={modelName}
            onChange={setModelName}
          />
          <Field id={brandId} label="Brand" value={brand} onChange={setBrand} />
          <Field
            id={categoryId}
            label="Category"
            value={category}
            onChange={setCategory}
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
          />

          <SectionLabel>Pricing</SectionLabel>
          <Field
            id={retailId}
            label="Retail price (THB)"
            value={retailPrice}
            onChange={setRetailPrice}
            type="number"
            numeric
          />
          <Field
            id={repairId}
            label="Repair price (THB)"
            value={repairPrice}
            onChange={setRepairPrice}
            type="number"
            numeric
          />
          <div className="sm:col-span-2">
            <Button
              type="button"
              disabled={!canCreate}
              onClick={() => createMutation.mutate(buildProductPayload(draft))}
              className="w-full sm:w-auto"
            >
              {createMutation.isPending ? "Creating…" : "Create product"}
            </Button>
          </div>
        </CardContent>
      </Card>

      <div className="space-y-2">
        <h2 className="text-lg font-semibold">Catalog</h2>
        {(products ?? []).length === 0 ? (
          <EmptyState
            icon={Package}
            title="No products yet"
            hint="Create your first product with the form above."
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>SKU</TableHead>
                <TableHead>Model</TableHead>
                <TableHead>Brand</TableHead>
                <TableHead>Category</TableHead>
                <TableHead>Tracking</TableHead>
                <TableHead className="text-right">Retail</TableHead>
                <TableHead className="text-right">Repair</TableHead>
                <TableHead className="text-right">History</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(products ?? []).map((p) => (
                <TableRow key={p.id}>
                  <TableCell className="num font-medium">{p.sku}</TableCell>
                  <TableCell>{p.model_name}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {p.brand ?? "—"}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {p.category ?? "—"}
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary">
                      {p.tracking_mode ?? "QUANTITY"}
                    </Badge>
                  </TableCell>
                  <TableCell className="num text-right">
                    {formatThb(p.retail_price_thb)}
                  </TableCell>
                  <TableCell className="num text-right">
                    {formatThb(p.repair_price_thb)}
                  </TableCell>
                  <TableCell className="text-right">
                    <PriceHistoryDialog productId={p.id} sku={p.sku} />
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
}: {
  id: string
  label: string
  value: string
  onChange: (v: string) => void
  type?: string
  /** Tabular monospace + decimal keypad for prices/quantities. */
  numeric?: boolean
}) {
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={numeric ? "num" : undefined}
        {...(numeric ? { inputMode: "decimal" as const } : {})}
        {...(type === "number" ? { min: 0 } : {})}
      />
    </div>
  )
}

function PriceHistoryDialog({
  productId,
  sku,
}: {
  productId: string
  sku: string
}) {
  const [open, setOpen] = useState(false)
  // isLoading (not isPending) so a disabled/closed query doesn't show "Loading…".
  const { data, isLoading, isError } = useQuery({
    queryKey: ["price-history", productId],
    queryFn: () => ProductsService.readPriceHistory({ productId }),
    enabled: open,
  })
  const rows = data ?? []

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button type="button" variant="outline" size="sm">
          History
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Price history — {sku}</DialogTitle>
        </DialogHeader>
        {isLoading ? (
          <p className="text-muted-foreground py-4 text-center text-sm">
            Loading…
          </p>
        ) : isError ? (
          <p className="text-muted-foreground py-4 text-center text-sm">
            Could not load price history.
          </p>
        ) : rows.length === 0 ? (
          <p className="text-muted-foreground py-4 text-center text-sm">
            No price changes recorded.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Field</TableHead>
                <TableHead className="text-right">Old</TableHead>
                <TableHead className="text-right">New</TableHead>
                <TableHead>When</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((h) => (
                <TableRow key={h.id}>
                  <TableCell>{h.field}</TableCell>
                  <TableCell className="num text-right">
                    {h.old_value}
                  </TableCell>
                  <TableCell className="num text-right">
                    {h.new_value}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {h.changed_at
                      ? new Date(h.changed_at).toLocaleDateString()
                      : "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </DialogContent>
    </Dialog>
  )
}
