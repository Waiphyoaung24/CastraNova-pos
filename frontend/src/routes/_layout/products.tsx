import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Package } from "lucide-react"
import { useState } from "react"

import { ProductsService } from "@/client"
import type { TrackingMode } from "@/client/types.gen"
import { ListShell } from "@/components/Common/ListShell"
import { ListTable } from "@/components/Common/ListTable"
import { PageHeader } from "@/components/Common/PageHeader"
import { PaginationControls } from "@/components/Common/PaginationControls"
import { EmptyState } from "@/components/EmptyState"
import { EditProductDialog } from "@/components/products/EditProductDialog"
import { ProductCreateDialog } from "@/components/products/ProductCreateDialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
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
import { useDebouncedValue } from "@/hooks/useDebouncedValue"
import { usePagination } from "@/hooks/usePagination"
import { trackingModeLabel } from "@/lib/labels"
import { formatThb } from "@/lib/reports"
import { requireAdmin } from "@/lib/route-guards"
import { cn } from "@/lib/utils"

// Radix Select forbids an empty-string item value, so "all" uses a sentinel.
const ALL = "__all__"

// Admin-only catalog management (FR-001) + per-product price history (FR-002).
export const Route = createFileRoute("/_layout/products")({
  component: Products,
  beforeLoad: () => requireAdmin(),
  head: () => ({
    meta: [{ title: "Products - CastraNova POS" }],
  }),
})

// Column widths in header order (SKU, Model, Brand, Category, Tracking,
// Status, Purchase, Retail, Repair, History); sum to 100%.
const PRODUCT_WIDTHS = [
  "11%",
  "15%",
  "8%",
  "9%",
  "9%",
  "8%",
  "8%",
  "8%",
  "8%",
  "16%",
]

function Products() {
  const [search, setSearch] = useState("")
  const [brand, setBrand] = useState("")
  const [category, setCategory] = useState("")
  const [trackingMode, setTrackingMode] = useState("")
  const debouncedSearch = useDebouncedValue(search)
  const debouncedBrand = useDebouncedValue(brand)
  const debouncedCategory = useDebouncedValue(category)
  const pagination = usePagination()
  const hasFilters = Boolean(
    debouncedSearch || debouncedBrand || debouncedCategory || trackingMode,
  )

  const {
    data: productsResponse,
    isPlaceholderData,
    isFetching,
  } = useQuery({
    queryKey: [
      "products",
      {
        page: pagination.page,
        q: debouncedSearch,
        brand: debouncedBrand,
        category: debouncedCategory,
        trackingMode,
      },
    ],
    queryFn: () =>
      ProductsService.readProducts({
        skip: pagination.skip,
        limit: pagination.limit,
        q: debouncedSearch || undefined,
        brand: debouncedBrand || undefined,
        category: debouncedCategory || undefined,
        trackingMode: (trackingMode || undefined) as TrackingMode | undefined,
      }),
    placeholderData: keepPreviousData,
  })
  const products = productsResponse?.data ?? []
  const listLoading = isPlaceholderData || isFetching
  const { data: purchaseCosts } = useQuery({
    queryKey: ["product-purchase-costs"],
    queryFn: () => ProductsService.readPurchaseCosts(),
  })
  const costByProductId = new Map(
    (purchaseCosts ?? []).map((c) => [
      c.product_id,
      String(c.latest_purchase_cost_thb),
    ]),
  )

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Products"
        description="Manage the catalog and review per-product price history."
        actions={<ProductCreateDialog />}
      />

      <div className="flex flex-wrap gap-3">
        <Input
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
            pagination.reset()
          }}
          placeholder="Search SKU or model…"
          className="w-full sm:w-64"
        />
        <Input
          value={brand}
          onChange={(e) => {
            setBrand(e.target.value)
            pagination.reset()
          }}
          placeholder="Brand…"
          aria-label="Brand filter"
          className="w-full sm:w-40"
        />
        <Input
          value={category}
          onChange={(e) => {
            setCategory(e.target.value)
            pagination.reset()
          }}
          placeholder="Category…"
          aria-label="Category filter"
          className="w-full sm:w-40"
        />
        <Select
          value={trackingMode === "" ? ALL : trackingMode}
          onValueChange={(v) => {
            setTrackingMode(v === ALL ? "" : v)
            pagination.reset()
          }}
        >
          <SelectTrigger
            className="w-full sm:w-40"
            aria-label="Tracking filter"
          >
            <SelectValue placeholder="All tracking" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All tracking</SelectItem>
            <SelectItem value="SERIALIZED">
              {trackingModeLabel("SERIALIZED")}
            </SelectItem>
            <SelectItem value="QUANTITY">
              {trackingModeLabel("QUANTITY")}
            </SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-2">
        <ListShell loading={listLoading}>
          {!productsResponse ? (
            <p className="text-muted-foreground py-6 text-center text-sm">
              Loading…
            </p>
          ) : products.length === 0 ? (
            <EmptyState
              icon={Package}
              title={
                hasFilters
                  ? "No products match these filters."
                  : "No products yet"
              }
              hint={
                hasFilters
                  ? undefined
                  : "Create your first product with the New product button above."
              }
            />
          ) : (
            <ListTable
              widths={PRODUCT_WIDTHS}
              minWidth={1140}
              head={
                <TableRow>
                  <TableHead>SKU</TableHead>
                  <TableHead>Model</TableHead>
                  <TableHead>Brand</TableHead>
                  <TableHead>Category</TableHead>
                  <TableHead>Tracking</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Purchase</TableHead>
                  <TableHead className="text-right">Retail</TableHead>
                  <TableHead className="text-right">Repair</TableHead>
                  <TableHead className="text-right">History</TableHead>
                </TableRow>
              }
            >
              {products.map((p) => (
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
                      {trackingModeLabel(p.tracking_mode ?? "QUANTITY")}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          "size-2 rounded-full",
                          p.is_active ? "bg-green-500" : "bg-gray-400",
                        )}
                      />
                      <span
                        className={p.is_active ? "" : "text-muted-foreground"}
                      >
                        {p.is_active ? "Active" : "Inactive"}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className="num text-right">
                    {costByProductId.has(p.id)
                      ? formatThb(costByProductId.get(p.id) as string)
                      : "—"}
                  </TableCell>
                  <TableCell className="num text-right">
                    {formatThb(p.retail_price_thb)}
                  </TableCell>
                  <TableCell className="num text-right">
                    {formatThb(p.repair_price_thb)}
                  </TableCell>
                  <TableCell className="overflow-visible! text-right">
                    <div className="flex justify-end gap-2">
                      <EditProductDialog product={p} />
                      <PriceHistoryDialog productId={p.id} sku={p.sku} />
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </ListTable>
          )}
        </ListShell>
        <PaginationControls
          total={productsResponse?.count ?? 0}
          pageSize={pagination.pageSize}
          page={pagination.page}
          onPageChange={pagination.setPage}
        />
      </div>
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
