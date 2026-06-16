import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { ChevronDown, ChevronRight } from "lucide-react"
import { useMemo, useState } from "react"

import { DashboardsService, SuppliersService } from "@/client"
import { PrintLabelButton } from "@/components/PrintLabelButton"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
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
import { useRole } from "@/hooks/useRole"
import { requireAuth } from "@/lib/route-guards"
import { deriveCategories, filterStockRows } from "@/lib/stock-on-hand"

export const Route = createFileRoute("/_layout/stock")({
  component: StockOnHand,
  beforeLoad: requireAuth,
  head: () => ({
    meta: [{ title: "Stock on hand - CastraNova POS" }],
  }),
})

// Radix Select forbids an empty-string item value, so "all" uses a sentinel.
const ALL = "__all__"

function StockOnHand() {
  const { isAdmin } = useRole()
  const [category, setCategory] = useState("")
  const [query, setQuery] = useState("")
  const [supplierId, setSupplierId] = useState("")
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const { data: stock } = useQuery({
    queryKey: ["stock-on-hand", supplierId],
    queryFn: () =>
      DashboardsService.getStockOnHand({
        supplier: supplierId || undefined,
      }),
  })
  // Suppliers list is admin-gated; only fetch it for the admin supplier filter.
  const { data: suppliers } = useQuery({
    queryKey: ["suppliers"],
    queryFn: () => SuppliersService.readSuppliers(),
    enabled: isAdmin,
    staleTime: 5 * 60 * 1000,
  })

  const allRows = stock?.rows ?? []
  const categories = useMemo(() => deriveCategories(allRows), [allRows])
  const rows = useMemo(
    () => filterStockRows(allRows, { category, query }),
    [allRows, category, query],
  )

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Stock on hand</h1>
        <p className="text-muted-foreground">
          Current quantity on hand across the catalog.
        </p>
      </div>

      <div className="flex flex-wrap gap-3">
        <Input
          placeholder="Search SKU or model…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-full sm:w-64"
        />
        <Select
          value={category === "" ? ALL : category}
          onValueChange={(v) => setCategory(v === ALL ? "" : v)}
        >
          <SelectTrigger className="w-full sm:w-48">
            <SelectValue placeholder="All categories" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All categories</SelectItem>
            {categories.map((c) => (
              <SelectItem key={c} value={c}>
                {c}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {isAdmin ? (
          <Select
            value={supplierId === "" ? ALL : supplierId}
            onValueChange={(v) => setSupplierId(v === ALL ? "" : v)}
          >
            <SelectTrigger className="w-full sm:w-48">
              <SelectValue placeholder="All suppliers" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All suppliers</SelectItem>
              {(suppliers ?? []).map((s) => (
                <SelectItem key={s.id} value={s.id}>
                  {s.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : null}
      </div>

      {rows.length === 0 ? (
        <p className="text-muted-foreground py-6 text-center text-sm">
          No stock matches these filters.
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-8" />
              <TableHead>SKU</TableHead>
              <TableHead>Model</TableHead>
              <TableHead>Category</TableHead>
              <TableHead>Mode</TableHead>
              <TableHead className="text-right">On hand</TableHead>
              <TableHead className="w-0" aria-label="Labels" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => {
              const isQuantity = r.tracking_mode === "QUANTITY"
              const isOpen = expandedId === r.product_id
              return (
                <StockRow
                  key={r.product_id}
                  productId={r.product_id}
                  sku={r.sku}
                  modelName={r.model_name}
                  category={r.category}
                  trackingMode={r.tracking_mode}
                  quantityOnHand={r.quantity_on_hand}
                  isQuantity={isQuantity}
                  isOpen={isOpen}
                  onToggle={() => setExpandedId(isOpen ? null : r.product_id)}
                />
              )
            })}
          </TableBody>
        </Table>
      )}
    </div>
  )
}

interface StockRowProps {
  productId: string
  sku: string
  modelName: string
  category: string | null
  trackingMode: string
  quantityOnHand: number
  isQuantity: boolean
  isOpen: boolean
  onToggle: () => void
}

function StockRow({
  productId,
  sku,
  modelName,
  category,
  trackingMode,
  quantityOnHand,
  isQuantity,
  isOpen,
  onToggle,
}: StockRowProps) {
  // QUANTITY rows drill into FIFO batches; SERIALIZED rows drill into in-stock
  // units (each with its CastraNova barcode). Both fetch lazily on expand.
  const { data: batches, isPending: batchesPending } = useQuery({
    queryKey: ["stock-batches", productId],
    queryFn: () => DashboardsService.getStockOnHandBatches({ productId }),
    enabled: isQuantity && isOpen,
  })
  const { data: units, isPending: unitsPending } = useQuery({
    queryKey: ["stock-units", productId],
    queryFn: () => DashboardsService.getStockOnHandUnits({ productId }),
    enabled: !isQuantity && isOpen,
  })

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
        <TableCell className="text-muted-foreground">
          {category ?? "—"}
        </TableCell>
        <TableCell>
          <Badge variant="secondary">{trackingMode}</Badge>
        </TableCell>
        <TableCell className="num text-right">{quantityOnHand}</TableCell>
        <TableCell className="text-right">
          {isQuantity ? (
            <PrintLabelButton target={{ kind: "sku", productId, sku }} />
          ) : null}
        </TableCell>
      </TableRow>
      {isOpen ? (
        <TableRow>
          <TableCell colSpan={7} className="bg-muted/30">
            {isQuantity ? (
              batchesPending ? (
                <p className="text-muted-foreground py-2 text-sm">Loading…</p>
              ) : (batches ?? []).length === 0 ? (
                <p className="text-muted-foreground py-2 text-sm">
                  No open batches.
                </p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Batch</TableHead>
                      <TableHead className="text-right">Remaining</TableHead>
                      <TableHead>Received</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(batches ?? []).map((b) => (
                      <TableRow key={b.batch_no}>
                        <TableCell className="num">{b.batch_no}</TableCell>
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
            ) : unitsPending ? (
              <p className="text-muted-foreground py-2 text-sm">Loading…</p>
            ) : (units ?? []).length === 0 ? (
              <p className="text-muted-foreground py-2 text-sm">
                No units in stock.
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>CastraNova barcode</TableHead>
                    <TableHead>Supplier serial</TableHead>
                    <TableHead>State</TableHead>
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
                      <TableCell>
                        <Badge variant="outline">{u.current_state}</Badge>
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
            )}
          </TableCell>
        </TableRow>
      ) : null}
    </>
  )
}
