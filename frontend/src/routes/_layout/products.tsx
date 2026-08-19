import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { History, Package } from "lucide-react"
import type { KeyboardEvent } from "react"
import { useState } from "react"

import { type ProductPublic, ProductsService } from "@/client"
import type { TrackingMode } from "@/client/types.gen"
import { ListFilters } from "@/components/Common/ListFilters"
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
import { useIsMobile } from "@/hooks/useMobile"
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

// Column widths in header order (SKU, Model, Brand / Category, Tracking,
// Status, Pricing, History); sum to 100%.
const PRODUCT_WIDTHS = ["12%", "18%", "18%", "10%", "10%", "20%", "12%"]

function Products() {
  const [search, setSearch] = useState("")
  const [brand, setBrand] = useState("")
  const [category, setCategory] = useState("")
  const [trackingMode, setTrackingMode] = useState("")
  const [statusFilter, setStatusFilter] = useState("")
  const [editing, setEditing] = useState<ProductPublic | null>(null)
  const debouncedSearch = useDebouncedValue(search)
  const debouncedBrand = useDebouncedValue(brand)
  const debouncedCategory = useDebouncedValue(category)
  const pagination = usePagination()
  const isMobile = useIsMobile()
  const activeCount = [
    debouncedSearch,
    debouncedBrand,
    debouncedCategory,
    trackingMode,
    statusFilter,
  ].filter(Boolean).length
  const hasFilters = activeCount > 0
  const clearFilters = () => {
    setSearch("")
    setBrand("")
    setCategory("")
    setTrackingMode("")
    setStatusFilter("")
    pagination.reset()
  }

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
        statusFilter,
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
        isActive: statusFilter === "" ? undefined : statusFilter === "active",
      }),
    placeholderData: keepPreviousData,
  })
  const products = productsResponse?.data ?? []
  const listLoading = isPlaceholderData || isFetching
  const rowProps = (p: ProductPublic) => ({
    role: "button" as const,
    tabIndex: 0,
    "aria-label": `Edit ${p.model_name}`,
    onClick: () => setEditing(p),
    onKeyDown: (ev: KeyboardEvent) => {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault()
        setEditing(p)
      }
    },
  })
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

      <ListFilters activeCount={activeCount} onClear={clearFilters}>
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
        <Select
          value={statusFilter === "" ? ALL : statusFilter}
          onValueChange={(v) => {
            setStatusFilter(v === ALL ? "" : v)
            pagination.reset()
          }}
        >
          <SelectTrigger className="w-full sm:w-40" aria-label="Status filter">
            <SelectValue placeholder="All statuses" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All statuses</SelectItem>
            <SelectItem value="active">Active</SelectItem>
            <SelectItem value="inactive">Inactive</SelectItem>
          </SelectContent>
        </Select>
      </ListFilters>

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
          ) : isMobile ? (
            <div className="space-y-3">
              {products.map((p) => (
                <div
                  key={p.id}
                  {...rowProps(p)}
                  className="bg-card hover:bg-muted/50 focus-visible:ring-ring cursor-pointer rounded-lg border p-4 outline-none focus-visible:ring-2"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="font-medium">{p.model_name}</p>
                      <p className="num text-muted-foreground mt-0.5 text-xs">
                        {p.sku}
                      </p>
                    </div>
                    <Badge variant="secondary" className="shrink-0">
                      {trackingModeLabel(p.tracking_mode ?? "QUANTITY")}
                    </Badge>
                  </div>
                  <dl className="text-muted-foreground mt-3 grid grid-cols-[5rem_1fr] gap-y-1 border-t pt-3 text-sm">
                    <dt>Status</dt>
                    <dd className="flex items-center gap-2">
                      <span
                        className={cn(
                          "size-2 rounded-full",
                          p.is_active ? "bg-green-500" : "bg-gray-400",
                        )}
                      />
                      <span
                        className={p.is_active ? "text-foreground" : undefined}
                      >
                        {p.is_active ? "Active" : "Inactive"}
                      </span>
                    </dd>
                    <dt>Brand</dt>
                    <dd className="text-foreground truncate">
                      {p.brand ?? "—"}
                    </dd>
                    <dt>Category</dt>
                    <dd className="text-foreground truncate">
                      {p.category ?? "—"}
                    </dd>
                    <dt>Purchase</dt>
                    <dd className="num text-foreground">
                      {costByProductId.has(p.id)
                        ? formatThb(costByProductId.get(p.id) as string)
                        : "—"}
                    </dd>
                    <dt>Project</dt>
                    <dd className="num text-foreground">
                      {formatThb(p.retail_price_thb)}
                    </dd>
                  </dl>
                  <div className="mt-3 flex justify-end gap-2 border-t pt-3">
                    <PriceHistoryDialog productId={p.id} sku={p.sku} />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <ListTable
              widths={PRODUCT_WIDTHS}
              minWidth={920}
              head={
                <TableRow>
                  <TableHead>SKU</TableHead>
                  <TableHead>Model</TableHead>
                  <TableHead>Brand / Category</TableHead>
                  <TableHead>Tracking</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Pricing</TableHead>
                  <TableHead className="text-right">History</TableHead>
                </TableRow>
              }
            >
              {products.map((p) => (
                <TableRow
                  key={p.id}
                  {...rowProps(p)}
                  className="hover:bg-muted/50 focus-visible:bg-muted/50 cursor-pointer outline-none"
                >
                  <TableCell className="num font-medium">{p.sku}</TableCell>
                  <TableCell>{p.model_name}</TableCell>
                  <TableCell className="text-muted-foreground">
                    <div>{p.brand ?? "—"}</div>
                    <div className="text-xs">{p.category ?? "—"}</div>
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
                    <div>
                      Purchase:{" "}
                      {costByProductId.has(p.id)
                        ? formatThb(costByProductId.get(p.id) as string)
                        : "—"}
                    </div>
                    <div>Project: {formatThb(p.retail_price_thb)}</div>
                  </TableCell>
                  <TableCell className="overflow-visible! text-right">
                    <div className="flex justify-end gap-2">
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
      {editing && (
        <EditProductDialog product={editing} onClose={() => setEditing(null)} />
      )}
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

  // Radix portals DialogContent/DialogOverlay elsewhere in the DOM, but React
  // bubbles their synthetic events through the component tree — so a click on
  // the close button or overlay still reaches the row's onClick unless this
  // whole subtree stops it, not just the trigger button.
  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: pure click-bubbling boundary around real interactive children, not itself perceivable by AT.
    <div
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
    >
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="Price history"
            title="Price history"
          >
            <History className="size-4" />
          </Button>
        </DialogTrigger>
        <DialogContent className="sm:max-w-3xl">
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
                  <TableHead>Changed by</TableHead>
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
                      {h.changed_by_full_name ?? "Unknown user"}
                    </TableCell>
                    <TableCell className="text-muted-foreground whitespace-nowrap">
                      {h.changed_at
                        ? new Date(h.changed_at).toLocaleString()
                        : "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
