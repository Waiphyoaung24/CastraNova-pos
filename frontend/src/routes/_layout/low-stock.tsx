import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { AlertTriangle } from "lucide-react"
import { useState } from "react"

import { type BulkMinStockUpdate, LowStockService } from "@/client"
import { LIST_SCROLL, ListShell } from "@/components/Common/ListShell"
import { PageHeader } from "@/components/Common/PageHeader"
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
import useCustomToast from "@/hooks/useCustomToast"
import { useIsMobile } from "@/hooks/useMobile"
import { useRole } from "@/hooks/useRole"
import { trackingModeLabel } from "@/lib/labels"
import { buildBulkMinStockUpdate } from "@/lib/low-stock"
import { requireAuth } from "@/lib/route-guards"

// Both roles (FR-016). No cost fields — safe for staff. Admin can edit the
// per-product reorder threshold inline and save all changes via the bulk
// endpoint; staff see the list read-only.
export const Route = createFileRoute("/_layout/low-stock")({
  component: LowStock,
  beforeLoad: requireAuth,
  head: () => ({
    meta: [{ title: "Low stock - CastraNova POS" }],
  }),
})

function LowStock() {
  const { isAdmin } = useRole()
  const isMobile = useIsMobile()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()
  const [edits, setEdits] = useState<Record<string, string>>({})

  const { data, isPending, isError, isPlaceholderData, isFetching } = useQuery({
    queryKey: ["low-stock"],
    queryFn: () => LowStockService.readLowStock(),
  })
  const listLoading = isPlaceholderData || isFetching

  const saveMutation = useMutation({
    mutationFn: (body: BulkMinStockUpdate) =>
      LowStockService.bulkSetMinStockLevel({ requestBody: body }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["low-stock"] })
      queryClient.invalidateQueries({ queryKey: ["products"] })
      setEdits({})
      showSuccessToast("Reorder levels updated.")
    },
    onError: () => showErrorToast("Could not save the levels. Try again."),
  })

  const rows = data ?? []
  const valueFor = (productId: string, level: number) =>
    edits[productId] ?? String(level)
  const pendingItems = buildBulkMinStockUpdate(
    rows.map((r) => ({
      productId: r.product_id,
      value: valueFor(r.product_id, r.min_stock_level),
      original: r.min_stock_level,
    })),
  )

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Low stock"
        description="Products that have dropped to their reorder level."
      />

      <Alert>
        <AlertTriangle />
        <AlertTitle>Your reorder watchlist</AlertTitle>
        <AlertDescription>
          These products have dropped to or below their reorder level — restock
          them soon.{" "}
          {isAdmin
            ? "Adjust any min level inline, then Save changes to update them all at once."
            : "Min levels are set by an admin."}
        </AlertDescription>
      </Alert>

      {isAdmin && (
        <div>
          <Button
            type="button"
            disabled={pendingItems.length === 0 || saveMutation.isPending}
            onClick={() => saveMutation.mutate({ items: pendingItems })}
          >
            {saveMutation.isPending
              ? "Saving…"
              : `Save changes${pendingItems.length ? ` (${pendingItems.length})` : ""}`}
          </Button>
        </div>
      )}

      {isPending ? (
        <p className="text-muted-foreground py-6 text-center text-sm">
          Loading…
        </p>
      ) : isError ? (
        <p className="text-muted-foreground py-6 text-center text-sm">
          Could not load low-stock items.
        </p>
      ) : rows.length === 0 ? (
        <p className="text-muted-foreground py-6 text-center text-sm">
          Nothing below threshold. 🎉
        </p>
      ) : isMobile ? (
        <ListShell loading={listLoading}>
          <div className="space-y-3">
            {rows.map((r) => (
              <div key={r.product_id} className="bg-card rounded-lg border p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="num font-medium">{r.sku}</span>
                      <Badge variant="secondary">
                        {trackingModeLabel(r.tracking_mode)}
                      </Badge>
                    </div>
                    <p className="truncate text-sm">{r.model_name}</p>
                  </div>
                  <div className="shrink-0 text-right">
                    <div className="num text-destructive text-lg leading-none font-semibold">
                      {r.on_hand}
                    </div>
                    <div className="text-muted-foreground mt-1 text-xs">
                      in stock
                    </div>
                  </div>
                </div>
                <div className="mt-3 flex items-center justify-between gap-3 border-t pt-3">
                  <span className="text-muted-foreground text-sm">
                    Reorder at
                  </span>
                  {isAdmin ? (
                    <Input
                      type="number"
                      min={0}
                      step={1}
                      aria-label={`Reorder level for ${r.sku}`}
                      className="num w-24 text-right"
                      placeholder="e.g. 5"
                      value={valueFor(r.product_id, r.min_stock_level)}
                      onChange={(e) =>
                        setEdits((prev) => ({
                          ...prev,
                          [r.product_id]: e.target.value,
                        }))
                      }
                    />
                  ) : (
                    <span className="num font-medium">{r.min_stock_level}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </ListShell>
      ) : (
        <ListShell loading={listLoading}>
          <Table containerClassName={LIST_SCROLL}>
            <TableHeader className="bg-background sticky top-0 z-10">
              <TableRow>
                <TableHead>SKU</TableHead>
                <TableHead>Model</TableHead>
                <TableHead>Type</TableHead>
                <TableHead className="text-right">In stock</TableHead>
                <TableHead className="text-right">Reorder at</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.product_id}>
                  <TableCell className="num font-medium">{r.sku}</TableCell>
                  <TableCell>{r.model_name}</TableCell>
                  <TableCell>
                    <Badge variant="secondary">
                      {trackingModeLabel(r.tracking_mode)}
                    </Badge>
                  </TableCell>
                  <TableCell className="num text-right font-semibold text-destructive">
                    {r.on_hand}
                  </TableCell>
                  <TableCell className="text-right">
                    {isAdmin ? (
                      <Input
                        type="number"
                        min={0}
                        step={1}
                        aria-label={`Reorder level for ${r.sku}`}
                        className="num ml-auto w-24 text-right"
                        placeholder="e.g. 5"
                        value={valueFor(r.product_id, r.min_stock_level)}
                        onChange={(e) =>
                          setEdits((prev) => ({
                            ...prev,
                            [r.product_id]: e.target.value,
                          }))
                        }
                      />
                    ) : (
                      <span className="num">{r.min_stock_level}</span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </ListShell>
      )}
    </div>
  )
}
