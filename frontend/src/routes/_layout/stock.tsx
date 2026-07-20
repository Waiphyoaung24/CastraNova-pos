import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { ChevronDown, ChevronRight, Warehouse } from "lucide-react"
import { useCallback, useState } from "react"

import { DashboardsService, type SupplierOption } from "@/client"
import { EntityCombobox } from "@/components/Common/EntityCombobox"
import { ListShell } from "@/components/Common/ListShell"
import { ListTable } from "@/components/Common/ListTable"
import { PageHeader } from "@/components/Common/PageHeader"
import { PaginationControls } from "@/components/Common/PaginationControls"
import { PrintLabelButton } from "@/components/PrintLabelButton"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
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
import { useRole } from "@/hooks/useRole"
import { useSupplierOptions } from "@/hooks/useSupplierOptions"
import { unitStatusLabel } from "@/lib/labels"
import { requireAuth } from "@/lib/route-guards"

export const Route = createFileRoute("/_layout/stock")({
  component: StockOnHand,
  beforeLoad: requireAuth,
  head: () => ({
    meta: [{ title: "Stock on hand - CastraNova POS" }],
  }),
})

// Column widths in header order (expander, SKU, Model, Brand, Category,
// In stock, Labels); sum to 100%.
const STOCK_WIDTHS = ["5%", "14%", "23%", "15%", "15%", "10%", "18%"]

function StockOnHand() {
  const { isAdmin } = useRole()
  const isMobile = useIsMobile()
  const [query, setQuery] = useState("")
  const [brand, setBrand] = useState("")
  const [category, setCategory] = useState("")
  const [supplierId, setSupplierId] = useState("")
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const debouncedQuery = useDebouncedValue(query)
  const debouncedBrand = useDebouncedValue(brand)
  const debouncedCategory = useDebouncedValue(category)
  const pagination = usePagination()

  const resetList = () => {
    pagination.reset()
    setExpandedId(null)
  }

  const {
    data: stock,
    isPlaceholderData,
    isFetching,
  } = useQuery({
    queryKey: [
      "stock-on-hand",
      {
        page: pagination.page,
        q: debouncedQuery,
        brand: debouncedBrand,
        category: debouncedCategory,
        supplierId,
      },
    ],
    queryFn: () =>
      DashboardsService.getStockOnHand({
        q: debouncedQuery || undefined,
        brand: debouncedBrand || undefined,
        category: debouncedCategory || undefined,
        supplier: supplierId || undefined,
        skip: pagination.skip,
        limit: pagination.limit,
      }),
    placeholderData: keepPreviousData,
  })
  const listLoading = isPlaceholderData || isFetching
  const { data: suppliers } = useSupplierOptions({ enabled: isAdmin })
  const rows = stock?.rows ?? []
  const selectedSupplier = suppliers?.find(
    (supplier) => supplier.id === supplierId,
  )
  const inStockLabel = selectedSupplier
    ? `In stock (${selectedSupplier.name})`
    : "In stock"
  const getSupplierKey = useCallback(
    (supplier: SupplierOption) => supplier.id,
    [],
  )
  const getSupplierLabel = useCallback(
    (supplier: SupplierOption) => supplier.name,
    [],
  )

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Stock on hand"
        description="What's in stock right now across the shop."
      />

      <Alert>
        <Warehouse />
        <AlertTitle>Check what's in stock</AlertTitle>
        <AlertDescription>
          Search by SKU or model, or narrow the list with the filters. Tap a row
          to see each delivery or unit. Print shelf or unit labels straight from
          the list.
        </AlertDescription>
      </Alert>

      <div className="flex flex-wrap gap-3">
        <Input
          placeholder="Search by name or barcode…"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value)
            resetList()
          }}
          className="w-full sm:w-64"
        />
        <Input
          aria-label="Brand filter"
          placeholder="Filter by brand…"
          value={brand}
          onChange={(event) => {
            setBrand(event.target.value)
            resetList()
          }}
          className="w-full sm:w-48"
        />
        <Input
          aria-label="Category filter"
          placeholder="Filter by category…"
          value={category}
          onChange={(event) => {
            setCategory(event.target.value)
            resetList()
          }}
          className="w-full sm:w-48"
        />
        {isAdmin ? (
          <div className="w-full sm:w-48">
            <EntityCombobox
              items={suppliers ?? []}
              value={supplierId || undefined}
              onChange={(value) => {
                setSupplierId(value ?? "")
                resetList()
              }}
              getKey={getSupplierKey}
              getLabel={getSupplierLabel}
              placeholder="All suppliers"
              searchPlaceholder="Search suppliers…"
              emptyText="No suppliers available"
              allowClear
              ariaLabel="Supplier filter"
            />
          </div>
        ) : null}
      </div>

      {rows.length === 0 ? (
        <p className="text-muted-foreground py-6 text-center text-sm">
          {stock ? "No stock matches these filters." : "Loading…"}
        </p>
      ) : isMobile ? (
        <ListShell loading={listLoading}>
          <div className="space-y-3">
            {rows.map((r) => {
              const isQuantity = r.tracking_mode === "QUANTITY"
              const isOpen = expandedId === r.product_id
              return (
                <StockCard
                  key={r.product_id}
                  productId={r.product_id}
                  sku={r.sku}
                  modelName={r.model_name}
                  brand={r.brand}
                  category={r.category}
                  quantityOnHand={r.quantity_on_hand}
                  isQuantity={isQuantity}
                  isOpen={isOpen}
                  onToggle={() => setExpandedId(isOpen ? null : r.product_id)}
                />
              )
            })}
          </div>
        </ListShell>
      ) : (
        <ListShell loading={listLoading}>
          <ListTable
            widths={STOCK_WIDTHS}
            minWidth={900}
            head={
              <TableRow>
                <TableHead aria-label="Expand" />
                <TableHead>SKU</TableHead>
                <TableHead>Model</TableHead>
                <TableHead>Brand</TableHead>
                <TableHead>Category</TableHead>
                <TableHead className="text-right">{inStockLabel}</TableHead>
                <TableHead aria-label="Labels" />
              </TableRow>
            }
          >
            {rows.map((r) => {
              const isQuantity = r.tracking_mode === "QUANTITY"
              const isOpen = expandedId === r.product_id
              return (
                <StockRow
                  key={r.product_id}
                  productId={r.product_id}
                  sku={r.sku}
                  modelName={r.model_name}
                  brand={r.brand}
                  category={r.category}
                  quantityOnHand={r.quantity_on_hand}
                  isQuantity={isQuantity}
                  isOpen={isOpen}
                  onToggle={() => setExpandedId(isOpen ? null : r.product_id)}
                />
              )
            })}
          </ListTable>
        </ListShell>
      )}
      <PaginationControls
        total={stock?.count ?? 0}
        pageSize={pagination.pageSize}
        page={pagination.page}
        onPageChange={(nextPage) => {
          pagination.setPage(nextPage)
          setExpandedId(null)
        }}
      />
    </div>
  )
}

