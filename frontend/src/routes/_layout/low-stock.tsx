import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { useState } from "react"

import { type BulkMinStockUpdate, LowStockService } from "@/client"
import { PageHeader } from "@/components/Common/PageHeader"
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
import { useRole } from "@/hooks/useRole"
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
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()
  const [edits, setEdits] = useState<Record<string, string>>({})

  const { data, isPending, isError } = useQuery({
    queryKey: ["low-stock"],
    queryFn: () => LowStockService.readLowStock(),
  })

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
        description="Products below their reorder threshold."
      />

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
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>SKU</TableHead>
              <TableHead>Model</TableHead>
              <TableHead>Tracking</TableHead>
              <TableHead className="text-right">On hand</TableHead>
              <TableHead className="text-right">Min level</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.product_id}>
                <TableCell className="num font-medium">{r.sku}</TableCell>
                <TableCell>{r.model_name}</TableCell>
                <TableCell>
                  <Badge variant="secondary">{r.tracking_mode}</Badge>
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
                      aria-label={`Min stock level for ${r.sku}`}
                      className="num ml-auto w-24 text-right"
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
      )}
    </div>
  )
}
