import { useMutation, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { useId, useState } from "react"

import { ApiError, StockAdjustmentsService } from "@/client"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import useCustomToast from "@/hooks/useCustomToast"
import { requireAdmin } from "@/lib/route-guards"
import {
  type AdjustmentDraft,
  buildAdjustmentPayload,
  canSubmitAdjustment,
  emptyAdjustmentDraft,
} from "@/lib/stock-adjustment"

export const Route = createFileRoute("/_layout/stock-adjustment")({
  component: StockAdjustment,
  beforeLoad: () => requireAdmin(),
  head: () => ({
    meta: [{ title: "Stock adjustment - CastraNova POS" }],
  }),
})

function StockAdjustment() {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()
  const barcodeId = useId()
  const skuId = useId()
  const deltaId = useId()
  const costId = useId()
  const reasonId = useId()

  const [draft, setDraft] = useState<AdjustmentDraft>(emptyAdjustmentDraft)
  const set = (patch: Partial<AdjustmentDraft>) =>
    setDraft((d) => ({ ...d, ...patch }))

  const mutation = useMutation({
    mutationFn: () =>
      StockAdjustmentsService.createStockAdjustment({
        requestBody: buildAdjustmentPayload(draft, crypto.randomUUID()),
      }),
    onSuccess: () => {
      // On-hand totals and any open search results are now stale.
      queryClient.invalidateQueries({ queryKey: ["stock-on-hand"] })
      queryClient.invalidateQueries({ queryKey: ["search-sku"] })
      queryClient.invalidateQueries({ queryKey: ["search-serial"] })
      showSuccessToast("Adjustment recorded.")
      setDraft({ ...emptyAdjustmentDraft, targetKind: draft.targetKind })
    },
    onError: (err) => {
      // Surface the server reason on a conflict (e.g. unit not IN_STOCK,
      // insufficient stock for a negative delta); generic otherwise.
      const detail =
        err instanceof ApiError && err.body && typeof err.body === "object"
          ? (err.body as { detail?: string }).detail
          : undefined
      showErrorToast(detail ?? "Could not record the adjustment.")
    },
  })

  const deltaNum = Number.parseInt(draft.qtyDelta, 10)
  const showCost =
    draft.targetKind === "QUANTITY" && Number.isFinite(deltaNum) && deltaNum > 0

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Stock adjustment</h1>
        <p className="text-muted-foreground">
          Write off or recount stock. Adjustments are recorded permanently and
          cannot be undone.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>New adjustment</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Tabs
            value={draft.targetKind}
            onValueChange={(v) =>
              setDraft({
                ...emptyAdjustmentDraft,
                targetKind: v as AdjustmentDraft["targetKind"],
              })
            }
          >
            <TabsList>
              <TabsTrigger value="UNIT">Serialized unit</TabsTrigger>
              <TabsTrigger value="QUANTITY">Quantity SKU</TabsTrigger>
            </TabsList>
          </Tabs>

          {draft.targetKind === "UNIT" ? (
            <div className="space-y-2">
              <Label htmlFor={barcodeId}>CastraNova barcode</Label>
              <Input
                id={barcodeId}
                value={draft.barcode}
                onChange={(e) => set({ barcode: e.target.value })}
                placeholder="Scan or type the unit barcode…"
              />
              <p className="text-muted-foreground text-sm">
                The unit moves to the terminal ADJUSTED_OUT state.
              </p>
            </div>
          ) : (
            <>
              <div className="space-y-2">
                <Label htmlFor={skuId}>SKU</Label>
                <Input
                  id={skuId}
                  value={draft.sku}
                  onChange={(e) => set({ sku: e.target.value })}
                  placeholder="Scan or type the SKU…"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor={deltaId}>Quantity delta</Label>
                <Input
                  id={deltaId}
                  inputMode="numeric"
                  value={draft.qtyDelta}
                  onChange={(e) => set({ qtyDelta: e.target.value })}
                  placeholder="e.g. -3 (write-off) or 5 (found)"
                />
                <p className="text-muted-foreground text-sm">
                  Negative consumes oldest batches first (FIFO); positive adds a
                  new adjustment batch.
                </p>
              </div>
              {showCost ? (
                <div className="space-y-2">
                  <Label htmlFor={costId}>Purchase cost (THB)</Label>
                  <Input
                    id={costId}
                    inputMode="decimal"
                    value={draft.purchaseCost}
                    onChange={(e) => set({ purchaseCost: e.target.value })}
                    placeholder="Cost basis for the new batch"
                  />
                </div>
              ) : null}
            </>
          )}

          <div className="space-y-2">
            <Label htmlFor={reasonId}>Reason</Label>
            <Input
              id={reasonId}
              value={draft.reason}
              maxLength={512}
              onChange={(e) => set({ reason: e.target.value })}
              placeholder="Why is this adjustment being made?"
            />
          </div>

          <Button
            type="button"
            disabled={!canSubmitAdjustment(draft) || mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "Recording…" : "Record adjustment"}
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