interface StockItemProps {
  productId: string
  sku: string
  modelName: string
  brand: string | null
  category: string | null
  quantityOnHand: number
  isQuantity: boolean
  isOpen: boolean
  onToggle: () => void
}

/**
 * Lazily-loaded expansion detail for one product. QUANTITY products drill into
 * FIFO batches; SERIALIZED products drill into in-stock units (each with its
 * CastraNova barcode). Rendered only when the row/card is open, so the lookup
 * fires on first expand. Shared by the desktop table row and the mobile card.
 */
function StockDrillDown({
  productId,
  isQuantity,
}: Pick<StockItemProps, "productId" | "isQuantity">) {
  const { data: batches, isPending: batchesPending } = useQuery({
    queryKey: ["stock-batches", productId],
    queryFn: () => DashboardsService.getStockOnHandBatches({ productId }),
    enabled: isQuantity,
  })
  const { data: units, isPending: unitsPending } = useQuery({
    queryKey: ["stock-units", productId],
    queryFn: () => DashboardsService.getStockOnHandUnits({ productId }),
    enabled: !isQuantity,
  })

  if (isQuantity) {
    if (batchesPending) {
      return <p className="text-muted-foreground py-2 text-sm">Loading…</p>
    }
    if ((batches ?? []).length === 0) {
      return (
        <p className="text-muted-foreground py-2 text-sm">
          No deliveries in stock.
        </p>
      )
    }
    return (
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Delivery</TableHead>
            <TableHead>Supplier</TableHead>
            <TableHead className="text-right">Remaining</TableHead>
            <TableHead>Received</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {(batches ?? []).map((b) => (
            <TableRow key={b.batch_no}>
              <TableCell className="num">{b.batch_no}</TableCell>
              <TableCell className="text-muted-foreground">
                {b.supplier ?? "—"}
              </TableCell>
              <TableCell className="num text-right">
                {b.remaining_qty}
              </TableCell>
              <TableCell className="text-muted-foreground">
                {new Date(b.received_at).toLocaleDateString()}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    )
  }

  if (unitsPending) {
    return <p className="text-muted-foreground py-2 text-sm">Loading…</p>
  }
  if ((units ?? []).length === 0) {
    return (
      <p className="text-muted-foreground py-2 text-sm">No units in stock.</p>
    )
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Shop barcode</TableHead>
          <TableHead>Maker's serial no.</TableHead>
          <TableHead>Supplier</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Received</TableHead>
          <TableHead className="w-0" aria-label="Actions" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {(units ?? []).map((u) => (
          <TableRow key={u.castranova_barcode}>
            <TableCell className="num font-medium">
              {u.castranova_barcode}
            </TableCell>
            <TableCell className="num">{u.supplier_serial}</TableCell>
            <TableCell className="text-muted-foreground">
              {u.supplier ?? "—"}
            </TableCell>
            <TableCell>
              <Badge variant="outline">
                {unitStatusLabel(u.current_state)}
              </Badge>
            </TableCell>
            <TableCell className="text-muted-foreground">
              {new Date(u.received_at).toLocaleDateString()}
            </TableCell>
            <TableCell className="text-right">
              <PrintLabelButton
                target={{
                  kind: "unit",
                  unitId: u.id,
                  serial: u.supplier_serial,
                }}
              />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function StockRow({
  productId,
  sku,
  modelName,
  brand,
  category,
  quantityOnHand,
  isQuantity,
  isOpen,
  onToggle,
}: StockItemProps) {
  return (
    <>
      <TableRow>
        <TableCell>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-8"
            aria-label={isOpen ? `Collapse ${sku}` : `Expand ${sku}`}
            aria-expanded={isOpen}
            onClick={onToggle}
          >
            {isOpen ? <ChevronDown /> : <ChevronRight />}
          </Button>
        </TableCell>
        <TableCell className="num font-medium">{sku}</TableCell>
        <TableCell>{modelName}</TableCell>
        <TableCell className="text-muted-foreground">{brand ?? "—"}</TableCell>
        <TableCell className="text-muted-foreground">
          {category ?? "—"}
        </TableCell>
        <TableCell className="num text-right">{quantityOnHand}</TableCell>
        <TableCell className="overflow-visible! text-right">
          {isQuantity ? (
            <PrintLabelButton target={{ kind: "sku", productId, sku }} />
          ) : null}
        </TableCell>
      </TableRow>
      {isOpen ? (
        <TableRow>
          <TableCell
            colSpan={7}
            className="bg-muted/30 overflow-visible! whitespace-normal"
          >
            <StockDrillDown productId={productId} isQuantity={isQuantity} />
          </TableCell>
        </TableRow>
      ) : null}
    </>
  )
}

/**
 * Mobile presentation of one product: a tap-to-expand card replacing the
 * desktop table row (the catalog table can't fit a phone without horizontal
 * scroll). The whole header is the toggle; the SKU print label and drill-down
 * detail live in the expanded panel so no buttons nest inside the toggle.
 */
function StockCard({
  productId,
  sku,
  modelName,
  brand,
  category,
  quantityOnHand,
  isQuantity,
  isOpen,
  onToggle,
}: StockItemProps) {
  const brandCategory = [brand, category].filter(Boolean).join(" · ")
  return (
    <div className="bg-card overflow-hidden rounded-lg border">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={isOpen}
        aria-label={isOpen ? `Collapse ${sku}` : `Expand ${sku}`}
        className="flex w-full items-center gap-3 p-4 text-left"
      >
        <span className="text-muted-foreground shrink-0">
          {isOpen ? (
            <ChevronDown className="size-4" />
          ) : (
            <ChevronRight className="size-4" />
          )}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="num font-medium">{sku}</span>
          </div>
          <p className="truncate text-sm">{modelName}</p>
          {brandCategory ? (
            <p className="text-muted-foreground truncate text-xs">
              {brandCategory}
            </p>
          ) : null}
        </div>
        <div className="shrink-0 text-right">
          <div className="num text-lg leading-none font-semibold">
            {quantityOnHand}
          </div>
          <div className="text-muted-foreground mt-1 text-xs">in stock</div>
        </div>
      </button>
      {isOpen ? (
        <div className="bg-muted/30 space-y-3 border-t p-4">
          {isQuantity ? (
            <PrintLabelButton target={{ kind: "sku", productId, sku }} />
          ) : null}
          <StockDrillDown productId={productId} isQuantity={isQuantity} />
        </div>
      ) : null}
    </div>
  )
}
